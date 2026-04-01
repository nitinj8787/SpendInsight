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

    # Barclays text-based parser (state machine on raw text)
    from app.services.pdf import BarclaysPDFParser
    parser = BarclaysPDFParser()
    transactions = parser.parse(pdf_bytes)

    # AI-powered parser (requires OPENAI_API_KEY or api_key kwarg)
    from app.services.pdf import AIPDFParser
    parser = AIPDFParser(api_key="sk-...")
    transactions = parser.parse(pdf_bytes)

    # Hybrid: structured + AI fallback with confidence scoring
    from app.services.pdf import HybridPDFParser, BarclaysPDFParser, AIPDFParser
    hybrid = HybridPDFParser(
        primary=BarclaysPDFParser(),
        ai_parser=AIPDFParser(api_key="sk-..."),
        confidence_threshold=0.7,
    )
    transactions = hybrid.parse(pdf_bytes)

    # Post-process a list of parsed transactions
    from app.services.pdf import TransactionPostProcessor
    processor = TransactionPostProcessor()
    cleaned = processor.process(transactions)
"""

from app.services.pdf.base import BasePDFParser
from app.services.pdf.factory import ParserFactory, parse_pdf
from app.services.pdf.parsers.ai_parser import AIPDFParser
from app.services.pdf.parsers.amex import AmexParser
from app.services.pdf.parsers.barclays import BarclaysParser
from app.services.pdf.parsers.barclays_text import BarclaysPDFParser
from app.services.pdf.parsers.fallback import FallbackAIParser
from app.services.pdf.parsers.generic import GenericParser
from app.services.pdf.parsers.hybrid import HybridPDFParser
from app.services.pdf.parsers.monzo import MonzoParser
from app.services.pdf.parsers.wise import WiseParser
from app.services.pdf.postprocessor import TransactionPostProcessor

__all__ = [
    "parse_pdf",
    "BasePDFParser",
    "ParserFactory",
    "GenericParser",
    "BarclaysParser",
    "BarclaysPDFParser",
    "AmexParser",
    "MonzoParser",
    "WiseParser",
    "FallbackAIParser",
    "AIPDFParser",
    "HybridPDFParser",
    "TransactionPostProcessor",
]
