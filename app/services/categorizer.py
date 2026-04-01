"""Transaction categorization service.

Provides a rule-based keyword-matching categorizer and an abstract base class
that makes the service extensible for future AI-powered implementations.

Usage::

    from app.services.categorizer import TransactionCategorizer

    categorizer = TransactionCategorizer()
    category = categorizer.categorize("TESCO STORES 2854")  # → "food"

To plug in a custom strategy (e.g. an AI model)::

    class MyAICategorizer(BaseCategorizer):
        def categorize(self, description: str, amount: float | None = None) -> str:
            ...  # call AI model

    categorizer = TransactionCategorizer(strategy=MyAICategorizer())
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseCategorizer(ABC):
    """Abstract base for all categorization strategies.

    Subclass this to add alternative implementations (e.g. ML/AI models)
    without changing any call sites.
    """

    @abstractmethod
    def categorize(self, description: str, amount: float | None = None) -> str:
        """Return a category string for the given transaction.

        Parameters
        ----------
        description:
            The transaction description / merchant name as it appears in the
            bank statement.
        amount:
            Optional monetary amount (absolute value).  May be used by
            strategies that need it (e.g. to separate salary from small
            deposits).

        Returns
        -------
        str
            A non-empty category string.  Returns ``"uncategorized"`` when no
            rule matches.
        """


# ---------------------------------------------------------------------------
# Rule-based implementation
# ---------------------------------------------------------------------------

# Each entry is (category_name, [keyword, ...]).
# Entries are evaluated in order; the first match wins.  Place more-specific
# or higher-priority categories earlier in the list.
_RULES: list[tuple[str, list[str]]] = [
    (
        "income",
        [
            "salary",
            "wages",
            "payroll",
            "hmrc",
            "tax rebate",
            "tax refund",
            "cashback",
            "interest payment",
            "dividend",
            "bacs credit",
            "faster payment received",
        ],
    ),
    (
        "food",
        [
            "tesco",
            "sainsbury",
            "asda",
            "waitrose",
            "morrisons",
            "lidl",
            "aldi",
            "co-op",
            "coop",
            "pizza",
            "mcdonalds",
            "mcdonald",
            "kfc",
            "burger king",
            "subway",
            "nando",
            "starbucks",
            "costa coffee",
            "greggs",
            "pret",
            "deliveroo",
            "just eat",
            "uber eats",
            "ubereats",
            "restaurant",
            "cafe",
            "bakery",
            "supermarket",
            "domino",
            "sushi",
            "takeaway",
        ],
    ),
    (
        "transport",
        [
            "uber",
            "lyft",
            "taxi",
            "tfl",
            "transport for london",
            "national rail",
            "thameslink",
            "avanti",
            "southeastern",
            "airport",
            "parking",
            "petrol",
            "fuel",
            "shell",
            "esso",
            "easyjet",
            "ryanair",
            "british airways",
            "jet2",
            "tube",
            "bus",
            "coach",
            "trainline",
            "rail",
        ],
    ),
    (
        "entertainment",
        [
            "netflix",
            "spotify",
            "amazon prime",
            "disney",
            "sky tv",
            "apple music",
            "apple tv",
            "cinema",
            "odeon",
            "vue",
            "cineworld",
            "ticketmaster",
            "eventbrite",
            "steam",
            "playstation",
            "xbox",
            "gaming",
            "audible",
            "youtube premium",
            "twitch",
        ],
    ),
    (
        "utilities",
        [
            "british gas",
            "octopus energy",
            "eon energy",
            "edf energy",
            "bulb energy",
            "thames water",
            "bt broadband",
            "virgin media",
            "vodafone",
            "talktalk",
            "electricity",
            "water bill",
            "broadband",
            "phone bill",
        ],
    ),
    (
        "healthcare",
        [
            "nhs",
            "pharmacy",
            "dentist",
            "doctor",
            "hospital",
            "pure gym",
            "david lloyd",
            "anytime fitness",
            "virgin active",
            "the gym",
            "fitness",
            "gym",
        ],
    ),
    (
        "shopping",
        [
            "amazon",
            "ebay",
            "argos",
            "currys",
            "john lewis",
            "marks & spencer",
            "h&m",
            "zara",
            "primark",
            "asos",
            "next",
            "tkmaxx",
            "tk maxx",
            "ikea",
            "superdrug",
            "topshop",
            "river island",
            "new look",
            "jd sports",
            "sports direct",
        ],
    ),
]


class RuleBasedCategorizer(BaseCategorizer):
    """Categorizes transactions via keyword matching against a fixed rule set.

    Each rule maps a category name to a list of lowercase keywords.  The first
    category whose keyword list contains a match (substring search, case-
    insensitive) is returned.  Falls back to ``"uncategorized"`` when no rule
    matches.

    Parameters
    ----------
    rules:
        Optional replacement rule set.  Each element is a
        ``(category, [keyword, ...])`` tuple.  Defaults to the built-in
        :data:`_RULES` list when not provided.
    """

    def __init__(
        self, rules: list[tuple[str, list[str]]] | None = None
    ) -> None:
        self._rules: list[tuple[str, list[str]]] = rules if rules is not None else _RULES
        # Pre-compile word-boundary patterns for efficiency.
        self._compiled: list[tuple[str, list[re.Pattern[str]]]] = [
            (
                category,
                [
                    re.compile(r"\b" + re.escape(kw) + r"\b")
                    for kw in keywords
                ],
            )
            for category, keywords in self._rules
        ]

    def categorize(self, description: str, amount: float | None = None) -> str:
        """Return the first matching category for *description*.

        Matching is case-insensitive and uses whole-word boundaries so that
        short keywords (e.g. ``"tfl"``) do not match inside longer words.

        Parameters
        ----------
        description:
            Raw transaction description string.
        amount:
            Ignored by this implementation; kept for interface compatibility.

        Returns
        -------
        str
            Matched category name, or ``"uncategorized"``.
        """
        desc_lower = description.lower()
        for category, patterns in self._compiled:
            if any(pattern.search(desc_lower) for pattern in patterns):
                return category
        return "uncategorized"


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


class TransactionCategorizer:
    """High-level facade that delegates to a :class:`BaseCategorizer` strategy.

    By default a :class:`RuleBasedCategorizer` is used.  Pass a different
    *strategy* to switch implementations without modifying call sites::

        categorizer = TransactionCategorizer(strategy=MyAICategorizer())

    Parameters
    ----------
    strategy:
        The categorization strategy to use.  Defaults to a
        :class:`RuleBasedCategorizer` instance.
    """

    def __init__(self, strategy: BaseCategorizer | None = None) -> None:
        self._strategy: BaseCategorizer = strategy or RuleBasedCategorizer()

    def categorize(self, description: str, amount: float | None = None) -> str:
        """Categorize a transaction description.

        Parameters
        ----------
        description:
            Transaction description / merchant name.
        amount:
            Optional absolute monetary amount; forwarded to the underlying
            strategy.

        Returns
        -------
        str
            Category string (e.g. ``"food"``, ``"transport"``), or
            ``"uncategorized"`` if no rule matches.
        """
        return self._strategy.categorize(description, amount)
