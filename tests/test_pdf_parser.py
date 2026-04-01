"""Unit tests for the PDF parsing service."""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf_parser import (
    _classify_columns,
    _extract_row,
    _is_balance_row,
    _is_header_row,
    _parse_amount,
    _parse_date,
    _row_has_amount,
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


def test_parse_date_dd_mmm_no_year():
    """'04 Oct' style dates (no year) should use the current calendar year."""
    result = _parse_date("04 Oct")
    assert result is not None
    assert result.month == 10
    assert result.day == 4
    assert result.year == datetime.date.today().year


def test_parse_date_dd_mmm_no_year_single_digit_day():
    result = _parse_date("4 Oct")
    assert result is not None
    assert result.month == 10
    assert result.day == 4
    assert result.year == datetime.date.today().year


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


def test_classify_columns_money_out_money_in():
    """'Money out' / 'Money in' headers must be recognised as debit/credit."""
    header = ["Date", "Description", "Money out", "Money in", "Balance"]
    data = ["04 Oct", "Direct Debit to Sky", "38.00", "", "9,524.70"]
    mapping = _classify_columns(header, data)
    assert mapping["date"] == 0
    assert mapping["description"] == 1
    assert mapping["debit"] == 2
    assert mapping["credit"] == 3


def test_classify_columns_debit_credit_headers():
    header = ["date", "description", "debit", "credit"]
    data = ["2024-03-15", "Payment", "50.00", ""]
    mapping = _classify_columns(header, data)
    assert mapping["debit"] == 2
    assert mapping["credit"] == 3


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
# _is_balance_row
# ---------------------------------------------------------------------------


def test_is_balance_row_start_balance():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    row = ["04 Oct", "Start balance", "", "9629.70"]
    assert _is_balance_row(row, col_map)


def test_is_balance_row_opening_balance():
    col_map = {"date": 0, "description": 1, "amount": 2}
    row = ["2024-03-01", "Opening balance", "5000.00"]
    assert _is_balance_row(row, col_map)


def test_is_balance_row_closing_balance():
    col_map = {"date": 0, "description": 1, "amount": 2}
    row = ["2024-03-31", "Closing balance", "4200.00"]
    assert _is_balance_row(row, col_map)


def test_is_balance_row_false_for_normal_transaction():
    col_map = {"date": 0, "description": 1, "amount": 2}
    row = ["2024-03-15", "Direct Debit to Sky", "38.00"]
    assert not _is_balance_row(row, col_map)


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
    assert t.category == "entertainment"


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


def test_extract_row_debit_column_is_expense():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    row = ["04 Oct", "Direct Debit to Sky", "38.00", ""]
    t = _extract_row(row, col_map)
    assert t.amount == Decimal("38.00")
    assert t.type == "expense"


def test_extract_row_credit_column_is_income():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    row = ["04 Oct", "Received From Danbro Employment", "", "7726.72"]
    t = _extract_row(row, col_map)
    assert t.amount == Decimal("7726.72")
    assert t.type == "income"


def test_extract_row_fallback_date_used_when_date_empty():
    fallback = datetime.date(2025, 10, 6)
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    row = ["", "Direct Debit to Thames Water", "67.00", ""]
    t = _extract_row(row, col_map, fallback_date=fallback)
    assert t.date == fallback
    assert t.amount == Decimal("67.00")
    assert t.type == "expense"


def test_extract_row_empty_date_no_fallback_raises():
    col_map = {"date": 0, "description": 1, "amount": 2}
    with pytest.raises(ValueError, match="Cannot parse date"):
        _extract_row(["", "Netflix", "12.99"], col_map)


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
    assert txns[0].category == "shopping"


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


def test_parse_pdf_money_out_money_in_columns():
    """Bank statements with separate 'Money out' / 'Money in' columns."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["04 Oct", "Start balance", "", "", "9,629.70"],
        ["06 Oct", "Direct Debit to Sky Digital", "38.00", "", "9,591.70"],
        ["06 Oct", "Direct Debit to Thames Water", "67.00", "", "9,524.70"],
        ["14 Oct", "Received From Danbro Employment", "", "7,726.72", "16,823.36"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    # "Start balance" row is skipped
    assert len(txns) == 3
    assert txns[0].description == "Direct Debit to Sky Digital"
    assert txns[0].amount == Decimal("38.00")
    assert txns[0].type == "expense"
    assert txns[1].description == "Direct Debit to Thames Water"
    assert txns[1].amount == Decimal("67.00")
    assert txns[1].type == "expense"
    assert txns[2].description == "Received From Danbro Employment"
    assert txns[2].amount == Decimal("7726.72")
    assert txns[2].type == "income"


def test_parse_pdf_dd_mmm_date_without_year():
    """Dates in 'DD MMM' format (no year) should parse using the current year."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["10 Oct", "Direct Debit to L&G Insurance MI", "18.07", "", "9,506.63"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].date.month == 10
    assert txns[0].date.day == 10
    assert txns[0].date.year == datetime.date.today().year


def test_parse_pdf_start_balance_row_skipped():
    """Opening-balance rows must be silently skipped."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["04 Oct", "Start balance", "", "", "9,629.70"],
        ["06 Oct", "Direct Debit to Sky Digital", "38.00", "", "9,591.70"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 1
    assert txns[0].description == "Direct Debit to Sky Digital"


def test_parse_pdf_date_carried_forward_for_continuation_rows():
    """Rows with an empty date cell reuse the date from the previous row."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["06 Oct", "Direct Debit to Sky Digital", "38.00", "", ""],
        ["", "Direct Debit to Thames Water", "67.00", "", "9,524.70"],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    assert len(txns) == 2
    assert txns[1].date == txns[0].date


# ---------------------------------------------------------------------------
# _row_has_amount
# ---------------------------------------------------------------------------


def test_row_has_amount_single_column_non_empty():
    col_map = {"date": 0, "description": 1, "amount": 2}
    assert _row_has_amount(["2024-01-01", "Tesco", "12.50"], col_map) is True


def test_row_has_amount_single_column_empty():
    col_map = {"date": 0, "description": 1, "amount": 2}
    assert _row_has_amount(["", "Ref: 12345", ""], col_map) is False


def test_row_has_amount_debit_credit_debit_present():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    assert _row_has_amount(["06 Oct", "Sky Digital", "38.00", ""], col_map) is True


def test_row_has_amount_debit_credit_credit_present():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    assert _row_has_amount(["14 Oct", "Salary", "", "2000.00"], col_map) is True


def test_row_has_amount_debit_credit_both_empty():
    col_map = {"date": 0, "description": 1, "debit": 2, "credit": 3}
    assert _row_has_amount(["", "Ref: 006247495311452", "", ""], col_map) is False


# ---------------------------------------------------------------------------
# Barclays-style Ref sub-rows skipped during full parse
# ---------------------------------------------------------------------------


def test_parse_pdf_barclays_ref_rows_skipped():
    """Ref sub-rows (no amount) must be silently skipped; transaction rows parsed."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["04 Oct", "Start balance", "", "", "9,629.70"],
        ["06 Oct", "DD Direct Debit to Sky Digital", "38.00", "", ""],
        ["", "Ref: 006247495311452", "", "", ""],
        ["", "DD Direct Debit to Thames Water", "67.00", "", "9,524.70"],
        ["", "Ref: 900067217429", "", "", ""],
        ["14 Oct", "Giro Received From Danbro Employment", "", "7,726.72", "16,823.36"],
        ["", "Ref: Danbro Employment", "", "", ""],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    # Start balance + three Ref rows skipped → 3 transactions
    assert len(txns) == 3

    assert txns[0].description == "DD Direct Debit to Sky Digital"
    assert txns[0].amount == Decimal("38.00")
    assert txns[0].type == "expense"
    assert txns[0].date.day == 6

    assert txns[1].description == "DD Direct Debit to Thames Water"
    assert txns[1].amount == Decimal("67.00")
    assert txns[1].type == "expense"
    assert txns[1].date == txns[0].date  # date carried forward

    assert txns[2].description == "Giro Received From Danbro Employment"
    assert txns[2].amount == Decimal("7726.72")
    assert txns[2].type == "income"
    assert txns[2].date.day == 14


def test_parse_pdf_barclays_multiline_description_ref_rows():
    """Multi-line transactions where Ref row has no amount are skipped across dates."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["13 Oct", "Bill Payment to Nitin Jain", "400.00", "", "9,106.63"],
        ["", "Ref: Nitin Monzo", "", "", ""],
        ["14 Oct", "DD Direct Debit to Interactive Invest", "9.99", "", ""],
        ["", "Ref: A05104971000Tdfeeo", "", "", ""],
        ["", "This Is A New Direct Debit Payment", "", "", ""],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    # "This Is A New Direct Debit Payment" has no amount → skipped
    assert len(txns) == 2
    assert txns[0].description == "Bill Payment to Nitin Jain"
    assert txns[0].amount == Decimal("400.00")
    assert txns[1].description == "DD Direct Debit to Interactive Invest"
    assert txns[1].amount == Decimal("9.99")


def test_parse_pdf_barclays_full_statement_sample():
    """Realistic Barclays table matching the PDF format in the bug report."""
    table = [
        ["Date", "Description", "Money out", "Money in", "Balance"],
        ["04 Oct", "Start balance", "", "", "9,629.70"],
        ["06 Oct", "DD Direct Debit to Sky Digital", "38.00", "", ""],
        ["", "Ref: 006247495311452", "", "", ""],
        ["", "DD Direct Debit to Thames Water", "67.00", "", "9,524.70"],
        ["", "Ref: 900067217429", "", "", ""],
        ["10 Oct", "DD Direct Debit to L&G Insurance MI", "18.07", "", "9,506.63"],
        ["", "Ref: 0238539324-251010", "", "", ""],
        ["13 Oct", "Bill Payment to Nitin Jain", "400.00", "", "9,106.63"],
        ["", "Ref: Nitin Monzo", "", "", ""],
        ["14 Oct", "DD Direct Debit to Interactive Invest", "9.99", "", ""],
        ["", "Ref: A05104971000Tdfeeo", "", "", ""],
        ["", "Giro Received From Danbro Employment", "", "7,726.72", "16,823.36"],
        ["", "Ref: Danbro Employment", "", "", ""],
        ["21 Oct", "DD Direct Debit to American Express", "1,741.70", "", "15,054.31"],
        ["", "Ref: 3746-802358-81007", "", "", ""],
    ]
    with patch("pdfplumber.open", return_value=_mock_pdf([[table]])):
        txns = parse_pdf(b"fake pdf")

    # Start balance + 7 Ref rows skipped → 7 transactions
    assert len(txns) == 7

    descs = [t.description for t in txns]
    assert "DD Direct Debit to Sky Digital" in descs
    assert "DD Direct Debit to Thames Water" in descs
    assert "DD Direct Debit to L&G Insurance MI" in descs
    assert "Bill Payment to Nitin Jain" in descs
    assert "DD Direct Debit to Interactive Invest" in descs
    assert "Giro Received From Danbro Employment" in descs
    assert "DD Direct Debit to American Express" in descs

    # Verify types
    income_txns = [t for t in txns if t.type == "income"]
    expense_txns = [t for t in txns if t.type == "expense"]
    assert len(income_txns) == 1
    assert income_txns[0].description == "Giro Received From Danbro Employment"
    assert income_txns[0].amount == Decimal("7726.72")
    assert len(expense_txns) == 6

    # Verify date carried forward within same-date group
    sky_txn = next(t for t in txns if "Sky Digital" in t.description)
    thames_txn = next(t for t in txns if "Thames Water" in t.description)
    assert sky_txn.date == thames_txn.date
    assert sky_txn.date.day == 6
