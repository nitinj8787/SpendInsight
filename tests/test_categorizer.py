"""Tests for the transaction categorization service."""

import pytest

from app.services.categorizer import (
    BaseCategorizer,
    RuleBasedCategorizer,
    TransactionCategorizer,
)


# ---------------------------------------------------------------------------
# RuleBasedCategorizer – keyword matching
# ---------------------------------------------------------------------------


class TestRuleBasedCategorizerFood:
    def test_tesco(self):
        assert RuleBasedCategorizer().categorize("TESCO STORES 2854") == "food"

    def test_sainsburys(self):
        assert RuleBasedCategorizer().categorize("SAINSBURY'S ONLINE") == "food"

    def test_deliveroo(self):
        assert RuleBasedCategorizer().categorize("DELIVEROO ORDER") == "food"

    def test_just_eat(self):
        assert RuleBasedCategorizer().categorize("JUST EAT UK") == "food"

    def test_mcdonalds(self):
        assert RuleBasedCategorizer().categorize("MCDONALD'S #1234") == "food"

    def test_starbucks(self):
        assert RuleBasedCategorizer().categorize("STARBUCKS CARD 012345") == "food"

    def test_restaurant(self):
        assert RuleBasedCategorizer().categorize("THE OLD RESTAURANT LTD") == "food"

    def test_case_insensitive(self):
        assert RuleBasedCategorizer().categorize("tesco express") == "food"


class TestRuleBasedCategorizerTransport:
    def test_uber_trip(self):
        assert RuleBasedCategorizer().categorize("UBER *TRIP LONDON") == "transport"

    def test_tfl(self):
        assert RuleBasedCategorizer().categorize("TFL TRAVEL CHARGE") == "transport"

    def test_national_rail(self):
        assert RuleBasedCategorizer().categorize("NATIONAL RAIL TICKET") == "transport"

    def test_easyjet(self):
        assert RuleBasedCategorizer().categorize("EASYJET FLIGHT EZY123") == "transport"

    def test_petrol(self):
        assert RuleBasedCategorizer().categorize("SHELL PETROL STATION") == "transport"

    def test_trainline(self):
        assert RuleBasedCategorizer().categorize("TRAINLINE.COM BOOKING") == "transport"


class TestRuleBasedCategorizerEntertainment:
    def test_netflix(self):
        assert RuleBasedCategorizer().categorize("NETFLIX.COM") == "entertainment"

    def test_spotify(self):
        assert RuleBasedCategorizer().categorize("SPOTIFY AB") == "entertainment"

    def test_disney_plus(self):
        assert RuleBasedCategorizer().categorize("DISNEY+ SUBSCRIPTION") == "entertainment"

    def test_cinema(self):
        assert RuleBasedCategorizer().categorize("ODEON CINEMA LONDON") == "entertainment"

    def test_xbox(self):
        assert RuleBasedCategorizer().categorize("XBOX GAME PASS") == "entertainment"


class TestRuleBasedCategorizerUtilities:
    def test_british_gas(self):
        assert RuleBasedCategorizer().categorize("BRITISH GAS PAYMENT") == "utilities"

    def test_octopus_energy(self):
        assert RuleBasedCategorizer().categorize("OCTOPUS ENERGY DD") == "utilities"

    def test_broadband(self):
        assert RuleBasedCategorizer().categorize("BROADBAND MONTHLY BILL") == "utilities"

    def test_vodafone(self):
        assert RuleBasedCategorizer().categorize("VODAFONE LIMITED") == "utilities"


class TestRuleBasedCategorizerHealthcare:
    def test_nhs(self):
        assert RuleBasedCategorizer().categorize("NHS PRESCRIPTION") == "healthcare"

    def test_pharmacy(self):
        assert RuleBasedCategorizer().categorize("BOOTS PHARMACY 0391") == "healthcare"

    def test_gym(self):
        assert RuleBasedCategorizer().categorize("PURE GYM MEMBERSHIP") == "healthcare"

    def test_dentist(self):
        assert RuleBasedCategorizer().categorize("SMILE DENTIST PRACTICE") == "healthcare"


class TestRuleBasedCategorizerShopping:
    def test_amazon(self):
        assert RuleBasedCategorizer().categorize("AMAZON.CO.UK") == "shopping"

    def test_ikea(self):
        assert RuleBasedCategorizer().categorize("IKEA UK LIMITED") == "shopping"

    def test_asos(self):
        assert RuleBasedCategorizer().categorize("ASOS.COM ORDER") == "shopping"

    def test_ebay(self):
        assert RuleBasedCategorizer().categorize("EBAY MARKETPLACE GB") == "shopping"


class TestRuleBasedCategorizerIncome:
    def test_salary(self):
        assert RuleBasedCategorizer().categorize("SALARY JUNE 2024") == "income"

    def test_wages(self):
        assert RuleBasedCategorizer().categorize("WAGES PAYMENT BACS") == "income"

    def test_hmrc(self):
        assert RuleBasedCategorizer().categorize("HMRC TAX REFUND") == "income"

    def test_dividend(self):
        assert RuleBasedCategorizer().categorize("DIVIDEND PAYMENT Q1") == "income"


class TestRuleBasedCategorizerFallback:
    def test_unknown_description(self):
        assert RuleBasedCategorizer().categorize("MISC PAYMENT REF 9999") == "uncategorized"

    def test_empty_description(self):
        assert RuleBasedCategorizer().categorize("") == "uncategorized"

    def test_whitespace_description(self):
        assert RuleBasedCategorizer().categorize("   ") == "uncategorized"

    def test_amount_ignored(self):
        # amount parameter is accepted but does not affect rule-based result
        assert RuleBasedCategorizer().categorize("TESCO EXTRA", amount=50.0) == "food"


# ---------------------------------------------------------------------------
# Priority ordering: first match wins
# ---------------------------------------------------------------------------


class TestRuleBasedCategorizerPriority:
    def test_income_before_shopping(self):
        # "salary" is listed under income which comes before shopping
        assert RuleBasedCategorizer().categorize("SALARY AMAZON BONUS") == "income"

    def test_healthcare_before_shopping_for_pharmacy(self):
        # "pharmacy" keyword is in healthcare; ensure it matches before shopping
        assert RuleBasedCategorizer().categorize("LLOYDS PHARMACY") == "healthcare"


# ---------------------------------------------------------------------------
# Custom rule set
# ---------------------------------------------------------------------------


class TestRuleBasedCategorizerCustomRules:
    def test_custom_rules_override_defaults(self):
        custom = RuleBasedCategorizer(rules=[("travel", ["ryanair", "hotel"])])
        assert custom.categorize("RYANAIR BOOKING") == "travel"

    def test_custom_rules_fallback(self):
        custom = RuleBasedCategorizer(rules=[("travel", ["ryanair"])])
        # "tesco" is not in the custom rule set → uncategorized
        assert custom.categorize("TESCO EXTRA") == "uncategorized"


# ---------------------------------------------------------------------------
# TransactionCategorizer – facade / strategy pattern
# ---------------------------------------------------------------------------


class TestTransactionCategorizerDefaults:
    def test_default_strategy_is_rule_based(self):
        tc = TransactionCategorizer()
        assert tc.categorize("NETFLIX SUBSCRIPTION") == "entertainment"

    def test_uncategorized_fallback(self):
        tc = TransactionCategorizer()
        assert tc.categorize("UNKNOWN VENDOR XYZ") == "uncategorized"


class TestTransactionCategorizerCustomStrategy:
    def test_custom_strategy_is_used(self):
        class ConstantCategorizer(BaseCategorizer):
            def categorize(self, description: str, amount: float | None = None) -> str:
                return "always_this"

        tc = TransactionCategorizer(strategy=ConstantCategorizer())
        assert tc.categorize("TESCO STORES") == "always_this"
        assert tc.categorize("AMAZON.CO.UK") == "always_this"

    def test_strategy_receives_amount(self):
        received: list = []

        class CapturingCategorizer(BaseCategorizer):
            def categorize(self, description: str, amount: float | None = None) -> str:
                received.append((description, amount))
                return "captured"

        tc = TransactionCategorizer(strategy=CapturingCategorizer())
        tc.categorize("SALARY PAYMENT", amount=3000.0)
        assert received == [("SALARY PAYMENT", 3000.0)]


# ---------------------------------------------------------------------------
# BaseCategorizer is abstract
# ---------------------------------------------------------------------------


class TestBaseCategorizerIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseCategorizer()  # type: ignore[abstract]

    def test_subclass_must_implement_categorize(self):
        class Incomplete(BaseCategorizer):
            pass  # missing categorize()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]
