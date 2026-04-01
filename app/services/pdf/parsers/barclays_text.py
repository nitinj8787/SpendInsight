"""Barclays-specific text-based PDF parser.

Uses raw text extraction from pdfplumber (not tables) and a two-state machine
tailored to the Barclays printed-statement layout:

* Dates appear as ``DD MMM`` (e.g. "04 Oct") at the start of a line.
* Multiple transactions can appear under the same date.
* Descriptions may span several lines.
* Amounts appear at the end of a description block, optionally suffixed with
  ``DR`` (debit / expense) or ``CR`` (credit / income).
* Lines like "Start balance" and "End balance" are ignored.

Example statement fragment::

    04 Oct  Start balance                     9,629.70
    06 Oct  Direct Debit to Sky Digital
              Sky subscription                   38.00 DR
            Direct Debit to Thames Water
              Water rates                        67.00 DR
    14 Oct  Received From Danbro Employment  7,726.72 CR

The parser emits one :class:`~app.schemas.transaction.TransactionCreate` per
amount line found, associating it with the most recently seen date.
"""

from __future__ import annotations

import datetime
import io
import logging
import re
from decimal import Decimal, InvalidOperation

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.categorizer import TransactionCategorizer
from app.services.pdf.base import BasePDFParser

logger = logging.getLogger(__name__)

_categorizer = TransactionCategorizer()

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# A line that starts with a Barclays-style date: "DD Mon" (e.g. "04 Oct").
# Optionally followed by the rest of the line.
_DATE_LINE_RE = re.compile(
    r"^(?P<date>\d{1,2}\s+[A-Za-z]{3})"
    r"(?:\s+(?P<rest>.+))?$",
)

# An amount (with optional thousand-separator commas) possibly followed by DR
# or CR at the end of a line.  One or two decimal places are accepted.
_AMOUNT_LINE_RE = re.compile(
    r"^(?P<desc>.*?)\s*"
    r"(?P<amount>[£$€]?\s*[\d,]+\.\d{1,2})"
    r"\s*(?P<direction>DR|CR)?\s*$",
    re.IGNORECASE,
)

# Lines to skip outright (balance markers and column headers).
# Matched against both the full original line AND extracted descriptions.
_SKIP_LINE_RE = re.compile(
    r"^\s*(?:"
    r"(?:start|end|opening|closing|brought\s+forward|carried\s+forward)\s+balance"
    r"|date|description|details|payment\s+(?:in|out)|balance"
    r"|debit|credit|paid\s+(?:in|out)"
    r")\b",
    re.IGNORECASE,
)

_DATE_FORMATS = ["%d %b", "%d %B"]


def _parse_barclays_date(value: str) -> datetime.date | None:
    """Parse a Barclays ``DD Mon`` (or ``DD Month``) date string."""
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            # strptime uses 1900 when no year is given — replace with current.
            return parsed.replace(year=datetime.date.today().year).date()
        except ValueError:
            continue
    return None


def _parse_amount_decimal(value: str) -> Decimal | None:
    """Parse a monetary amount string such as ``1,234.56`` or ``£38.00``."""
    cleaned = re.sub(r"[£$€\s,]", "", value)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# State machine states
# ---------------------------------------------------------------------------

class _State:
    SEEKING_DATE = "SEEKING_DATE"
    BUILDING_ENTRY = "BUILDING_ENTRY"


# ---------------------------------------------------------------------------
# BarclaysPDFParser
# ---------------------------------------------------------------------------


class BarclaysPDFParser(BasePDFParser):
    """Text-based parser for Barclays printed bank statement PDFs.

    Unlike :class:`~app.services.pdf.parsers.barclays.BarclaysParser`
    (which relies on pdfplumber table extraction), this parser works directly
    on the raw text of each page.  It is more robust for statements where
    table borders are not recognised by pdfplumber.

    State machine
    ~~~~~~~~~~~~~
    The parser walks lines using two states:

    * **SEEKING_DATE** — looking for a line that starts with a ``DD Mon``
      date token.
    * **BUILDING_ENTRY** — accumulating description parts until a line that
      ends with ``amount [DR|CR]`` is encountered, at which point a
      transaction is emitted and the machine returns to SEEKING_DATE to look
      for the next date (which may be the same date as the current one, since
      multiple transactions can share a date).

    The current date is carried forward across continuation lines so that
    transactions grouped under the same date header all receive that date.
    """

    source = "barclays"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bBarclays\b", re.IGNORECASE),
    ]

    def can_parse(self, text: str) -> bool:
        return any(p.search(text) for p in self.IDENTIFIER_PATTERNS)

    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Parse Barclays PDF *content* into normalised transactions.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        list[TransactionCreate]
            Parsed transactions (empty list if none found).
        """
        logger.debug("BarclaysPDFParser.parse() called")
        lines = self._extract_lines(content)
        transactions = self._run_state_machine(lines)
        logger.info("BarclaysPDFParser extracted %d transaction(s)", len(transactions))
        return transactions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_lines(self, content: bytes) -> list[str]:
        """Return non-blank lines from every page of the PDF."""
        lines: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                raw = page.extract_text() or ""
                for line in raw.splitlines():
                    stripped = line.strip()
                    if stripped:
                        lines.append(stripped)
        return lines

    def _run_state_machine(self, lines: list[str]) -> list[TransactionCreate]:
        """Walk *lines* through the Barclays state machine."""
        transactions: list[TransactionCreate] = []
        state = _State.SEEKING_DATE
        current_date: datetime.date | None = None
        desc_parts: list[str] = []

        for line in lines:
            if _SKIP_LINE_RE.match(line):
                logger.debug("BarclaysPDFParser: skipping noise line: %r", line)
                continue

            date_match = _DATE_LINE_RE.match(line)

            if date_match:
                # Flush any pending description (amount never arrived)
                desc_parts = []
                state = _State.SEEKING_DATE

                parsed_date = _parse_barclays_date(date_match.group("date"))
                if parsed_date is not None:
                    current_date = parsed_date
                    logger.debug("BarclaysPDFParser: date = %s", current_date)

                rest = (date_match.group("rest") or "").strip()
                if not rest:
                    # Pure date header line — nothing more to do
                    continue

                # The rest of the line may already contain description+amount
                # or just a description start.
                txn = self._try_parse_amount_line(rest, current_date)
                if txn is not None:
                    transactions.append(txn)
                    state = _State.SEEKING_DATE
                    desc_parts = []
                else:
                    # Begin accumulating a multi-line description
                    desc_parts = [rest]
                    state = _State.BUILDING_ENTRY

            elif state == _State.BUILDING_ENTRY:
                # See if this line closes the current entry
                txn = self._try_parse_amount_line(line, current_date, desc_parts)
                if txn is not None:
                    transactions.append(txn)
                    desc_parts = []
                    state = _State.SEEKING_DATE
                else:
                    # Another description continuation line
                    desc_parts.append(line)

            else:
                # SEEKING_DATE but no date prefix — could be a one-liner
                # description+amount without a preceding date line.
                if current_date is not None:
                    txn = self._try_parse_amount_line(line, current_date)
                    if txn is not None:
                        transactions.append(txn)
                    else:
                        # Treat as start of a new entry
                        desc_parts = [line]
                        state = _State.BUILDING_ENTRY

        return transactions

    def _try_parse_amount_line(
        self,
        line: str,
        date: datetime.date | None,
        preceding_desc_parts: list[str] | None = None,
    ) -> TransactionCreate | None:
        """Try to extract a transaction from *line*.

        If *line* ends with a monetary amount (and optional DR/CR), a
        :class:`TransactionCreate` is returned; otherwise ``None``.

        *preceding_desc_parts* are prepended to any description found on
        *line* itself.
        """
        m = _AMOUNT_LINE_RE.match(line)
        if m is None:
            return None

        amount = _parse_amount_decimal(m.group("amount"))
        if amount is None:
            return None

        # Build full description from preceding parts + inline desc
        desc_on_line = m.group("desc").strip()
        all_parts = list(preceding_desc_parts or [])
        if desc_on_line:
            all_parts.append(desc_on_line)
        description = " ".join(p for p in all_parts if p).strip()

        # Skip balance summary lines even when they contain an amount
        if _SKIP_LINE_RE.match(description):
            logger.debug("BarclaysPDFParser: skipping balance description: %r", description)
            return None

        if not description:
            logger.debug("BarclaysPDFParser: skipping amount line with empty description")
            return None

        if date is None:
            logger.debug("BarclaysPDFParser: skipping '%s' — no date context", description)
            return None

        direction = (m.group("direction") or "").upper()
        if direction == "DR":
            txn_type = "expense"
        elif direction == "CR":
            txn_type = "income"
        else:
            # No explicit direction: infer from sign or default to expense
            txn_type = "income" if amount > 0 else "expense"

        category = _categorizer.categorize(description)

        return TransactionCreate(
            date=date,
            description=description,
            amount=abs(amount),
            type=txn_type,
            source=self.source,
            category=category,
        )
