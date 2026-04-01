"""Post-processing service for parsed transactions.

The :class:`TransactionPostProcessor` applies a pipeline of normalisation
steps to a list of raw :class:`~app.schemas.transaction.TransactionCreate`
objects produced by any PDF or CSV parser:

1. **Amount normalisation** — amounts are always stored as positive values;
   the sign is moved into the ``type`` field.
2. **Type inference** — ``type`` is set to ``"income"`` or ``"expense"``
   based on the amount sign when the raw value was not already set.
3. **Categorisation** — uses the :class:`~app.services.categorizer.TransactionCategorizer`
   rule-based strategy (or a custom callable) to fill in ``category`` when it
   is ``"uncategorized"`` or empty.
4. **Internal transfer detection** — pairs of transactions that share the
   same (absolute) amount and fall within a configurable time window are
   flagged as ``"transfer"`` category, since they likely represent a debit
   from one account and the corresponding credit to another.

The class is designed to be extensible: pass a custom *categorize_fn* to
plug in an AI-powered categorizer without subclassing.

Usage::

    from app.services.pdf.postprocessor import TransactionPostProcessor

    processor = TransactionPostProcessor()
    cleaned = processor.process(raw_transactions)

    # With a custom AI categorizer:
    processor = TransactionPostProcessor(
        categorize_fn=my_llm_categorizer,
        transfer_window_days=2,
    )
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import Callable

from app.schemas.transaction import TransactionCreate
from app.services.categorizer import TransactionCategorizer

logger = logging.getLogger(__name__)

_default_categorizer = TransactionCategorizer()


class TransactionPostProcessor:
    """Pipeline that normalises, categorises, and flags parsed transactions.

    Parameters
    ----------
    categorize_fn:
        Optional callable ``(description: str) -> str`` to use for
        categorisation.  Defaults to the built-in rule-based categorizer.
    transfer_window_days:
        Maximum number of days between two matching transactions for them to
        be considered an internal transfer.  Set to ``0`` to disable transfer
        detection entirely.  Defaults to ``2``.
    transfer_amount_tolerance:
        Maximum absolute difference (as a :class:`~decimal.Decimal`) between
        two amounts for them to be considered matching.  Defaults to ``0``
        (exact match).
    """

    def __init__(
        self,
        categorize_fn: Callable[[str], str] | None = None,
        transfer_window_days: int = 2,
        transfer_amount_tolerance: Decimal = Decimal("0"),
    ) -> None:
        self._categorize = categorize_fn or _default_categorizer.categorize
        self._transfer_window = datetime.timedelta(days=transfer_window_days)
        self._transfer_tolerance = transfer_amount_tolerance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(
        self, transactions: list[TransactionCreate]
    ) -> list[TransactionCreate]:
        """Apply the full post-processing pipeline to *transactions*.

        Steps applied in order:
        1. Normalise amounts and infer type.
        2. Categorise each transaction.
        3. Detect and mark internal transfers.

        Parameters
        ----------
        transactions:
            Raw list from a parser.  Mutated in-place and returned.

        Returns
        -------
        list[TransactionCreate]
            The same list, with fields updated.
        """
        logger.debug("TransactionPostProcessor.process(): %d transactions", len(transactions))
        normalised = [self._normalise(t) for t in transactions]
        categorised = [self._categorise(t) for t in normalised]
        result = self._detect_transfers(categorised)
        logger.info("TransactionPostProcessor: processed %d transactions", len(result))
        return result

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    def _normalise(self, txn: TransactionCreate) -> TransactionCreate:
        """Ensure amount is positive and type is inferred from the sign."""
        amount = txn.amount
        txn_type = txn.type

        if amount < 0:
            amount = abs(amount)
            if txn_type not in ("income", "expense"):
                txn_type = "expense"

        if txn_type not in ("income", "expense", "transfer"):
            # Default to "expense" when the type value is unrecognised.
            txn_type = "expense"

        return TransactionCreate(
            date=txn.date,
            description=txn.description,
            amount=amount,
            type=txn_type,
            source=txn.source,
            category=txn.category,
        )

    def _categorise(self, txn: TransactionCreate) -> TransactionCreate:
        """Fill in category when it is missing or ``"uncategorized"``."""
        if txn.category and txn.category != "uncategorized":
            return txn
        try:
            category = self._categorize(txn.description)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TransactionPostProcessor: categorizer raised %s", exc)
            category = "uncategorized"

        return TransactionCreate(
            date=txn.date,
            description=txn.description,
            amount=txn.amount,
            type=txn.type,
            source=txn.source,
            category=category,
        )

    def _detect_transfers(
        self, transactions: list[TransactionCreate]
    ) -> list[TransactionCreate]:
        """Mark paired transactions as ``"transfer"`` when applicable.

        A pair is detected when:
        * The absolute difference between their amounts is within
          :attr:`_transfer_tolerance`.
        * One is of type ``"income"`` and the other is ``"expense"``.
        * Their dates are within :attr:`_transfer_window` of each other.

        Both transactions in a detected pair are marked with
        ``category="transfer"``.

        Parameters
        ----------
        transactions:
            List of normalised, categorised transactions.

        Returns
        -------
        list[TransactionCreate]
            Same list with transfer pairs updated.
        """
        if self._transfer_window.days == 0:
            return transactions

        # Work on mutable copies so we can update category
        result: list[TransactionCreate] = list(transactions)
        n = len(result)
        matched: set[int] = set()

        for i in range(n):
            if i in matched:
                continue
            for j in range(i + 1, n):
                if j in matched:
                    continue
                a, b = result[i], result[j]
                # Must be opposite types
                if a.type == b.type:
                    continue
                # Amounts must be within tolerance
                if abs(a.amount - b.amount) > self._transfer_tolerance:
                    continue
                # Dates must be within window
                date_diff = abs(a.date - b.date)
                if date_diff > self._transfer_window:
                    continue
                # Mark both as transfers
                logger.debug(
                    "TransactionPostProcessor: transfer pair detected: %r <-> %r",
                    a.description,
                    b.description,
                )
                result[i] = TransactionCreate(
                    date=a.date, description=a.description, amount=a.amount,
                    type=a.type, source=a.source, category="transfer",
                )
                result[j] = TransactionCreate(
                    date=b.date, description=b.description, amount=b.amount,
                    type=b.type, source=b.source, category="transfer",
                )
                matched.add(i)
                matched.add(j)
                break  # each transaction can only be matched once

        return result
