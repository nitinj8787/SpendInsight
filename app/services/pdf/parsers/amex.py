"""American Express (Amex) specific PDF parser."""

from __future__ import annotations

import re

from app.services.pdf.parsers.generic import GenericParser


class AmexParser(GenericParser):
    """Parser for American Express statement PDFs.

    Amex statements are identified by the phrase "American Express" or the
    abbreviation "AMEX".  Columns are typically "Date", "Description", and
    "Amount".  Dates can appear in multiple formats (``DD/MM/YYYY``,
    ``DD MMM YYYY``, ``MM/DD/YY``); all are handled by the generic date
    parser.
    """

    source = "amex"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        re.compile(r"American\s+Express", re.IGNORECASE),
        re.compile(r"\bAMEX\b"),
    ]
