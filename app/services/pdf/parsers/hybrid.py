"""Hybrid PDF parser that combines a structured parser with AI fallback.

The :class:`HybridPDFParser` wraps any :class:`~app.services.pdf.base.BasePDFParser`
(typically a bank-specific one) with an :class:`~app.services.pdf.parsers.ai_parser.AIPDFParser`.

Flow
~~~~
1. Run the *primary* structured parser.
2. Count the lines in the raw PDF text that *look like* transactions
   (lines containing an amount pattern after a date).
3. Compute **confidence** = ``len(parsed) / max(1, estimated_total)``.
4. If ``confidence >= confidence_threshold`` → return the structured result.
5. Otherwise → run the AI parser and return whichever result has more
   transactions.

Confidence scoring
~~~~~~~~~~~~~~~~~~
The confidence metric is a heuristic: the number of successfully parsed
transactions divided by the number of candidate amount lines detected in the
raw text.  A value near 1.0 means the structured parser captured nearly
everything; a value close to 0 suggests it missed most transactions.

Usage::

    from app.services.pdf.parsers.hybrid import HybridPDFParser
    from app.services.pdf.parsers.barclays_text import BarclaysPDFParser
    from app.services.pdf.parsers.ai_parser import AIPDFParser

    hybrid = HybridPDFParser(
        primary=BarclaysPDFParser(),
        ai_parser=AIPDFParser(api_key="sk-..."),
        confidence_threshold=0.7,
    )
    transactions = hybrid.parse(pdf_bytes)
    print(f"Confidence was: {hybrid.last_confidence:.0%}")
"""

from __future__ import annotations

import io
import logging
import re

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.pdf.base import BasePDFParser
from app.services.pdf.parsers.ai_parser import AIPDFParser

logger = logging.getLogger(__name__)

# Heuristic: a line containing an amount pattern suggests a transaction row.
# Accepts one or two decimal places (e.g. "10.50" or "10.5").
_CANDIDATE_LINE_RE = re.compile(
    r"[\d,]+\.\d{1,2}",
)


class HybridPDFParser(BasePDFParser):
    """Combines a structured parser with an AI fallback for best-effort parsing.

    Parameters
    ----------
    primary:
        A bank-specific (or generic) structured parser to try first.
    ai_parser:
        An :class:`~app.services.pdf.parsers.ai_parser.AIPDFParser` instance
        to use when the structured parser's confidence is too low.
    confidence_threshold:
        Minimum confidence ratio (0–1) required to accept the structured
        result.  Defaults to ``0.6`` (60%).
    """

    source = "pdf"

    def __init__(
        self,
        primary: BasePDFParser,
        ai_parser: AIPDFParser | None = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._primary = primary
        self._ai = ai_parser or AIPDFParser()
        self._threshold = confidence_threshold
        #: Confidence score from the most recent :meth:`parse` call.
        self.last_confidence: float = 0.0
        #: Name of the parser strategy used in the most recent :meth:`parse` call.
        self.last_strategy: str = "none"

    # ------------------------------------------------------------------
    # BasePDFParser interface
    # ------------------------------------------------------------------

    def can_parse(self, text: str) -> bool:
        """Delegates to the primary parser's :meth:`can_parse`."""
        return self._primary.can_parse(text)

    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Parse *content*, choosing between structured and AI strategies.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        list[TransactionCreate]
            The best available list of transactions.
        """
        logger.debug(
            "HybridPDFParser.parse(): primary=%s, threshold=%.2f",
            type(self._primary).__name__,
            self._threshold,
        )

        candidate_count = self._count_candidates(content)
        logger.debug("HybridPDFParser: estimated candidate lines = %d", candidate_count)

        # --- attempt structured parsing ---
        try:
            structured = self._primary.parse(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HybridPDFParser: primary parser raised %s; confidence = 0", exc)
            structured = []

        confidence = len(structured) / max(1, candidate_count)
        self.last_confidence = confidence
        logger.info(
            "HybridPDFParser: structured=%d txns, candidates=%d, confidence=%.2f",
            len(structured),
            candidate_count,
            confidence,
        )

        if confidence >= self._threshold:
            logger.info("HybridPDFParser: confidence OK — using structured result")
            self.last_strategy = type(self._primary).__name__
            return structured

        # --- fall back to AI parser ---
        logger.info(
            "HybridPDFParser: confidence %.2f < %.2f — invoking AI parser",
            confidence,
            self._threshold,
        )
        try:
            ai_result = self._ai.parse(content)
        except Exception as exc:  # noqa: BLE001
            logger.error("HybridPDFParser: AI parser raised %s; returning structured result", exc)
            self.last_strategy = type(self._primary).__name__ + " (AI failed)"
            return structured

        # Return whichever result has more transactions
        if len(ai_result) >= len(structured):
            logger.info(
                "HybridPDFParser: using AI result (%d txns vs %d)",
                len(ai_result),
                len(structured),
            )
            self.last_strategy = "AIPDFParser"
            return ai_result

        logger.info(
            "HybridPDFParser: AI result smaller (%d) than structured (%d); using structured",
            len(ai_result),
            len(structured),
        )
        self.last_strategy = type(self._primary).__name__
        return structured

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _count_candidates(self, content: bytes) -> int:
        """Count lines in the raw PDF text that look like transaction rows."""
        count = 0
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not isinstance(text, str):
                        continue
                    for line in text.splitlines():
                        if _CANDIDATE_LINE_RE.search(line):
                            count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("HybridPDFParser: candidate counting failed: %s", exc)
        return count
