"""Backward-compatible shim for the PDF parsing engine.

All production code should import from :mod:`app.services.pdf` instead.
This module re-exports the public function and the private helpers that the
existing test suite accesses directly, so that no test changes are required.
"""

# Re-export the primary public function
from app.services.pdf.factory import parse_pdf  # noqa: F401

# Re-export private helpers used by tests/test_pdf_parser.py
from app.services.pdf.parsers.generic import (  # noqa: F401
    _classify_columns,
    _extract_row,
    _is_balance_row,
    _is_header_row,
    _parse_amount,
    _parse_date,
)

__all__ = [
    "parse_pdf",
    "_classify_columns",
    "_extract_row",
    "_is_balance_row",
    "_is_header_row",
    "_parse_amount",
    "_parse_date",
]
