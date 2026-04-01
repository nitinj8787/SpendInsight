"""PDF parser factory — detects the correct strategy and routes parsing."""

from __future__ import annotations

import io
import logging

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.pdf.base import BasePDFParser
from app.services.pdf.parsers.barclays import BarclaysParser
from app.services.pdf.parsers.amex import AmexParser
from app.services.pdf.parsers.monzo import MonzoParser
from app.services.pdf.parsers.wise import WiseParser
from app.services.pdf.parsers.generic import GenericParser
from app.services.pdf.parsers.fallback import FallbackAIParser

logger = logging.getLogger(__name__)


class ParserFactory:
    """Routes a PDF document to the most appropriate parser strategy.

    On construction a default set of bank-specific parsers is registered in
    priority order, followed by the :class:`~app.services.pdf.parsers.generic.GenericParser`
    as a catch-all and :class:`~app.services.pdf.parsers.fallback.FallbackAIParser`
    as the last-resort text extractor.

    Calling :meth:`parse` will:

    1. Extract the full raw text from the PDF.
    2. Iterate over registered parsers in order and call :meth:`~BasePDFParser.can_parse`.
    3. Invoke :meth:`~BasePDFParser.parse` on the first matching parser.
    4. If that raises a :exc:`ValueError` or returns an empty list,
       fall back to :class:`~app.services.pdf.parsers.fallback.FallbackAIParser`.

    To add support for a new bank, create a :class:`~BasePDFParser` subclass
    and call :meth:`register` before the first :meth:`parse` call::

        factory = ParserFactory()
        factory.register(MyNewBankParser(), priority=0)  # highest priority
        transactions = factory.parse(pdf_bytes)
    """

    def __init__(self) -> None:
        # Ordered list of (parser, priority) tuples.  Lower priority value
        # means the parser is tried earlier.
        self._parsers: list[tuple[BasePDFParser, int]] = []
        self._fallback: FallbackAIParser = FallbackAIParser()

        # Register the built-in bank-specific parsers (highest priority = 0)
        # followed by the generic table parser as a catch-all (priority = 100).
        for parser in [BarclaysParser(), AmexParser(), MonzoParser(), WiseParser()]:
            self.register(parser, priority=0)
        self.register(GenericParser(), priority=100)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, parser: BasePDFParser, priority: int = 50) -> None:
        """Register *parser* with the given *priority*.

        Parsers with a lower *priority* value are tried before parsers with a
        higher value.  Within the same priority level, parsers are tried in
        registration order (FIFO).

        Parameters
        ----------
        parser:
            A :class:`BasePDFParser` instance to add to the registry.
        priority:
            Integer priority (default ``50``).  Built-in bank parsers use
            ``0``; the generic table parser uses ``100``.
        """
        self._parsers.append((parser, priority))
        self._parsers.sort(key=lambda t: t[1])
        logger.debug(
            "Registered parser %s at priority %d", type(parser).__name__, priority
        )

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _extract_text(self, content: bytes) -> str:
        """Return the concatenated text of all pages in *content*."""
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                parts.append(text if isinstance(text, str) else "")
        return "\n".join(parts)

    def detect(self, content: bytes) -> BasePDFParser:
        """Return the first registered parser that claims *content*.

        Falls back to :attr:`_fallback` if no parser matches.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        BasePDFParser
            The selected parser instance.
        """
        text = self._extract_text(content)
        for parser, _ in self._parsers:
            if parser.can_parse(text):
                logger.info("Detected parser: %s", type(parser).__name__)
                return parser
        logger.info("No specific parser matched; using FallbackAIParser")
        return self._fallback

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Parse *content* using the best available parser.

        The method attempts the detected parser first.  If it raises
        :exc:`ValueError` or returns an empty list, :class:`FallbackAIParser`
        is tried next.

        Parameters
        ----------
        content:
            Raw PDF bytes.

        Returns
        -------
        list[TransactionCreate]
            Parsed transactions (possibly empty).

        Raises
        ------
        ValueError
            If both the primary parser and the fallback raise errors.
        """
        parser = self.detect(content)
        logger.debug("Primary parser: %s", type(parser).__name__)

        transactions = parser.parse(content)

        if not transactions and not isinstance(parser, FallbackAIParser):
            logger.info(
                "%s returned no transactions; invoking FallbackAIParser",
                type(parser).__name__,
            )
            transactions = self._fallback.parse(content)

        logger.info("ParserFactory.parse() returning %d transaction(s)", len(transactions))
        return transactions


# ---------------------------------------------------------------------------
# Module-level singleton factory (used by parse_pdf)
# ---------------------------------------------------------------------------

_default_factory = ParserFactory()


def parse_pdf(content: bytes) -> list[TransactionCreate]:
    """Parse PDF *content* into a list of :class:`~app.schemas.transaction.TransactionCreate`.

    This is the main entry-point for the PDF parsing engine.  It delegates to
    :class:`ParserFactory`, which automatically detects the source bank and
    selects the appropriate parsing strategy, falling back to a text-based
    extractor if structured table parsing fails.

    Parameters
    ----------
    content:
        Raw bytes of the PDF file.

    Returns
    -------
    list[TransactionCreate]
        Normalised transactions with ``date``, ``description``, ``amount``,
        ``type``, ``source``, and ``category`` fields populated.

    Raises
    ------
    ValueError
        If the PDF cannot be parsed at all.

    Example
    -------
    ::

        with open("statement.pdf", "rb") as f:
            transactions = parse_pdf(f.read())

        for txn in transactions:
            print(txn.date, txn.description, txn.amount, txn.type)
    """
    return _default_factory.parse(content)
