"""Unit tests for the bank-aware CSV parsing service."""

import io
from decimal import Decimal

import csv
import pytest

from app.services.csv_parser import parse_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv_bytes(headers: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Generic format (backward-compatible)
# ---------------------------------------------------------------------------


def test_generic_format_single_row():
    content = _make_csv_bytes(
        ["date", "description", "amount", "type", "source", "category"],
        [["2024-03-15", "Grocery shopping", "75.50", "expense", "credit_card", "food"]],
    )
    txns = parse_csv(content)
    assert len(txns) == 1
    t = txns[0]
    assert t.date.isoformat() == "2024-03-15"
    assert t.description == "Grocery shopping"
    assert t.amount == Decimal("75.50")
    assert t.type == "expense"
    assert t.source == "credit_card"
    assert t.category == "food"


def test_generic_format_multiple_rows():
    content = _make_csv_bytes(
        ["date", "description", "amount", "type", "source", "category"],
        [
            ["2024-03-15", "Grocery", "75.50", "expense", "credit_card", "food"],
            ["2024-03-16", "Salary", "2000.00", "income", "bank", "salary"],
        ],
    )
    txns = parse_csv(content)
    assert len(txns) == 2
    assert txns[0].description == "Grocery"
    assert txns[1].description == "Salary"


def test_generic_format_amount_with_comma():
    content = _make_csv_bytes(
        ["date", "description", "amount", "type", "source", "category"],
        [["2024-03-15", "Test", "1,234.56", "expense", "bank", "other"]],
    )
    txns = parse_csv(content)
    assert txns[0].amount == Decimal("1234.56")


def test_generic_format_missing_columns_raises():
    content = b"date,description\n2024-03-15,Test\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_csv(content)


def test_generic_format_invalid_date_raises():
    content = _make_csv_bytes(
        ["date", "description", "amount", "type", "source", "category"],
        [["not-a-date", "Test", "10.00", "expense", "bank", "food"]],
    )
    with pytest.raises(ValueError, match="CSV row 2"):
        parse_csv(content)


def test_generic_format_invalid_amount_raises():
    content = _make_csv_bytes(
        ["date", "description", "amount", "type", "source", "category"],
        [["2024-03-15", "Test", "not-a-number", "expense", "bank", "food"]],
    )
    with pytest.raises(ValueError, match="CSV row 2"):
        parse_csv(content)


def test_non_utf8_encoding_raises():
    with pytest.raises(ValueError, match="UTF-8"):
        parse_csv(b"\xff\xfe bad bytes")


# ---------------------------------------------------------------------------
# Barclays format
# ---------------------------------------------------------------------------
# Signature column: "Memo"
# Date format:      DD/MM/YYYY
# Amount sign:      negative = expense, positive = income


def test_barclays_expense_row():
    content = _make_csv_bytes(
        ["Date", "Memo", "Amount", "Balance"],
        [["15/03/2024", "Amazon", "-75.50", "1000.00"]],
    )
    txns = parse_csv(content)
    assert len(txns) == 1
    t = txns[0]
    assert t.date.isoformat() == "2024-03-15"
    assert t.description == "Amazon"
    assert t.amount == Decimal("75.50")
    assert t.type == "expense"
    assert t.source == "barclays"
    assert t.category == "shopping"


def test_barclays_income_row():
    content = _make_csv_bytes(
        ["Date", "Memo", "Amount"],
        [["16/03/2024", "Salary", "2000.00"]],
    )
    txns = parse_csv(content)
    t = txns[0]
    assert t.amount == Decimal("2000.00")
    assert t.type == "income"
    assert t.source == "barclays"


def test_barclays_multiple_rows():
    content = _make_csv_bytes(
        ["Date", "Memo", "Amount"],
        [
            ["15/03/2024", "Amazon", "-75.50"],
            ["16/03/2024", "Salary", "2000.00"],
            ["17/03/2024", "Netflix", "-12.99"],
        ],
    )
    txns = parse_csv(content)
    assert len(txns) == 3
    assert txns[0].type == "expense"
    assert txns[1].type == "income"
    assert txns[2].type == "expense"


# ---------------------------------------------------------------------------
# Monzo format
# ---------------------------------------------------------------------------
# Signature column: "Transaction ID"
# Date format:      YYYY-MM-DD
# Category column:  present in CSV


def test_monzo_basic_row():
    content = _make_csv_bytes(
        ["Transaction ID", "Date", "Time", "Type", "Name", "Emoji",
         "Category", "Amount", "Currency"],
        [["tx_001", "2024-03-15", "12:00:00", "Payment", "Grocery store",
          "🛒", "shopping", "-75.50", "GBP"]],
    )
    txns = parse_csv(content)
    assert len(txns) == 1
    t = txns[0]
    assert t.date.isoformat() == "2024-03-15"
    assert t.description == "Grocery store"
    assert t.amount == Decimal("75.50")
    assert t.type == "expense"
    assert t.source == "monzo"
    assert t.category == "shopping"


def test_monzo_income_row():
    content = _make_csv_bytes(
        ["Transaction ID", "Date", "Name", "Amount", "Category"],
        [["tx_002", "2024-03-16", "Employer Ltd", "2500.00", "income"]],
    )
    txns = parse_csv(content)
    t = txns[0]
    assert t.type == "income"
    assert t.category == "income"


def test_monzo_empty_category_defaults_to_uncategorized():
    content = _make_csv_bytes(
        ["Transaction ID", "Date", "Name", "Amount", "Category"],
        [["tx_003", "2024-03-17", "Unknown shop", "-5.00", ""]],
    )
    txns = parse_csv(content)
    assert txns[0].category == "uncategorized"


# ---------------------------------------------------------------------------
# Amex format
# ---------------------------------------------------------------------------
# Signature column: "Reference"
# Date format:      DD/MM/YYYY  (UK) or DD MMM YYYY


def test_amex_basic_row():
    content = _make_csv_bytes(
        ["Date", "Reference", "Description", "Amount"],
        [["15/03/2024", "REF001", "Amazon.co.uk", "75.50"]],
    )
    txns = parse_csv(content)
    assert len(txns) == 1
    t = txns[0]
    assert t.date.isoformat() == "2024-03-15"
    assert t.description == "Amazon.co.uk"
    assert t.amount == Decimal("75.50")
    assert t.type == "income"   # positive amount -> income
    assert t.source == "amex"
    assert t.category == "shopping"


def test_amex_refund_row():
    content = _make_csv_bytes(
        ["Date", "Reference", "Description", "Amount"],
        [["16/03/2024", "REF002", "Refund", "-25.00"]],
    )
    txns = parse_csv(content)
    t = txns[0]
    assert t.amount == Decimal("25.00")
    assert t.type == "expense"


def test_amex_date_format_dd_mmm_yyyy():
    content = _make_csv_bytes(
        ["Date", "Reference", "Description", "Amount"],
        [["15 Mar 2024", "REF003", "Costa Coffee", "4.50"]],
    )
    txns = parse_csv(content)
    assert txns[0].date.isoformat() == "2024-03-15"


# ---------------------------------------------------------------------------
# TransferWise format
# ---------------------------------------------------------------------------
# Signature column: "TransferWise ID"
# Date format:      YYYY-MM-DD


def test_transferwise_basic_row():
    content = _make_csv_bytes(
        ["TransferWise ID", "Date", "Amount", "Currency", "Description",
         "Payment Reference", "Running Balance"],
        [["T001", "2024-03-15", "-75.50", "GBP", "Grocery store",
          "REF001", "1000.00"]],
    )
    txns = parse_csv(content)
    assert len(txns) == 1
    t = txns[0]
    assert t.date.isoformat() == "2024-03-15"
    assert t.description == "Grocery store"
    assert t.amount == Decimal("75.50")
    assert t.type == "expense"
    assert t.source == "transferwise"
    assert t.category == "uncategorized"


def test_transferwise_income_row():
    content = _make_csv_bytes(
        ["TransferWise ID", "Date", "Amount", "Currency", "Description",
         "Payment Reference", "Running Balance"],
        [["T002", "2024-03-16", "500.00", "GBP", "Client payment",
          "REF002", "1500.00"]],
    )
    txns = parse_csv(content)
    t = txns[0]
    assert t.amount == Decimal("500.00")
    assert t.type == "income"


def test_transferwise_multiple_rows():
    content = _make_csv_bytes(
        ["TransferWise ID", "Date", "Amount", "Currency", "Description",
         "Payment Reference", "Running Balance"],
        [
            ["T001", "2024-03-15", "-75.50", "GBP", "Grocery store", "R1", "1000.00"],
            ["T002", "2024-03-16", "500.00", "GBP", "Client payment", "R2", "1500.00"],
        ],
    )
    txns = parse_csv(content)
    assert len(txns) == 2
    assert txns[0].type == "expense"
    assert txns[1].type == "income"


# ---------------------------------------------------------------------------
# Column name whitespace trimming
# ---------------------------------------------------------------------------


def test_column_names_with_surrounding_whitespace():
    """Leading/trailing spaces in header names must be tolerated."""
    content = b" Date , Memo , Amount \n15/03/2024, Amazon,-75.50\n"
    txns = parse_csv(content)
    assert len(txns) == 1
    assert txns[0].description == "Amazon"
