"""Monzo-specific PDF parser."""

from __future__ import annotations

import re

from app.services.pdf.parsers.generic import GenericParser


class MonzoParser(GenericParser):
    """Parser for Monzo bank statement PDFs.

    Monzo statements are identified by the word "Monzo" and typically use
    ISO ``YYYY-MM-DD`` date formats.  Columns may include "Date", "Name" (or
    "Description"), "Amount", and "Category".
    """

    source = "monzo"

    IDENTIFIER_PATTERNS: list[re.Pattern] = [
        re.compile(r"\bMonzo\b", re.IGNORECASE),
    ]
