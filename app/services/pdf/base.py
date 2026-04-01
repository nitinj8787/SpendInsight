"""Abstract base class for all bank-specific PDF parsers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.schemas.transaction import TransactionCreate

logger = logging.getLogger(__name__)


class BasePDFParser(ABC):
    """Abstract base for all PDF parsing strategies.

    Subclass this to add support for a new bank.  Each concrete subclass must:

    1. Set :attr:`source` to a human-readable bank identifier string.
    2. Implement :meth:`can_parse` to detect whether the raw PDF text
       originates from this bank.
    3. Implement :meth:`parse` to extract :class:`~app.schemas.transaction.TransactionCreate`
       objects from the raw PDF bytes.

    Sample subclass skeleton::

        class MyBankParser(BasePDFParser):
            source = "mybank"
            IDENTIFIER_PATTERNS = [re.compile(r"My Bank PLC", re.IGNORECASE)]

            def can_parse(self, text: str) -> bool:
                return any(p.search(text) for p in self.IDENTIFIER_PATTERNS)

            def parse(self, content: bytes) -> list[TransactionCreate]:
                ...
    """

    #: Human-readable bank name / source identifier written into every parsed
    #: transaction's ``source`` field.
    source: str = "unknown"

    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Return ``True`` if this parser can handle *text*.

        *text* is the full raw text of the PDF (all pages concatenated).
        Implementations typically search for bank-identifying strings such as
        the institution's name, IBAN prefix, or a known header pattern.
        """

    @abstractmethod
    def parse(self, content: bytes) -> list[TransactionCreate]:
        """Parse *content* (raw PDF bytes) into a list of transactions.

        Parameters
        ----------
        content:
            Raw bytes of the PDF file.

        Returns
        -------
        list[TransactionCreate]
            Parsed and normalised transactions.  Must not return ``None``;
            return an empty list if the document contains no transactions.

        Raises
        ------
        ValueError
            If the document is structurally invalid or a required field
            cannot be extracted.
        """
