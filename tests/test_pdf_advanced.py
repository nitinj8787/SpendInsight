"""Unit tests for the advanced PDF parsing components.

Covers:
- BarclaysPDFParser (text-based state machine)
- AIPDFParser (mocked OpenAI API)
- HybridPDFParser (confidence scoring + AI fallback)
- TransactionPostProcessor (normalisation, categorisation, transfer detection)
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.pdf import (
    AIPDFParser,
    BarclaysPDFParser,
    HybridPDFParser,
    TransactionPostProcessor,
)
from app.schemas.transaction import TransactionCreate


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_text_pdf(text: str):
    """Return a pdfplumber mock that yields *text* on a single page."""
    page = MagicMock()
    page.extract_tables.return_value = []
    page.extract_text.return_value = text
    mock_pdf = MagicMock()
    mock_pdf.pages = [page]
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    return mock_pdf


def _txn(
    *,
    date: str = "2024-10-06",
    description: str = "Test",
    amount: str = "10.00",
    type: str = "expense",
    source: str = "barclays",
    category: str = "uncategorized",
) -> TransactionCreate:
    return TransactionCreate(
        date=datetime.date.fromisoformat(date),
        description=description,
        amount=Decimal(amount),
        type=type,
        source=source,
        category=category,
    )


# ===========================================================================
# BarclaysPDFParser — text-based state machine
# ===========================================================================


class TestBarclaysPDFParser:
    """Tests for BarclaysPDFParser using mocked pdfplumber text."""

    # -----------------------------------------------------------------------
    # Detection
    # -----------------------------------------------------------------------

    def test_can_parse_detects_barclays_text(self):
        parser = BarclaysPDFParser()
        assert parser.can_parse("Barclays Bank PLC — Statement") is True

    def test_can_parse_rejects_other_banks(self):
        parser = BarclaysPDFParser()
        assert parser.can_parse("HSBC Premier Banking") is False
        assert parser.can_parse("Monzo Bank Ltd") is False

    def test_source_is_barclays(self):
        assert BarclaysPDFParser.source == "barclays"

    # -----------------------------------------------------------------------
    # Basic extraction
    # -----------------------------------------------------------------------

    def test_parses_single_dr_transaction(self):
        text = "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 1
        t = txns[0]
        assert t.date.month == 10
        assert t.date.day == 6
        assert t.amount == Decimal("38.00")
        assert t.type == "expense"
        assert t.source == "barclays"

    def test_parses_single_cr_transaction(self):
        text = "14 Oct  Received From Danbro Employment  7726.72 CR\n"
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 1
        assert txns[0].type == "income"
        assert txns[0].amount == Decimal("7726.72")

    def test_parses_multiple_transactions_same_date(self):
        text = (
            "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
            "        Direct Debit to Thames Water  67.00 DR\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 2
        assert txns[0].date == txns[1].date

    def test_date_carried_forward_for_second_transaction(self):
        text = (
            "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
            "        Direct Debit to Thames Water  67.00 DR\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        # Both transactions should share the same date (06 Oct)
        assert txns[0].date == txns[1].date
        assert txns[0].date.day == 6

    def test_parses_multiline_description(self):
        text = (
            "15 Oct  L&G INSURANCE MI\n"
            "        REFERENCE 12345\n"
            "        18.07 DR\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 1
        assert "L&G INSURANCE MI" in txns[0].description

    def test_ignores_start_balance_line(self):
        text = (
            "04 Oct  Start balance  9629.70\n"
            "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 1
        assert txns[0].description == "Direct Debit to Sky Digital"

    def test_ignores_end_balance_line(self):
        text = (
            "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
            "31 Oct  End balance  9500.00\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 1

    def test_parses_full_statement_block(self):
        text = (
            "04 Oct  Start balance                       9629.70\n"
            "06 Oct  Direct Debit to Sky Digital           38.00 DR\n"
            "06 Oct  Direct Debit to Thames Water          67.00 DR\n"
            "14 Oct  Received From Danbro Employment     7726.72 CR\n"
            "15 Oct  L&G Insurance                         18.07 DR\n"
            "31 Oct  End balance                         17232.85\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert len(txns) == 4
        assert txns[0].amount == Decimal("38.00")
        assert txns[1].amount == Decimal("67.00")
        assert txns[2].type == "income"
        assert txns[3].amount == Decimal("18.07")

    def test_returns_empty_for_blank_pdf(self):
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("")):
            txns = parser.parse(b"fake")
        assert txns == []

    def test_amounts_always_positive(self):
        text = "06 Oct  DIRECT DEBIT  38.00 DR\n"
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")
        assert txns[0].amount > 0

    def test_date_uses_current_year(self):
        text = "06 Oct  DIRECT DEBIT  38.00 DR\n"
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")
        assert txns[0].date.year == datetime.date.today().year

    def test_missing_date_line_uses_previous_date(self):
        """Continuation transactions without a date header get the last date."""
        text = (
            "06 Oct  Direct Debit to Sky Digital  38.00 DR\n"
            "        Direct Debit to Thames Water  67.00 DR\n"
        )
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")

        assert txns[1].date.day == 6

    def test_category_assigned_by_rules(self):
        text = "06 Oct  Netflix subscription  12.99 DR\n"
        parser = BarclaysPDFParser()
        with patch("pdfplumber.open", return_value=_make_text_pdf(text)):
            txns = parser.parse(b"fake")
        assert txns[0].category == "entertainment"


# ===========================================================================
# AIPDFParser — OpenAI API integration (mocked)
# ===========================================================================


class TestAIPDFParser:
    """Tests for AIPDFParser with the OpenAI client mocked out."""

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _make_parser(self) -> AIPDFParser:
        return AIPDFParser(api_key="test-key", model="gpt-4o-mini", retry_delay=0)

    def _mock_openai_response(self, content: str) -> MagicMock:
        """Return a mock that mimics the OpenAI client.chat.completions.create response."""
        choice = MagicMock()
        choice.message.content = content
        response = MagicMock()
        response.choices = [choice]
        return response

    # -----------------------------------------------------------------------
    # can_parse
    # -----------------------------------------------------------------------

    def test_can_parse_always_returns_false(self):
        parser = self._make_parser()
        assert parser.can_parse("Any text at all") is False

    # -----------------------------------------------------------------------
    # Successful extraction
    # -----------------------------------------------------------------------

    def test_parse_returns_valid_transactions(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Tesco Superstore", "amount": 42.50, "type": "expense"},
            {"date": "2024-03-20", "description": "Salary BACS", "amount": 2500.00, "type": "income"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 2
        assert txns[0].description == "Tesco Superstore"
        assert txns[0].amount == Decimal("42.50")
        assert txns[0].type == "expense"
        assert txns[1].description == "Salary BACS"
        assert txns[1].type == "income"

    def test_parse_strips_markdown_code_fences(self):
        payload = "```json\n[{\"date\": \"2024-03-15\", \"description\": \"Netflix\", \"amount\": 12.99, \"type\": \"expense\"}]\n```"
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1
        assert txns[0].description == "Netflix"

    def test_parse_negative_amount_normalised_to_positive(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Gas Bill", "amount": -45.00, "type": "expense"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert txns[0].amount == Decimal("45.00")
        assert txns[0].type == "expense"

    # -----------------------------------------------------------------------
    # Retry logic
    # -----------------------------------------------------------------------

    def test_retries_on_api_failure_and_succeeds(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Amazon", "amount": 25.99, "type": "expense"},
        ])
        call_count = 0

        def flaky_api(text: str) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("temporary network error")
            return payload

        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", side_effect=flaky_api):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1
        assert call_count == 2  # failed once then succeeded

    def test_returns_empty_after_all_retries_exhausted(self):
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", side_effect=ConnectionError("always fails")):
                txns = parser.parse(b"fake pdf")

        assert txns == []

    # -----------------------------------------------------------------------
    # Validation of AI response
    # -----------------------------------------------------------------------

    def test_skips_items_with_invalid_date(self):
        payload = json.dumps([
            {"date": "not-a-date", "description": "Something", "amount": 10.00, "type": "expense"},
            {"date": "2024-03-15", "description": "Valid", "amount": 20.00, "type": "income"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1
        assert txns[0].description == "Valid"

    def test_skips_items_with_missing_description(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "", "amount": 10.00, "type": "expense"},
            {"date": "2024-03-15", "description": "Good item", "amount": 5.00, "type": "expense"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1

    def test_skips_items_with_invalid_amount(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Bad amount", "amount": "not-a-number", "type": "expense"},
            {"date": "2024-03-15", "description": "Good", "amount": 99.00, "type": "income"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1

    def test_returns_empty_for_invalid_json(self):
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value="this is not json"):
                txns = parser.parse(b"fake pdf")

        assert txns == []

    def test_returns_empty_for_json_object_not_array(self):
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value='{"key": "value"}'):
                txns = parser.parse(b"fake pdf")

        assert txns == []

    def test_returns_empty_for_blank_pdf(self):
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("")):
            txns = parser.parse(b"fake pdf")
        assert txns == []

    def test_type_defaults_to_expense_for_unknown_type_value(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Payment", "amount": 15.00, "type": "debit"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert len(txns) == 1
        assert txns[0].type == "expense"

    def test_category_assigned_by_rules(self):
        payload = json.dumps([
            {"date": "2024-03-15", "description": "Tesco Extra", "amount": 32.00, "type": "expense"},
        ])
        parser = self._make_parser()
        with patch("pdfplumber.open", return_value=_make_text_pdf("some text")):
            with patch.object(parser, "_call_api", return_value=payload):
                txns = parser.parse(b"fake pdf")

        assert txns[0].category == "food"

    def test_raises_import_error_when_openai_not_installed(self):
        parser = self._make_parser()
        parser._client = None  # ensure lazy init path
        with patch("pdfplumber.open", return_value=_make_text_pdf("text")):
            with patch.dict("sys.modules", {"openai": None}):
                # The import happens inside _get_client; force it to run
                with pytest.raises(ImportError, match="openai"):
                    parser._get_client()


# ===========================================================================
# HybridPDFParser — confidence scoring + AI fallback
# ===========================================================================


class TestHybridPDFParser:
    """Tests for HybridPDFParser."""

    def _make_txns(self, n: int, source: str = "barclays") -> list[TransactionCreate]:
        return [
            _txn(description=f"Transaction {i}", source=source)
            for i in range(n)
        ]

    def _mock_pdf_with_amount_lines(self, n_amount_lines: int):
        """Return a pdf mock with *n_amount_lines* lines containing decimals."""
        lines = [f"06 Oct  Merchant {i}  {10 + i}.00 DR" for i in range(n_amount_lines)]
        return _make_text_pdf("\n".join(lines))

    # -----------------------------------------------------------------------
    # can_parse delegates to primary
    # -----------------------------------------------------------------------

    def test_can_parse_delegates_to_primary(self):
        primary = MagicMock()
        primary.can_parse.return_value = True
        hybrid = HybridPDFParser(primary=primary)
        assert hybrid.can_parse("any text") is True
        primary.can_parse.assert_called_once_with("any text")

    # -----------------------------------------------------------------------
    # High-confidence path: use structured result
    # -----------------------------------------------------------------------

    def test_uses_structured_result_when_confidence_high(self):
        primary = MagicMock()
        ai = MagicMock()
        structured = self._make_txns(4)
        primary.parse.return_value = structured

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai, confidence_threshold=0.5)

        # 4 amount lines in PDF text → 4/4 = 1.0 confidence
        mock_pdf = self._mock_pdf_with_amount_lines(4)
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = hybrid.parse(b"fake")

        assert result == structured
        ai.parse.assert_not_called()
        assert hybrid.last_confidence == 1.0

    # -----------------------------------------------------------------------
    # Low-confidence path: AI fallback
    # -----------------------------------------------------------------------

    def test_uses_ai_when_confidence_below_threshold(self):
        primary = MagicMock()
        ai_parser = MagicMock()
        structured = self._make_txns(1)  # only 1 out of 5 lines parsed
        ai_result = self._make_txns(5, source="ai")
        primary.parse.return_value = structured
        ai_parser.parse.return_value = ai_result

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.6)

        mock_pdf = self._mock_pdf_with_amount_lines(5)
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = hybrid.parse(b"fake")

        # confidence = 1/5 = 0.2, below 0.6 → AI is called
        ai_parser.parse.assert_called_once()
        assert result == ai_result
        assert hybrid.last_strategy == "AIPDFParser"

    def test_returns_structured_when_ai_returns_fewer_transactions(self):
        primary = MagicMock()
        ai_parser = MagicMock()
        structured = self._make_txns(3)
        ai_result = self._make_txns(1)  # AI found fewer
        primary.parse.return_value = structured
        ai_parser.parse.return_value = ai_result

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.9)

        mock_pdf = self._mock_pdf_with_amount_lines(10)
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = hybrid.parse(b"fake")

        # AI result < structured result → keep structured
        assert result == structured

    # -----------------------------------------------------------------------
    # Error handling
    # -----------------------------------------------------------------------

    def test_primary_exception_falls_to_ai(self):
        primary = MagicMock()
        ai_parser = MagicMock()
        primary.parse.side_effect = ValueError("parse error")
        ai_result = self._make_txns(2, source="ai")
        ai_parser.parse.return_value = ai_result

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.5)

        mock_pdf = self._mock_pdf_with_amount_lines(2)
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = hybrid.parse(b"fake")

        # Primary failed → confidence=0, AI is invoked
        assert result == ai_result

    def test_ai_exception_returns_structured_result(self):
        primary = MagicMock()
        ai_parser = MagicMock()
        structured = self._make_txns(1)
        primary.parse.return_value = structured
        ai_parser.parse.side_effect = RuntimeError("AI is down")

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.9)

        mock_pdf = self._mock_pdf_with_amount_lines(5)
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = hybrid.parse(b"fake")

        assert result == structured

    # -----------------------------------------------------------------------
    # Confidence tracking
    # -----------------------------------------------------------------------

    def test_last_confidence_reflects_calculation(self):
        primary = MagicMock()
        ai_parser = MagicMock()
        primary.parse.return_value = self._make_txns(3)
        ai_parser.parse.return_value = []

        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.5)

        mock_pdf = self._mock_pdf_with_amount_lines(4)
        with patch("pdfplumber.open", return_value=mock_pdf):
            hybrid.parse(b"fake")

        # 3 parsed / 4 candidates = 0.75
        assert abs(hybrid.last_confidence - 0.75) < 0.01

    def test_last_strategy_set_for_primary_path(self):
        primary = BarclaysPDFParser()
        ai_parser = MagicMock()
        ai_parser.parse.return_value = []
        hybrid = HybridPDFParser(primary=primary, ai_parser=ai_parser, confidence_threshold=0.0)

        with patch.object(primary, "parse", return_value=self._make_txns(2)):
            mock_pdf = self._mock_pdf_with_amount_lines(2)
            with patch("pdfplumber.open", return_value=mock_pdf):
                hybrid.parse(b"fake")

        assert hybrid.last_strategy == "BarclaysPDFParser"


# ===========================================================================
# TransactionPostProcessor
# ===========================================================================


class TestTransactionPostProcessor:
    """Tests for TransactionPostProcessor."""

    # -----------------------------------------------------------------------
    # Amount normalisation
    # -----------------------------------------------------------------------

    def test_normalise_negative_amount_to_positive(self):
        t = _txn(amount="-50.00", type="expense")
        processor = TransactionPostProcessor()
        result = processor.process([t])
        assert result[0].amount == Decimal("50.00")
        assert result[0].amount > 0

    def test_normalise_positive_amount_unchanged(self):
        t = _txn(amount="50.00", type="income")
        processor = TransactionPostProcessor()
        result = processor.process([t])
        assert result[0].amount == Decimal("50.00")

    def test_negative_amount_infers_expense_type(self):
        t = _txn(amount="-25.00", type="")
        processor = TransactionPostProcessor()
        result = processor.process([t])
        assert result[0].type == "expense"

    # -----------------------------------------------------------------------
    # Categorisation
    # -----------------------------------------------------------------------

    def test_categorises_uncategorized_transaction(self):
        t = _txn(description="Tesco Superstore", category="uncategorized")
        processor = TransactionPostProcessor()
        result = processor.process([t])
        assert result[0].category == "food"

    def test_does_not_overwrite_existing_category(self):
        t = _txn(description="Tesco Superstore", category="groceries")
        processor = TransactionPostProcessor()
        result = processor.process([t])
        assert result[0].category == "groceries"  # kept

    def test_custom_categorize_fn_is_called(self):
        called = []

        def my_fn(desc: str) -> str:
            called.append(desc)
            return "custom"

        t = _txn(description="Unknown Merchant", category="uncategorized")
        processor = TransactionPostProcessor(categorize_fn=my_fn)
        result = processor.process([t])
        assert result[0].category == "custom"
        assert "Unknown Merchant" in called

    def test_categorize_fn_exception_falls_back_to_uncategorized(self):
        def bad_fn(desc: str) -> str:
            raise RuntimeError("AI offline")

        t = _txn(description="Some Merchant", category="uncategorized")
        processor = TransactionPostProcessor(categorize_fn=bad_fn)
        result = processor.process([t])
        assert result[0].category == "uncategorized"

    # -----------------------------------------------------------------------
    # Internal transfer detection
    # -----------------------------------------------------------------------

    def test_detects_matching_transfer_pair(self):
        debit = _txn(
            date="2024-03-15",
            description="Transfer to Savings",
            amount="500.00",
            type="expense",
            category="shopping",
        )
        credit = _txn(
            date="2024-03-15",
            description="Received from Current",
            amount="500.00",
            type="income",
            category="income",
        )
        processor = TransactionPostProcessor(transfer_window_days=2)
        result = processor.process([debit, credit])
        assert result[0].category == "transfer"
        assert result[1].category == "transfer"

    def test_does_not_match_same_type_transactions(self):
        t1 = _txn(date="2024-03-15", amount="500.00", type="expense")
        t2 = _txn(date="2024-03-15", amount="500.00", type="expense")
        processor = TransactionPostProcessor(transfer_window_days=2)
        result = processor.process([t1, t2])
        # Both expenses — not a transfer pair
        assert result[0].category != "transfer"
        assert result[1].category != "transfer"

    def test_does_not_match_outside_time_window(self):
        debit = _txn(date="2024-03-15", amount="500.00", type="expense")
        credit = _txn(date="2024-03-20", amount="500.00", type="income")  # 5 days apart
        processor = TransactionPostProcessor(transfer_window_days=2)
        result = processor.process([debit, credit])
        assert result[0].category != "transfer"
        assert result[1].category != "transfer"

    def test_does_not_match_different_amounts(self):
        debit = _txn(date="2024-03-15", amount="500.00", type="expense")
        credit = _txn(date="2024-03-15", amount="499.00", type="income")
        processor = TransactionPostProcessor(transfer_window_days=2)
        result = processor.process([debit, credit])
        assert result[0].category != "transfer"

    def test_transfer_detection_disabled_when_window_is_zero(self):
        debit = _txn(date="2024-03-15", amount="500.00", type="expense")
        credit = _txn(date="2024-03-15", amount="500.00", type="income")
        processor = TransactionPostProcessor(transfer_window_days=0)
        result = processor.process([debit, credit])
        assert result[0].category != "transfer"
        assert result[1].category != "transfer"

    def test_process_empty_list(self):
        processor = TransactionPostProcessor()
        assert processor.process([]) == []

    def test_process_multiple_transactions(self):
        transactions = [
            _txn(description="Netflix", amount="12.99", type="expense", category="uncategorized"),
            _txn(description="Salary", amount="2000.00", type="income", category="uncategorized"),
            _txn(description="Tesco", amount="-45.00", type="expense", category="uncategorized"),
        ]
        processor = TransactionPostProcessor()
        result = processor.process(transactions)

        assert len(result) == 3
        assert result[0].category == "entertainment"
        assert result[1].category == "income"
        assert result[2].amount == Decimal("45.00")  # normalised
        assert result[2].category == "food"

    def test_amount_tolerance_allows_slight_difference(self):
        debit = _txn(date="2024-03-15", amount="500.00", type="expense", category="uncategorized")
        credit = _txn(date="2024-03-15", amount="500.01", type="income", category="uncategorized")
        processor = TransactionPostProcessor(
            transfer_window_days=2,
            transfer_amount_tolerance=Decimal("0.05"),
        )
        result = processor.process([debit, credit])
        assert result[0].category == "transfer"
        assert result[1].category == "transfer"


# ===========================================================================
# ParserFactory — integration: BarclaysPDFParser selected for Barclays text
# ===========================================================================


class TestParserFactoryWithBarclaysText:
    """Verify that ParserFactory auto-selects BarclaysPDFParser when text contains 'Barclays'."""

    def test_factory_selects_barclays_parser(self):
        from app.services.pdf import ParserFactory

        factory = ParserFactory()
        # Use priority=-1 so BarclaysPDFParser takes precedence over
        # the table-based BarclaysParser (registered at priority=0).
        factory.register(BarclaysPDFParser(), priority=-1)
        with patch.object(factory, "_extract_text", return_value="Barclays Bank PLC Statement"):
            parser = factory.detect(b"fake")
        assert isinstance(parser, BarclaysPDFParser)
