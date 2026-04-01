"""Unit tests for the PDF parsing engine (strategy pattern + factory)."""

from __future__ import annotations

import datetime
import io
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf import (
    AmexParser,
    BarclaysParser,
    BasePDFParser,
    FallbackAIParser,
    GenericParser,
    MonzoParser,
    ParserFactory,
    WiseParser,
    parse_pdf,
)
from app.services.pdf.parsers.fallback import _parse_date_str


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _mock_pdf_factory(tables_per_page: list[list[list[list]]]):
    """Return a pdfplumber mock with the given table structure."""
    pages = []
    for tables in tables_per_page:
        page = MagicMock()
        page.extract_tables.return_value = tables
        page.extract_text.return_value = ""
        pages.append(page)

    mock_pdf = MagicMock()
    mock_pdf.pages = pages
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


def _mock_pdf_text(text: str):
    """Return a pdfplumber mock that serves raw *text* on a single page."""
    page = MagicMock()
    page.extract_tables.return_value = []
    page.extract_text.return_value = text

    mock_pdf = MagicMock()
    mock_pdf.pages = [page]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


# ---------------------------------------------------------------------------
# BasePDFParser — abstract interface enforcement
# ---------------------------------------------------------------------------


def test_base_parser_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BasePDFParser()  # type: ignore[abstract]


def test_custom_subclass_must_implement_can_parse_and_parse():
    class Incomplete(BasePDFParser):
        source = "test"

        def can_parse(self, text: str) -> bool:
            return True

    with pytest.raises(TypeError):
        Incomplete()  # parse() not implemented


# ---------------------------------------------------------------------------
# GenericParser
# ---------------------------------------------------------------------------


def test_generic_parser_can_parse_returns_true_without_patterns():
    """GenericParser with no IDENTIFIER_PATTERNS acts as a catch-all."""
    parser = GenericParser()
    assert parser.can_parse("Any text at all") is True


def test_generic_parser_parse_extracts_transactions():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Tesco", "12.50"],
    ]
    parser = GenericParser()
    with patch("pdfplumber.open", return_value=_mock_pdf_factory([[table]])):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].description == "Tesco"
    assert txns[0].amount == Decimal("12.50")
    assert txns[0].source == "pdf"


def test_generic_parser_source_label_stays_pdf():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Netflix", "-12.99"],
    ]
    parser = GenericParser()
    with patch("pdfplumber.open", return_value=_mock_pdf_factory([[table]])):
        txns = parser.parse(b"fake pdf")
    assert txns[0].source == "pdf"


# ---------------------------------------------------------------------------
# Bank-specific parsers — can_parse detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "parser_cls, text, expected",
    [
        (BarclaysParser, "Barclays Bank PLC — Account Statement", True),
        (BarclaysParser, "HSBC Premier Account", False),
        # Structural detection: "Money out" + "Money in" header (Barclays-specific)
        # This covers PDFs where the bank name appears only as a logo (not readable text).
        (BarclaysParser, "Date Description Money out Money in Balance", True),
        # A Barclays PDF that contains "Monzo" in a transaction ref but NOT the
        # word "Barclays" must still be identified as Barclays (not Monzo).
        (BarclaysParser, "Date Description Money out Money in Balance\n06 Oct Direct Debit to Sky Digital 38.00\nRef: Nitin Monzo", True),
        (AmexParser, "American Express — Platinum Card Statement", True),
        (AmexParser, "AMEX Card Services", True),
        (AmexParser, "Lloyds Current Account", False),
        (MonzoParser, "Monzo Bank Limited", True),
        (MonzoParser, "Nationwide Building Society", False),
        # "Monzo" appearing only in a transaction reference should NOT match
        # MonzoParser (BarclaysParser would claim the PDF first via header match).
        (MonzoParser, "Ref: Nitin Monzo", True),  # MonzoParser alone still matches
        (WiseParser, "Wise (formerly TransferWise)", True),
        (WiseParser, "TransferWise Ltd", True),
        (WiseParser, "Starling Bank", False),
    ],
)
def test_bank_parser_can_parse(parser_cls, text, expected):
    parser = parser_cls()
    assert parser.can_parse(text) is expected


# ---------------------------------------------------------------------------
# Bank-specific parsers — source label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "parser_cls, expected_source",
    [
        (BarclaysParser, "barclays"),
        (AmexParser, "amex"),
        (MonzoParser, "monzo"),
        (WiseParser, "wise"),
    ],
)
def test_bank_parser_sets_correct_source(parser_cls, expected_source):
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Salary", "2000.00"],
    ]
    parser = parser_cls()
    with patch("pdfplumber.open", return_value=_mock_pdf_factory([[table]])):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].source == expected_source


# ---------------------------------------------------------------------------
# ParserFactory — registration and detection
# ---------------------------------------------------------------------------


def test_factory_detects_barclays():
    factory = ParserFactory()
    with patch.object(factory, "_extract_text", return_value="Barclays Bank PLC"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, BarclaysParser)


def test_factory_detects_barclays_by_column_headers():
    """Barclays PDFs without the word 'Barclays' are detected by column headers."""
    factory = ParserFactory()
    text = "Date Description Money out Money in Balance"
    with patch.object(factory, "_extract_text", return_value=text):
        parser = factory.detect(b"fake")
    assert isinstance(parser, BarclaysParser)


def test_factory_detects_barclays_not_monzo_when_ref_contains_monzo():
    """BarclaysParser must win over MonzoParser even when a transaction ref
    contains the word 'Monzo' — as seen in 'Ref: Nitin Monzo'."""
    factory = ParserFactory()
    # Simulate the extracted text from a real Barclays PDF: has "Money out"/
    # "Money in" column headers AND a "Ref: Nitin Monzo" transaction reference.
    text = (
        "Your transactions\n"
        "Date Description Money out Money in Balance\n"
        "04 Oct Start balance 9,629.70\n"
        "13 Oct Bill Payment to Nitin Jain 400.00\n"
        "Ref: Nitin Monzo\n"
    )
    with patch.object(factory, "_extract_text", return_value=text):
        parser = factory.detect(b"fake")
    assert isinstance(parser, BarclaysParser)
    assert parser.source == "barclays"


def test_factory_detects_amex():
    factory = ParserFactory()
    with patch.object(factory, "_extract_text", return_value="American Express Card"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, AmexParser)


def test_factory_detects_monzo():
    factory = ParserFactory()
    with patch.object(factory, "_extract_text", return_value="Monzo Statement"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, MonzoParser)


def test_factory_detects_wise():
    factory = ParserFactory()
    with patch.object(factory, "_extract_text", return_value="Wise Borderless Account"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, WiseParser)


def test_factory_falls_back_to_generic_for_unknown_bank():
    factory = ParserFactory()
    with patch.object(factory, "_extract_text", return_value="HSBC Statement"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, GenericParser)


def test_factory_register_custom_parser():
    class TestBankParser(GenericParser):
        source = "testbank"

        import re as _re
        IDENTIFIER_PATTERNS = [_re.compile(r"TestBank")]

    factory = ParserFactory()
    factory.register(TestBankParser(), priority=0)
    with patch.object(factory, "_extract_text", return_value="TestBank PLC Statement"):
        parser = factory.detect(b"fake")
    assert isinstance(parser, TestBankParser)


def test_factory_parse_uses_detected_parser():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Amazon", "25.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf_factory([[table]])):
        factory = ParserFactory()
        with patch.object(factory, "_extract_text", return_value="Barclays Bank PLC"):
            txns = factory.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].source == "barclays"


def test_factory_falls_back_to_fallback_parser_on_empty_result():
    """When the primary parser returns no transactions, FallbackAIParser is tried."""
    text = (
        "15/03/2024  Tesco Express  12.50\n"
        "16/03/2024  Netflix        9.99\n"
    )
    factory = ParserFactory()

    with patch.object(factory, "detect", return_value=GenericParser()):
        with patch.object(GenericParser, "parse", return_value=[]):
            mock = _mock_pdf_text(text)
            with patch("pdfplumber.open", return_value=mock):
                txns = factory.parse(b"fake pdf")

    assert len(txns) == 2


def test_factory_propagates_value_error_from_primary_parser():
    """Data parsing errors (bad rows) should propagate, not be swallowed."""
    factory = ParserFactory()

    with patch.object(factory, "detect", return_value=GenericParser()):
        with patch.object(GenericParser, "parse", side_effect=ValueError("bad row data")):
            with pytest.raises(ValueError, match="bad row data"):
                factory.parse(b"fake pdf")


# ---------------------------------------------------------------------------
# Module-level parse_pdf convenience function
# ---------------------------------------------------------------------------


def test_parse_pdf_function_delegates_to_factory():
    table = [
        ["date", "description", "amount"],
        ["2024-06-01", "Starbucks", "4.50"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf_factory([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].description == "Starbucks"


# ---------------------------------------------------------------------------
# FallbackAIParser — state machine
# ---------------------------------------------------------------------------


def _make_fallback_pdf(text: str):
    page = MagicMock()
    page.extract_tables.return_value = []
    page.extract_text.return_value = text
    mock_pdf = MagicMock()
    mock_pdf.pages = [page]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


def test_fallback_parses_simple_entries():
    text = (
        "15/03/2024  Tesco Express  12.50\n"
        "16/03/2024  Netflix        9.99\n"
    )
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 2
    assert txns[0].date == datetime.date(2024, 3, 15)
    assert txns[0].description == "Tesco Express"
    assert txns[0].amount == Decimal("12.50")
    assert txns[1].description == "Netflix"
    assert txns[1].amount == Decimal("9.99")


def test_fallback_handles_multiline_description():
    text = (
        "15/03/2024  AMAZON.CO.UK\n"
        "            REF: 123456789\n"
        "            25.99\n"
        "16/03/2024  Starbucks  3.80\n"
    )
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 2
    amazon = next((t for t in txns if "amazon" in t.description.lower()), None)
    assert amazon is not None
    assert amazon.amount == Decimal("25.99")


def test_fallback_negative_amount_becomes_expense():
    text = "2024-03-15  Netflix  -12.99\n"
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].type == "expense"
    assert txns[0].amount == Decimal("12.99")


def test_fallback_positive_amount_defaults_to_income():
    text = "2024-03-15  Salary  2000.00\n"
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert txns[0].type == "income"


def test_fallback_skips_header_noise():
    text = (
        "Date  Description  Amount\n"
        "15/03/2024  Tesco  12.50\n"
    )
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].description == "Tesco"


def test_fallback_skips_balance_rows():
    text = (
        "Opening balance  9629.70\n"
        "15/03/2024  Netflix  12.99\n"
        "Closing balance  9616.71\n"
    )
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].description == "Netflix"


def test_fallback_returns_empty_for_blank_text():
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf("")):
        txns = parser.parse(b"fake pdf")
    assert txns == []


def test_fallback_ai_classify_fn_is_called():
    """When ai_classify_fn is set it should be used for categorisation."""
    called_with: list[str] = []

    def fake_ai(desc: str) -> str:
        called_with.append(desc)
        return "custom_category"

    text = "2024-03-15  SomeUnknownMerchant  50.00\n"
    parser = FallbackAIParser()
    parser.ai_classify_fn = fake_ai
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].category == "custom_category"
    assert "SomeUnknownMerchant" in called_with


def test_fallback_ai_classify_fn_exception_falls_back_to_rules():
    """If ai_classify_fn raises, rule-based categorizer should be used."""

    def bad_ai(desc: str) -> str:
        raise RuntimeError("AI unavailable")

    text = "2024-03-15  Tesco Express  12.50\n"
    parser = FallbackAIParser()
    parser.ai_classify_fn = bad_ai
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].category == "food"  # rule-based categorizer should match Tesco


def test_fallback_iso_date_format():
    text = "2024-01-20  Uber Eats  18.45\n"
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")
    assert len(txns) == 1
    assert txns[0].date == datetime.date(2024, 1, 20)


def test_fallback_dd_mmm_date_without_year():
    text = "14 Oct  British Gas  45.00\n"
    parser = FallbackAIParser()
    with patch("pdfplumber.open", return_value=_make_fallback_pdf(text)):
        txns = parser.parse(b"fake pdf")
    assert len(txns) == 1
    assert txns[0].date.month == 10
    assert txns[0].date.day == 14
    assert txns[0].date.year == datetime.date.today().year


# ---------------------------------------------------------------------------
# _parse_date_str helper
# ---------------------------------------------------------------------------


def test_parse_date_str_iso():
    assert _parse_date_str("2024-03-15") == datetime.date(2024, 3, 15)


def test_parse_date_str_uk_slash():
    assert _parse_date_str("15/03/2024") == datetime.date(2024, 3, 15)


def test_parse_date_str_dd_mmm_yyyy():
    assert _parse_date_str("15 Mar 2024") == datetime.date(2024, 3, 15)


def test_parse_date_str_dd_mmm_no_year():
    result = _parse_date_str("04 Oct")
    assert result is not None
    assert result.month == 10
    assert result.day == 4


def test_parse_date_str_invalid_returns_none():
    assert _parse_date_str("not-a-date") is None


# ---------------------------------------------------------------------------
# Extensibility: registering a new bank parser at runtime
# ---------------------------------------------------------------------------


def test_register_new_parser_takes_precedence():
    import re

    class MyNewBankParser(GenericParser):
        source = "mynewbank"
        IDENTIFIER_PATTERNS = [re.compile(r"MyNewBank", re.IGNORECASE)]

    factory = ParserFactory()
    factory.register(MyNewBankParser(), priority=0)

    with patch.object(factory, "_extract_text", return_value="MyNewBank Statement"):
        parser = factory.detect(b"fake")

    assert isinstance(parser, MyNewBankParser)
    assert parser.source == "mynewbank"
