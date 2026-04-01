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
    """

    source = "barclays"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bBarclays\b", re.IGNORECASE),
    ]
