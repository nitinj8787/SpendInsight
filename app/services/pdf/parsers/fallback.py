"""Fallback AI-based PDF parser using regex and a state machine.

This parser is invoked when no bank-specific parser claims the document and
the generic table-extraction strategy fails to find any transactions.  It
operates directly on the raw text extracted from the PDF pages, using a
state-machine approach to handle:

* Multi-line transaction descriptions
* Missing dates (carried forward from the previous transaction)
* Transactions where the amount appears on a continuation line
* Noisy PDF text (page headers, footers, running balances)

The class also exposes an :attr:`ai_classify_fn` hook.  When set to a
callable, it is invoked for transactions whose description cannot be
categorised by the rule-based categorizer, allowing an external LLM or ML
model to provide a category without changing the parsing logic.
"""

from __future__ import annotations

import io
import logging
import re
from decimal import Decimal, InvalidOperation
from enum import Enum, auto
from typing import Callable

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.categorizer import TransactionCategorizer
from app.services.pdf.base import BasePDFParser

logger = logging.getLogger(__name__)

_categorizer = TransactionCategorizer()

# ---------------------------------------------------------------------------
# Regex patterns used by the state machine
# ---------------------------------------------------------------------------

# Recognise a date at the start of a line (or standalone on its own line).
# Groups: date_iso | date_slash | date_dash | date_longmonth | date_shortmonth
_LINE_DATE_RE = re.compile(
    r"^(?P<date>"
    r"\d{4}-\d{2}-\d{2}"                       # YYYY-MM-DD
    r"|\d{1,2}/\d{2}/\d{4}"                    # DD/MM/YYYY
    r"|\d{1,2}/\d{2}/\d{2}"                    # DD/MM/YY
    r"|\d{1,2}-\d{2}-\d{4}"                    # DD-MM-YYYY
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"        # DD Month YYYY
    r"|\d{1,2}\s+[A-Za-z]{3}"                  # DD Mon  (no year)
    r")"
    r"(?:\s+(?P<rest>.+))?$",
    re.IGNORECASE,
)

# Amount pattern: optional currency prefix, optional sign, digits
_AMOUNT_RE = re.compile(
    r"(?:^|(?<=\s))"
    r"(?P<amount>[£$€]?\s*[-+]?\s*[\d,]{1,12}(?:\.\d{1,2})?)"
    r"(?:\s+(?:DR|CR|debit|credit))?"
    r"(?:\s|$)",
    re.IGNORECASE,
)

# Trailing amount: an amount appearing at the very end of a description line.
# Requires either a decimal part (25.99, 1,234.56) or a short integer ≤6
# digits (e.g. 2000, 500) so that long reference numbers (123456789) are
# not mistaken for monetary amounts.
_TRAILING_AMOUNT_RE = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<amount>[£$€]?\s*[-+]?\s*"
    r"(?:"
    r"[\d,]+\.\d{1,2}"      # has decimal places: 25.99, 1,234.56, £9,629.70
    r"|\d{1,6}"              # short plain integer (≤6 digits): 2000, 500
    r")"
    r")"
    r"\s*(?:DR|CR|debit|credit)?\s*$",
    re.IGNORECASE,
)

# Lines that look like column headers or page noise — skip them
_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"date|description|amount|balance|details|money\s+(?:in|out)|"
    r"debit|credit|reference|transaction|page\s+\d+|statement\s+date|"
    r"sort\s+code|account\s+(?:number|name)"
    r")\s*$",
    re.IGNORECASE,
)

# Balance-row noise (running balance figures to discard)
_BALANCE_NOISE_RE = re.compile(
    r"\b(start|opening|closing|end|brought\s+forward|carried\s+forward)\s+balance\b",
    re.IGNORECASE,
)

# Debit/Credit suffix patterns used to infer transaction type
_DEBIT_SUFFIX_RE = re.compile(r"\bDR\b|\bdebit\b", re.IGNORECASE)
_CREDIT_SUFFIX_RE = re.compile(r"\bCR\b|\bcredit\b", re.IGNORECASE)

# Standalone amount line: the entire (stripped) text is a monetary amount with
# optional currency prefix, optional sign, and at least one decimal digit.
# Accepts either decimal amounts (25.99) or short plain integers (≤6 digits).
_STANDALONE_AMOUNT_RE = re.compile(
    r"^[£$€]?\s*[-+]?\s*"
    r"(?:[\d,]+\.\d{1,2}|\d{1,6})"
    r"\s*(?:DR|CR|debit|credit)?\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Date parsing (mirrors generic parser)
# ---------------------------------------------------------------------------

_PARSE_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%d %b",
    "%d %B",
]


def _parse_date_str(value: str) -> "datetime.date | None":
    import datetime

    value = value.strip()
    for fmt in _PARSE_DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            if parsed.year == 1900:
                today = datetime.date.today()
                parsed = parsed.replace(year=today.year)
                if parsed.date() > today + datetime.timedelta(days=31):
                    parsed = parsed.replace(year=parsed.year - 1)
            return parsed.date()
        except ValueError:
            continue
    return None


def _parse_amount_str(value: str) -> Decimal | None:
    cleaned = re.sub(r"[£$€\s]", "", value).replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# State machine states
# ---------------------------------------------------------------------------


class _State(Enum):
    SEEKING_ENTRY = auto()
    BUILDING_ENTRY = auto()


# ---------------------------------------------------------------------------
# Internal pending-entry accumulator
# ---------------------------------------------------------------------------


class _PendingEntry:
    """Holds partially-parsed transaction fields while the state machine runs."""

    __slots__ = ("date", "description_parts", "amount_str", "type_hint")

    def __init__(self, date: "datetime.date", description_parts: list[str]) -> None:
        self.date = date
        self.description_parts: list[str] = description_parts
        self.amount_str: str | None = None
        self.type_hint: str | None = None  # "expense" | "income" | None

    @property
    def description(self) -> str:
        return " ".join(p for p in self.description_parts if p)


# ---------------------------------------------------------------------------
# FallbackAIParser
# ---------------------------------------------------------------------------


class FallbackAIParser(BasePDFParser):
    """Text-extraction parser driven by a regex + state machine.

    This parser is the last resort when no bank-specific or generic table
    parser succeeds.  It extracts raw text from every PDF page and walks
    through it line by line using a two-state machine:

    * **SEEKING_ENTRY** — scanning for a line that starts with a recognised
      date pattern.
    * **BUILDING_ENTRY** — accumulating description and amount tokens until
      the next date-starting line is found (or the text ends), at which point
      the buffered entry is emitted.

    The :attr:`ai_classify_fn` hook allows callers to plug in an external
    model (e.g. an LLM) for category inference::

        def my_llm_classify(description: str) -> str:
            ...  # call OpenAI / local model
            return "food"

        parser = FallbackAIParser()
        parser.ai_classify_fn = my_llm_classify

    When no hook is supplied the built-in :class:`~app.services.categorizer.TransactionCategorizer`
    is used.
    """

    source = "pdf"

    #: Optional external callable ``(description: str) -> str`` for category
    #: inference.  When set it is tried *before* the rule-based categorizer.
    ai_classify_fn: Callable[[str], str] | None = None

    def can_parse(self, text: str) -> bool:
        """Always returns ``True`` — this parser is the universal fallback."""
        return True

    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Extract transactions from raw PDF text using a state machine.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        list[TransactionCreate]
            Parsed transactions.  Returns an empty list if no transaction
            patterns are found.
        """
        logger.debug("FallbackAIParser.parse() invoked")
        lines = self._extract_lines(content)
        transactions = self._run_state_machine(lines)
        logger.info("FallbackAIParser extracted %d transaction(s)", len(transactions))
        return transactions

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_lines(self, content: bytes) -> list[str]:
        """Return all non-blank text lines from the PDF."""
        lines: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for raw_line in text.splitlines():
                    line = raw_line.strip()
                    if line:
                        lines.append(line)
        return lines

    def _run_state_machine(self, lines: list[str]) -> list[TransactionCreate]:
        """Walk *lines* through the two-state machine and return transactions."""
        transactions: list[TransactionCreate] = []
        state = _State.SEEKING_ENTRY
        pending: _PendingEntry | None = None
        last_date = None

        for line in lines:
            if _NOISE_RE.match(line) or _BALANCE_NOISE_RE.search(line):
                continue

            date_match = _LINE_DATE_RE.match(line)

            if date_match:
                # We found a new date-prefixed line → flush any pending entry
                if pending is not None:
                    txn = self._try_emit(pending, last_date)
                    if txn is not None:
                        transactions.append(txn)
                        last_date = txn.date

                parsed_date = _parse_date_str(date_match.group("date"))
                if parsed_date is None:
                    # Couldn't parse the date — treat line as description noise
                    if pending is not None and state == _State.BUILDING_ENTRY:
                        pending.description_parts.append(line)
                    continue

                rest = (date_match.group("rest") or "").strip()

                # Try to split rest into description + trailing amount
                desc_part, amount_str, type_hint = self._split_desc_amount(rest)

                pending = _PendingEntry(
                    date=parsed_date,
                    description_parts=[desc_part] if desc_part else [],
                )
                if amount_str:
                    pending.amount_str = amount_str
                    pending.type_hint = type_hint
                    state = _State.SEEKING_ENTRY
                else:
                    state = _State.BUILDING_ENTRY

            elif state == _State.BUILDING_ENTRY and pending is not None:
                # Continuation line: may be more description or the amount
                desc_part, amount_str, type_hint = self._split_desc_amount(line)

                if amount_str and not desc_part:
                    # Pure amount line → close this entry
                    pending.amount_str = amount_str
                    pending.type_hint = type_hint
                    txn = self._try_emit(pending, last_date)
                    if txn is not None:
                        transactions.append(txn)
                        last_date = txn.date
                    pending = None
                    state = _State.SEEKING_ENTRY
                elif amount_str:
                    # Description and amount on same continuation line
                    pending.description_parts.append(desc_part)
                    pending.amount_str = amount_str
                    pending.type_hint = type_hint
                    txn = self._try_emit(pending, last_date)
                    if txn is not None:
                        transactions.append(txn)
                        last_date = txn.date
                    pending = None
                    state = _State.SEEKING_ENTRY
                else:
                    # Pure description continuation
                    pending.description_parts.append(line)

        # Flush any remaining pending entry
        if pending is not None:
            txn = self._try_emit(pending, last_date)
            if txn is not None:
                transactions.append(txn)

        return transactions

    # ------------------------------------------------------------------

    def _split_desc_amount(
        self, text: str
    ) -> tuple[str, str | None, str | None]:
        """Try to split *text* into (description, amount_str, type_hint).

        Returns ``(text, None, None)`` when no amount pattern is found.
        """
        if not text:
            return ("", None, None)

        m = _TRAILING_AMOUNT_RE.match(text)
        if m:
            desc = m.group("desc").strip()
            amount_str = m.group("amount").strip()
            # Determine debit/credit hint from the full text suffix
            type_hint: str | None = None
            if _DEBIT_SUFFIX_RE.search(text):
                type_hint = "expense"
            elif _CREDIT_SUFFIX_RE.search(text):
                type_hint = "income"
            return (desc, amount_str, type_hint)

        # Check if the entire line is just an amount (decimal or short integer)
        stripped = text.strip()
        if _STANDALONE_AMOUNT_RE.match(stripped):
            type_hint = None
            if _DEBIT_SUFFIX_RE.search(text):
                type_hint = "expense"
            elif _CREDIT_SUFFIX_RE.search(text):
                type_hint = "income"
            return ("", stripped, type_hint)

        return (text, None, None)

    def _try_emit(
        self,
        pending: _PendingEntry,
        last_date: "datetime.date | None",
    ) -> TransactionCreate | None:
        """Convert a completed *pending* entry into a :class:`TransactionCreate`.

        Returns ``None`` (and logs a warning) if the entry is missing a
        required field.
        """
        import datetime

        description = pending.description
        if not description:
            logger.debug("FallbackAIParser: skipping entry with empty description")
            return None

        if pending.amount_str is None:
            logger.debug(
                "FallbackAIParser: skipping '%s' — no amount found", description
            )
            return None

        amount = _parse_amount_str(pending.amount_str)
        if amount is None:
            logger.warning(
                "FallbackAIParser: cannot parse amount %r for '%s'",
                pending.amount_str,
                description,
            )
            return None

        date = pending.date or last_date
        if date is None:
            logger.debug("FallbackAIParser: skipping '%s' — no date", description)
            return None

        # Determine transaction type
        if pending.type_hint:
            txn_type = pending.type_hint
            amount = abs(amount)
        elif amount < 0:
            txn_type = "expense"
            amount = abs(amount)
        else:
            txn_type = "income"

        # Category: try AI hook first, fall back to rule-based
        category = "uncategorized"
        if self.ai_classify_fn is not None:
            try:
                category = self.ai_classify_fn(description)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_classify_fn raised %r; falling back to rules", exc)
                category = _categorizer.categorize(description)
        else:
            category = _categorizer.categorize(description)

        return TransactionCreate(
            date=date,
            description=description,
            amount=amount,
            type=txn_type,
            source=self.source,
            category=category,
        )
