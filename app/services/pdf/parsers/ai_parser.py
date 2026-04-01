"""AI-powered PDF parser using the OpenAI Chat Completions API.

This parser sends the raw text extracted from a PDF to an OpenAI model and
asks it to return a structured JSON list of transactions.  It is used as a
high-quality fallback when rule-based parsers are unable to extract
transactions with sufficient confidence.

Key features
~~~~~~~~~~~~
* **Retry logic** — up to :attr:`max_retries` attempts with exponential
  back-off before giving up.
* **Strict JSON validation** — the raw model response is parsed and each
  item is validated against the :class:`~app.schemas.transaction.TransactionCreate`
  schema.  Items that fail validation are silently skipped.
* **Graceful degradation** — if all retries fail or the model returns
  unparseable JSON, an empty list is returned and the error is logged.

Configuration
~~~~~~~~~~~~~
Pass an ``api_key`` at construction time or set the ``OPENAI_API_KEY``
environment variable.  The model can be overridden via the ``model``
parameter (default: ``"gpt-4o-mini"``).

Usage::

    parser = AIPDFParser(api_key="sk-...", model="gpt-4o-mini")
    transactions = parser.parse(pdf_bytes)

To use a compatible alternative API (e.g. local Ollama, Azure OpenAI)::

    parser = AIPDFParser(api_key="...", base_url="http://localhost:11434/v1")
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.categorizer import TransactionCategorizer
from app.services.pdf.base import BasePDFParser

logger = logging.getLogger(__name__)

_categorizer = TransactionCategorizer()

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial data extraction assistant.
Your job is to extract bank transactions from raw PDF text.

Return ONLY a valid JSON array (no markdown, no explanation).
Each element must have exactly these fields:
  "date"        – string, format YYYY-MM-DD
  "description" – string, merchant or narrative
  "amount"      – number, always positive (absolute value)
  "type"        – string, either "income" or "expense"

Rules:
- Ignore lines like "Opening balance", "Closing balance", "Start balance".
- Ignore page headers, footers, and column headers.
- Infer type: money paid out is "expense"; money received is "income".
- If a date is missing, carry forward the last seen date.
- Consolidate multi-line descriptions into a single description string.
- If you cannot determine a date for a transaction, omit it entirely.

Output example:
[
  {"date": "2024-03-15", "description": "Tesco Superstore", "amount": 42.50, "type": "expense"},
  {"date": "2024-03-20", "description": "Salary BACS", "amount": 2500.00, "type": "income"}
]
"""

_USER_PROMPT_TEMPLATE = """\
Extract all transactions from the following bank statement text:

---
{text}
---

Return ONLY the JSON array. Do not include any other text.
"""

# ---------------------------------------------------------------------------
# AIPDFParser
# ---------------------------------------------------------------------------


class AIPDFParser(BasePDFParser):
    """LLM-powered PDF parser that uses the OpenAI Chat Completions API.

    This parser extracts raw text from the PDF with *pdfplumber* and then
    sends it to an OpenAI model for structured extraction.

    Parameters
    ----------
    api_key:
        OpenAI API key.  Falls back to the ``OPENAI_API_KEY`` environment
        variable when not provided.
    model:
        Chat model to use.  Defaults to ``"gpt-4o-mini"`` (cheap + fast).
    base_url:
        Optional base URL for compatible APIs (Azure OpenAI, Ollama, etc.).
    max_retries:
        Maximum number of API call attempts before giving up (default: 3).
    retry_delay:
        Base delay in seconds between retries; doubled on each attempt
        (exponential back-off).  Defaults to 1.0 s.
    """

    source = "pdf"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        base_url: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._base_url = base_url
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._client: "openai.OpenAI | None" = None  # lazy init

    # ------------------------------------------------------------------
    # BasePDFParser interface
    # ------------------------------------------------------------------

    def can_parse(self, text: str) -> bool:
        """Always returns ``False``.

        :class:`AIPDFParser` is never selected automatically by
        :class:`~app.services.pdf.factory.ParserFactory`.  It is used
        explicitly by :class:`~app.services.pdf.parsers.hybrid.HybridPDFParser`
        when structured parsing confidence is too low.
        """
        return False

    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Parse PDF *content* via the OpenAI API.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        list[TransactionCreate]
            Extracted and validated transactions, or an empty list if the
            API call fails or returns unparseable data.
        """
        logger.debug("AIPDFParser.parse() called (model=%s)", self._model)
        text = self._extract_text(content)
        if not text.strip():
            logger.warning("AIPDFParser: PDF yielded no text")
            return []

        raw_json = self._call_with_retries(text)
        if raw_json is None:
            logger.error("AIPDFParser: all retries exhausted; returning empty list")
            return []

        transactions = self._parse_response(raw_json)
        logger.info("AIPDFParser extracted %d transaction(s)", len(transactions))
        return transactions

    # ------------------------------------------------------------------
    # Private: text extraction
    # ------------------------------------------------------------------

    def _extract_text(self, content: bytes) -> str:
        """Return all text from the PDF as a single string."""
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Private: OpenAI API call with retry
    # ------------------------------------------------------------------

    def _get_client(self) -> "openai.OpenAI":
        """Lazily initialise the OpenAI client."""
        if self._client is None:
            try:
                import openai
            except ImportError as exc:
                raise ImportError(
                    "The 'openai' package is required for AIPDFParser. "
                    "Install it with: pip install openai"
                ) from exc
            kwargs: dict = {"api_key": self._api_key}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    def _call_api(self, text: str) -> str:
        """Make a single Chat Completions call and return the raw response text."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(text=text)},
            ],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    def _call_with_retries(self, text: str) -> str | None:
        """Call the API up to *max_retries* times, returning the response or ``None``."""
        delay = self._retry_delay
        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug("AIPDFParser: API attempt %d/%d", attempt, self._max_retries)
                return self._call_api(text)
            except Exception as exc:  # noqa: BLE001 – catch all transient errors
                logger.warning(
                    "AIPDFParser: attempt %d failed: %s", attempt, exc
                )
                if attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= 2  # exponential back-off
        return None

    # ------------------------------------------------------------------
    # Private: response validation
    # ------------------------------------------------------------------

    def _parse_response(self, raw: str) -> list[TransactionCreate]:
        """Parse and validate the raw JSON string from the model.

        Strips markdown code fences if present, parses JSON, and validates
        each item.  Invalid items are skipped with a warning.
        """
        # Strip ```json ... ``` fences that some models emit despite instructions
        cleaned = re.sub(r"^```[a-z]*\s*", "", raw.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"```\s*$", "", cleaned.strip())

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("AIPDFParser: JSON parse error: %s\nRaw: %r", exc, raw[:500])
            return []

        if not isinstance(data, list):
            logger.error("AIPDFParser: expected a JSON array, got %s", type(data).__name__)
            return []

        transactions: list[TransactionCreate] = []
        for i, item in enumerate(data):
            txn = self._validate_item(i, item)
            if txn is not None:
                transactions.append(txn)

        return transactions

    def _validate_item(
        self, index: int, item: object
    ) -> TransactionCreate | None:
        """Validate a single JSON object and return a :class:`TransactionCreate`.

        Returns ``None`` on any validation error.
        """
        import datetime

        if not isinstance(item, dict):
            logger.warning("AIPDFParser: item %d is not a dict; skipping", index)
            return None

        # --- date ---
        date_str = str(item.get("date", "")).strip()
        try:
            date = datetime.date.fromisoformat(date_str)
        except (ValueError, TypeError):
            logger.warning(
                "AIPDFParser: item %d has invalid date %r; skipping", index, date_str
            )
            return None

        # --- description ---
        description = str(item.get("description", "")).strip()
        if not description:
            logger.warning("AIPDFParser: item %d has empty description; skipping", index)
            return None

        # --- amount ---
        try:
            amount = Decimal(str(item.get("amount", "")))
            if amount < 0:
                amount = abs(amount)
        except (InvalidOperation, TypeError):
            logger.warning(
                "AIPDFParser: item %d has invalid amount %r; skipping",
                index,
                item.get("amount"),
            )
            return None

        # --- type ---
        txn_type = str(item.get("type", "")).strip().lower()
        if txn_type not in ("income", "expense"):
            # Tolerate and infer from amount
            logger.debug(
                "AIPDFParser: item %d type %r not recognised; defaulting to expense", index, txn_type
            )
            txn_type = "expense"

        category = _categorizer.categorize(description)

        return TransactionCreate(
            date=date,
            description=description,
            amount=amount,
            type=txn_type,
            source=self.source,
            category=category,
        )
