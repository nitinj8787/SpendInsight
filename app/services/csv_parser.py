import datetime
import io
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd

from app.schemas.transaction import TransactionCreate

# ---------------------------------------------------------------------------
# Bank format definitions
# ---------------------------------------------------------------------------

# Each bank has a set of column names whose presence uniquely identifies it.
_BANK_SIGNATURES: dict[str, set[str]] = {
    "barclays": {"Memo"},
    "monzo": {"Transaction ID"},
    "amex": {"Reference"},
    "transferwise": {"TransferWise ID"},
}

# Maps bank-specific column names to the standard internal names.
_COLUMN_MAPS: dict[str, dict[str, str]] = {
    "barclays": {
        "Date": "date",
        "Memo": "description",
        "Amount": "amount",
    },
    "monzo": {
        "Date": "date",
        "Name": "description",
        "Amount": "amount",
        "Category": "category",
    },
    "amex": {
        "Date": "date",
        "Description": "description",
        "Amount": "amount",
    },
    "transferwise": {
        "Date": "date",
        "Description": "description",
        "Amount": "amount",
    },
}

# Date format strings to try (in order) for each bank format.
_DATE_FORMATS: dict[str, list[str]] = {
    "barclays": ["%d/%m/%Y"],
    "monzo": ["%Y-%m-%d", "%d/%m/%Y"],
    "amex": ["%d/%m/%Y", "%d %b %Y", "%m/%d/%y"],
    "transferwise": ["%Y-%m-%d"],
}

# Default value for the ``source`` field when the CSV does not supply one.
_SOURCES: dict[str, str] = {
    "barclays": "barclays",
    "monzo": "monzo",
    "amex": "amex",
    "transferwise": "transferwise",
}

# Columns required by the generic (non-bank-specific) format.
_GENERIC_REQUIRED = {"date", "description", "amount", "type", "source", "category"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_bank(columns: list[str]) -> Optional[str]:
    """Return the bank name whose signature columns are all present, or *None*."""
    col_set = set(columns)
    for bank, signature in _BANK_SIGNATURES.items():
        if signature.issubset(col_set):
            return bank
    return None


def _parse_date(value: str, bank: Optional[str]) -> datetime.date:
    """Parse *value* as a date, trying bank-specific formats before generic ones."""
    formats: list[str] = list(_DATE_FORMATS.get(bank or "", []))
    for generic in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        if generic not in formats:
            formats.append(generic)
    for fmt in formats:
        try:
            return datetime.datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date '{value}'")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_csv(content: bytes) -> list[TransactionCreate]:
    """Parse CSV bytes into a list of :class:`~app.schemas.transaction.TransactionCreate`.

    The function auto-detects the bank format by inspecting the header row and
    normalises column names accordingly.  Supported bank formats:

    * **Barclays** – columns ``Date``, ``Memo``, ``Amount``
    * **Monzo** – columns ``Transaction ID``, ``Date``, ``Name``, ``Amount``, ``Category``
    * **Amex** – columns ``Date``, ``Reference``, ``Description``, ``Amount``
    * **TransferWise** – columns ``TransferWise ID``, ``Date``, ``Description``, ``Amount``

    If none of the above signatures are detected the CSV is treated as a
    *generic* format that must contain all six standard columns:
    ``date``, ``description``, ``amount``, ``type``, ``source``, ``category``.

    For bank formats the ``type`` field is inferred from the sign of *amount*
    (negative → ``"expense"``, non-negative → ``"income"``), ``source`` defaults
    to the bank name, and ``category`` defaults to ``"uncategorized"`` unless the
    CSV already provides it (e.g. Monzo's ``Category`` column).
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV file must be UTF-8 encoded.") from exc

    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as exc:
        raise ValueError(f"Failed to parse CSV: {exc}") from exc

    # Strip surrounding whitespace from column names.
    df.columns = [c.strip() for c in df.columns]

    bank = _detect_bank(list(df.columns))

    if bank is not None:
        df = df.rename(columns=_COLUMN_MAPS[bank])
    else:
        missing = _GENERIC_REQUIRED - set(df.columns)
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}"
            )

    transactions: list[TransactionCreate] = []
    records: list[dict] = df.to_dict("records")

    for row_idx, row in enumerate(records, start=2):
        try:
            date_val = _parse_date(str(row["date"]).strip(), bank)

            amount_str = str(row["amount"]).strip().replace(",", "")
            try:
                amount = Decimal(amount_str)
            except InvalidOperation as exc:
                raise ValueError(f"Invalid amount '{row['amount']}'") from exc

            # Infer transaction type from amount sign for bank formats; use the
            # explicit column value for the generic format.
            raw_type = str(row.get("type", "")).strip()
            if raw_type:
                txn_type = raw_type
            else:
                txn_type = "expense" if amount < 0 else "income"

            # Bank-format amounts are stored as absolute values so that the
            # sign information is captured solely by the ``type`` field.
            if bank is not None:
                amount = abs(amount)

            raw_source = str(row.get("source", "")).strip()
            if raw_source:
                source = raw_source
            elif bank is not None:
                source = _SOURCES.get(bank, "unknown")
            else:
                # Generic format: the source column is required; preserve the
                # supplied value even if empty (validation is the caller's job).
                source = raw_source

            raw_category = str(row.get("category", "")).strip()
            category = raw_category if raw_category else "uncategorized"

            transactions.append(
                TransactionCreate(
                    date=date_val,
                    description=str(row["description"]).strip(),
                    amount=amount,
                    type=txn_type,
                    source=source,
                    category=category,
                )
            )
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f"Invalid data on CSV row {row_idx}: {exc}") from exc

    return transactions

