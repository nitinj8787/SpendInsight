"""PDF parsing engine package.

Public API::

    from app.services.pdf import parse_pdf
    from app.services.pdf import ParserFactory, BasePDFParser

    # Simple one-shot usage
    transactions = parse_pdf(pdf_bytes)

    # Advanced: register a custom bank parser
    from app.services.pdf import ParserFactory
    factory = ParserFactory()
    factory.register(MyBankParser(), priority=0)
    transactions = factory.parse(pdf_bytes)
"""

from app.services.pdf.base import BasePDFParser
from app.services.pdf.factory import ParserFactory, parse_pdf
from app.services.pdf.parsers.amex import AmexParser
from app.services.pdf.parsers.barclays import BarclaysParser
from app.services.pdf.parsers.fallback import FallbackAIParser
from app.services.pdf.parsers.generic import GenericParser
from app.services.pdf.parsers.monzo import MonzoParser
from app.services.pdf.parsers.wise import WiseParser

__all__ = [
    "parse_pdf",
    "BasePDFParser",
    "ParserFactory",
    "GenericParser",
    "BarclaysParser",
    "AmexParser",
    "MonzoParser",
    "WiseParser",
    "FallbackAIParser",
]
