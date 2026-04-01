"""Unit tests for the PDF parsing service."""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf_parser import (
    _classify_columns,
    _extract_row,
    _is_header_row,
    _parse_amount,
    _parse_date,
    parse_pdf,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pdf(tables_per_page: list[list[list[list]]]):
    """Return a mock pdfplumber context manager with the given table structure.

    *tables_per_page* is a list (one element per page) where each element is
    a list of tables, and each table is a list of rows (lists of cell strings).
    """
    pages = []
    for tables in tables_per_page:
        page = MagicMock()
        page.extract_tables.return_value = tables
        pages.append(page)

    mock_pdf = MagicMock()
    mock_pdf.pages = pages
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


def test_parse_date_iso_format():
    assert _parse_date("2024-03-15") == datetime.date(2024, 3, 15)


def test_parse_date_uk_slash_format():
    assert _parse_date("15/03/2024") == datetime.date(2024, 3, 15)


def test_parse_date_dd_mm_yyyy_dash():
    assert _parse_date("15-03-2024") == datetime.date(2024, 3, 15)


def test_parse_date_dd_mmm_yyyy():
    assert _parse_date("15 Mar 2024") == datetime.date(2024, 3, 15)


def test_parse_date_with_surrounding_whitespace():
    assert _parse_date("  2024-03-15  ") == datetime.date(2024, 3, 15)


def test_parse_date_invalid_returns_none():
    assert _parse_date("not-a-date") is None


def test_parse_date_empty_returns_none():
    assert _parse_date("") is None


# ---------------------------------------------------------------------------
# _parse_amount
# ---------------------------------------------------------------------------


def test_parse_amount_positive_decimal():
    assert _parse_amount("75.50") == Decimal("75.50")


def test_parse_amount_negative_decimal():
    assert _parse_amount("-75.50") == Decimal("-75.50")


def test_parse_amount_with_thousands_comma():
    assert _parse_amount("1,234.56") == Decimal("1234.56")


def test_parse_amount_gbp_symbol():
    assert _parse_amount("£75.50") == Decimal("75.50")


def test_parse_amount_usd_symbol():
    assert _parse_amount("$1,000.00") == Decimal("1000.00")


def test_parse_amount_eur_symbol():
    assert _parse_amount("€50.00") == Decimal("50.00")


def test_parse_amount_integer_value():
    assert _parse_amount("100") == Decimal("100")


def test_parse_amount_with_surrounding_whitespace():
    assert _parse_amount("  75.50  ") == Decimal("75.50")


def test_parse_amount_invalid_returns_none():
    assert _parse_amount("not-a-number") is None


def test_parse_amount_empty_returns_none():
    assert _parse_amount("") is None


# ---------------------------------------------------------------------------
# _classify_columns
# ---------------------------------------------------------------------------


def test_classify_columns_from_standard_header():
    header = ["date", "description", "amount", "type", "source", "category"]
    data = ["2024-03-15", "Grocery", "75.50", "expense", "bank", "food"]
    mapping = _classify_columns(header, data)
    assert mapping == {
        "date": 0,
        "description": 1,
        "amount": 2,
        "type": 3,
        "source": 4,
        "category": 5,
    }


def test_classify_columns_from_alias_header():
    header = ["Date", "Memo", "Value", "Account"]
    data = ["2024-03-15", "Amazon", "75.50", "barclays"]
    mapping = _classify_columns(header, data)
    assert mapping["date"] == 0
    assert mapping["description"] == 1
    assert mapping["amount"] == 2
    assert mapping["source"] == 3


def test_classify_columns_inferred_from_data():
    mapping = _classify_columns(None, ["2024-03-15", "Grocery", "75.50"])
    assert mapping["date"] == 0
    assert mapping["description"] == 1
    assert mapping["amount"] == 2


def test_classify_columns_inferred_negative_amount():
    mapping = _classify_columns(None, ["2024-03-15", "Netflix", "-12.99"])
    assert mapping["date"] == 0
    assert mapping["description"] == 1
    assert mapping["amount"] == 2


# ---------------------------------------------------------------------------
# _is_header_row
# ---------------------------------------------------------------------------


def test_is_header_row_detects_date():
    assert _is_header_row(["date", "description", "amount"])


def test_is_header_row_detects_amount():
    assert _is_header_row(["col1", "col2", "AMOUNT"])


def test_is_header_row_false_for_data_row():
    assert not _is_header_row(["2024-03-15", "Amazon", "75.50"])


def test_is_header_row_false_for_empty():
    assert not _is_header_row([])


# ---------------------------------------------------------------------------
# _extract_row
# ---------------------------------------------------------------------------


def test_extract_row_expense_from_negative_amount():
    col_map = {"date": 0, "description": 1, "amount": 2}
    row = ["2024-03-15", "Netflix", "-12.99"]
    t = _extract_row(row, col_map)
    assert t.amount == Decimal("12.99")
    assert t.type == "expense"
    assert t.source == "pdf"
    assert t.category == "uncategorized"


def test_extract_row_income_from_positive_amount():
    col_map = {"date": 0, "description": 1, "amount": 2}
    row = ["2024-03-15", "Salary", "2000.00"]
    t = _extract_row(row, col_map)
    assert t.amount == Decimal("2000.00")
    assert t.type == "income"


def test_extract_row_uses_explicit_type_over_sign():
    # Negative amount but explicit type="income" (e.g. a refund credit)
    col_map = {"date": 0, "description": 1, "amount": 2, "type": 3}
    row = ["2024-03-15", "Refund", "-25.00", "income"]
    t = _extract_row(row, col_map)
    assert t.amount == Decimal("25.00")
    assert t.type == "income"


def test_extract_row_uses_explicit_type():
    col_map = {"date": 0, "description": 1, "amount": 2, "type": 3}
    row = ["2024-03-15", "Refund", "25.00", "income"]
    t = _extract_row(row, col_map)
    assert t.type == "income"


def test_extract_row_invalid_date_raises():
    col_map = {"date": 0, "description": 1, "amount": 2}
    with pytest.raises(ValueError, match="Cannot parse date"):
        _extract_row(["bad-date", "Netflix", "12.99"], col_map)


def test_extract_row_invalid_amount_raises():
    col_map = {"date": 0, "description": 1, "amount": 2}
    with pytest.raises(ValueError, match="Cannot parse amount"):
        _extract_row(["2024-03-15", "Netflix", "not-a-number"], col_map)


def test_extract_row_empty_description_raises():
    col_map = {"date": 0, "description": 1, "amount": 2}
    with pytest.raises(ValueError, match="Description is empty"):
        _extract_row(["2024-03-15", "", "12.99"], col_map)


# ---------------------------------------------------------------------------
# parse_pdf — integration-level tests (pdfplumber mocked)
# ---------------------------------------------------------------------------


def test_parse_pdf_single_row_with_full_header():
    table = [
        ["date", "description", "amount", "type", "source", "category"],
        ["2024-03-15", "Grocery shopping", "75.50", "expense", "credit_card", "food"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 1
    t = txns[0]
    assert t.date == datetime.date(2024, 3, 15)
    assert t.description == "Grocery shopping"
    assert t.amount == Decimal("75.50")
    assert t.type == "expense"
    assert t.source == "credit_card"
    assert t.category == "food"


def test_parse_pdf_multiple_rows():
    table = [
        ["date", "description", "amount", "type", "source", "category"],
        ["2024-03-15", "Grocery", "75.50", "expense", "credit_card", "food"],
        ["2024-03-16", "Salary", "2000.00", "income", "bank", "salary"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 2
    assert txns[0].description == "Grocery"
    assert txns[1].description == "Salary"


def test_parse_pdf_negative_amount_becomes_expense():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Netflix", "-12.99"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].amount == Decimal("12.99")
    assert txns[0].type == "expense"


def test_parse_pdf_positive_amount_defaults_to_income():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Salary", "2000.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].type == "income"


def test_parse_pdf_defaults_source_and_category():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Amazon", "50.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].source == "pdf"
    assert txns[0].category == "uncategorized"


def test_parse_pdf_infers_columns_without_header():
    # No header row: columns must be inferred from first data row via regex
    table = [
        ["2024-03-15", "Grocery", "75.50"],
        ["2024-03-16", "Gas", "40.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 2
    assert txns[0].description == "Grocery"
    assert txns[1].description == "Gas"


def test_parse_pdf_alias_header_memo_and_value():
    table = [
        ["Date", "Memo", "Value"],
        ["2024-03-15", "Amazon", "75.50"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].description == "Amazon"
    assert txns[0].amount == Decimal("75.50")


def test_parse_pdf_multiple_pages():
    page1_table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Grocery", "75.50"],
    ]
    page2_table = [
        ["date", "description", "amount"],
        ["2024-03-16", "Gas", "40.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[page1_table], [page2_table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 2
    assert txns[0].description == "Grocery"
    assert txns[1].description == "Gas"


def test_parse_pdf_skips_empty_rows():
    table = [
        ["date", "description", "amount"],
        [],
        ["2024-03-15", "Grocery", "75.50"],
        None,
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 1


def test_parse_pdf_skips_table_without_required_columns():
    # A table whose columns cannot be identified should be skipped entirely
    table = [
        ["col_a", "col_b"],
        ["foo", "bar"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 0


def test_parse_pdf_empty_pdf_returns_empty_list():
    with patch("pdfplumber.open", return_value=_mock_pdf([[]])):
        txns = parse_pdf(b"fake pdf")

    assert txns == []


def test_parse_pdf_invalid_row_raises_value_error():
    table = [
        ["date", "description", "amount"],
        ["not-a-date", "Netflix", "12.99"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        with pytest.raises(ValueError, match=r"Invalid data in PDF page 1, row 2"):
            parse_pdf(b"fake pdf")


def test_parse_pdf_uk_slash_date_format():
    table = [
        ["date", "description", "amount"],
        ["15/03/2024", "Costa Coffee", "4.50"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].date == datetime.date(2024, 3, 15)


def test_parse_pdf_dd_mmm_yyyy_date_format():
    table = [
        ["date", "description", "amount"],
        ["15 Mar 2024", "Starbucks", "3.75"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].date == datetime.date(2024, 3, 15)


def test_parse_pdf_amount_with_gbp_symbol():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Tesco", "£12.50"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].amount == Decimal("12.50")


def test_parse_pdf_amount_with_thousands_comma():
    table = [
        ["date", "description", "amount"],
        ["2024-03-15", "Rent", "1,200.00"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert txns[0].amount == Decimal("1200.00")
