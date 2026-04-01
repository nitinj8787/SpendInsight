"""Wise (formerly TransferWise) specific PDF parser."""

from __future__ import annotations

import re

from app.services.pdf.parsers.generic import GenericParser


class WiseParser(GenericParser):
    """Parser for Wise (formerly TransferWise) statement PDFs.

    Wise statements are identified by the words "Wise" or "TransferWise".
    Dates typically appear in ``YYYY-MM-DD`` ISO format.  Columns include
    "Date", "Description", and "Amount".
    """

    source = "wise"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bWise\b", re.IGNORECASE),
        re.compile(r"\bTransferWise\b", re.IGNORECASE),
    ]
