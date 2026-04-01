"""Barclays-specific PDF parser."""

from __future__ import annotations

import re

from app.services.pdf.parsers.generic import GenericParser


class BarclaysParser(GenericParser):
    """Parser for Barclays bank statement PDFs.

    Barclays statements typically include the word "Barclays" in the header
    and use columns such as "Date", "Memo" (or "Description"), "Money out",
    "Money in", and "Balance".

    Dates appear in ``DD/MM/YYYY`` or ``DD MMM YYYY`` format.

    Detection notes
    ~~~~~~~~~~~~~~~
    PDF text extraction via pdfplumber may not include "Barclays" when the
    bank name appears only as a logo/image (which pdfplumber skips).  A
    second pattern therefore looks for the Barclays-specific column-header
    pair ``"Money out" … "Money in"`` which always appears as extractable
    text in the table header row.  This ensures the parser claims the
    document *before* less-specific parsers (e.g. MonzoParser, which would
    otherwise false-match on a transaction reference such as
    ``"Ref: Nitin Monzo"``).
    """

    source = "barclays"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        # Direct bank-name match (present when pdfplumber can read the header).
        re.compile(r"\bBarclays\b", re.IGNORECASE),
        # Structural match on Barclays-specific column header terminology.
        # "Money out" and "Money in" appear on the same header line in the
        # Barclays table layout and are unique to Barclays printed statements.
        re.compile(r"\bMoney\s+out\b.*?\bMoney\s+in\b", re.IGNORECASE),
    ]
