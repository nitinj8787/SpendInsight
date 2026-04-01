import datetime
import io
import re
from decimal import Decimal, InvalidOperation

import pdfplumber

from app.schemas.transaction import TransactionCreate
from app.services.categorizer import TransactionCategorizer

_categorizer = TransactionCategorizer()

# ---------------------------------------------------------------------------
# Regex patterns for field identification
# ---------------------------------------------------------------------------

# Supported date formats with their strptime directives.
# The "DD MMM" pattern (no year) yields year 1900 via strptime; callers
# must substitute the current year when they see year == 1900.
_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d"),
    (re.compile(r"^\d{1,2}/\d{2}/\d{4}$"), "%d/%m/%Y"),
    (re.compile(r"^\d{1,2}-\d{2}-\d{4}$"), "%d-%m-%Y"),
    (re.compile(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$"), "%d %b %Y"),
    (re.compile(r"^\d{1,2}\s+[A-Za-z]{3}$"), "%d %b"),          # e.g. "04 Oct"
]

# Optional leading currency symbol, optional sign, digits with optional
# thousands-commas and up to two decimal places.
_AMOUNT_RE = re.compile(r"^[£$€]?\s*[-+]?\s*[\d,]+(?:\.\d{1,2})?$")

# Column header names that map to each logical field
_HEADER_KEYWORDS = {"date", "description", "amount", "type", "source", "category"}

_DESC_ALIASES = {"description", "memo", "name", "narrative", "details", "payee"}
_AMOUNT_ALIASES = {"amount", "value"}
# Separate debit ("money out") and credit ("money in") column header aliases
_DEBIT_ALIASES = {"debit", "money out", "withdrawal", "paid out", "dr"}
_CREDIT_ALIASES = {"credit", "money in", "deposit", "paid in", "payment in", "cr"}
_SOURCE_ALIASES = {"source", "bank", "account"}

# Description keywords that identify an opening/closing balance row to skip
_BALANCE_ROW_RE = re.compile(
    r"\b(start|opening|closing|end|brought\s+forward|carried\s+forward)\s+balance\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helper: date parsing
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> datetime.date | None:
    """Try to parse *value* as a date using known regex-backed formats.

    Returns a :class:`datetime.date` on success, or ``None`` if no pattern
    matches.  For formats that carry no year (e.g. "04 Oct") the current
    calendar year is substituted.  Note: this heuristic may be inaccurate
    for statements that span a year boundary (e.g. a December transaction
    on a statement fetched in January of the following year).
    """
    value = value.strip()
    for pattern, fmt in _DATE_PATTERNS:
        if pattern.match(value):
            try:
                parsed = datetime.datetime.strptime(value, fmt)
                if parsed.year == 1900:
                    # strptime default when no year present; use current year
                    parsed = parsed.replace(year=datetime.date.today().year)
                return parsed.date()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Helper: amount parsing
# ---------------------------------------------------------------------------


def _parse_amount(value: str) -> Decimal | None:
    """Try to parse *value* as a monetary amount using a regex guard.

    Strips leading currency symbols and thousand-separator commas before
    converting to :class:`~decimal.Decimal`.  Returns ``None`` if *value*
    does not look like an amount.
    """
    value = value.strip()
    if not _AMOUNT_RE.match(value):
        return None
    cleaned = re.sub(r"[£$€\s]", "", value).replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# Helper: column classification
# ---------------------------------------------------------------------------


def _classify_columns(
    header_row: list | None, first_data_row: list
) -> dict[str, int]:
    """Return a mapping of logical field name -> column index.

    When *header_row* is provided its labels are matched against known aliases
    for each field.  If required fields (date, description, plus at least one
    amount-like column) are all found, that mapping is returned directly.

    The supported amount-like column keys are:

    * ``"amount"`` – a single signed-amount column (e.g. "amount", "value")
    * ``"debit"``  – a money-out column (e.g. "debit", "money out")
    * ``"credit"`` – a money-in column (e.g. "credit", "money in")

    Otherwise the first data row is scanned with :func:`_parse_date` and
    :func:`_parse_amount` to infer positions automatically.
    """
    if header_row:
        mapping: dict[str, int] = {}
        for i, cell in enumerate(header_row):
            key = str(cell).strip().lower()
            if key == "date":
                mapping["date"] = i
            elif key in _DESC_ALIASES:
                mapping.setdefault("description", i)
            elif key in _AMOUNT_ALIASES:
                mapping.setdefault("amount", i)
            elif key in _DEBIT_ALIASES:
                mapping.setdefault("debit", i)
            elif key in _CREDIT_ALIASES:
                mapping.setdefault("credit", i)
            elif key == "type":
                mapping["type"] = i
            elif key in _SOURCE_ALIASES:
                mapping.setdefault("source", i)
            elif key == "category":
                mapping["category"] = i
        has_amount = {"amount", "debit", "credit"}.intersection(mapping)
        if {"date", "description"}.issubset(mapping) and has_amount:
            return mapping

    # Fallback: infer positions from the content of the first data row
    mapping = {}
    for i, cell in enumerate(first_data_row):
        cell_str = str(cell).strip()
        if "date" not in mapping and _parse_date(cell_str) is not None:
            mapping["date"] = i
        elif "amount" not in mapping and _parse_amount(cell_str) is not None:
            mapping["amount"] = i
        elif (
            "description" not in mapping
            and cell_str
            and not _AMOUNT_RE.match(cell_str)
        ):
            mapping["description"] = i
    return mapping


# ---------------------------------------------------------------------------
# Helper: row extraction
# ---------------------------------------------------------------------------


def _is_header_row(row: list) -> bool:
    """Return True if a table row looks like a column-header row."""
    return bool(row and any(str(cell).strip().lower() in _HEADER_KEYWORDS for cell in row))


def _is_balance_row(row: list, col_map: dict[str, int]) -> bool:
    """Return True if *row* represents an opening/closing balance entry.

    Such rows (e.g. "Start balance", "Opening balance") carry no money
    movement and should be skipped rather than treated as transactions.
    """
    desc_idx = col_map.get("description")
    if desc_idx is not None and desc_idx < len(row):
        desc = str(row[desc_idx]).strip()
        return bool(_BALANCE_ROW_RE.search(desc))
    return False


def _extract_row(
    row: list,
    col_map: dict[str, int],
    fallback_date: datetime.date | None = None,
) -> TransactionCreate:
    """Build a :class:`TransactionCreate` from *row* using *col_map*.

    *fallback_date* is used when the date cell is empty – typically for
    continuation rows that share a date with the preceding transaction.

    Raises :exc:`ValueError` when a required field cannot be parsed.
    """

    def _get(key: str, default: str = "") -> str:
        idx = col_map.get(key)
        return str(row[idx]).strip() if idx is not None and idx < len(row) else default

    date_str = _get("date")
    parsed_date = _parse_date(date_str)
    if parsed_date is None:
        if not date_str and fallback_date is not None:
            parsed_date = fallback_date
        else:
            raise ValueError(f"Cannot parse date: {date_str!r}")

    description = _get("description")
    if not description:
        raise ValueError("Description is empty")

    # Handle separate debit/credit columns (e.g. "Money out" / "Money in")
    # or fall back to a single amount column.
    if "debit" in col_map or "credit" in col_map:
        explicit_type = _get("type")
        debit_str = _get("debit")
        credit_str = _get("credit")
        debit_amount = _parse_amount(debit_str) if debit_str else None
        credit_amount = _parse_amount(credit_str) if credit_str else None

        if debit_amount is not None and debit_amount:
            parsed_amount = abs(debit_amount)
            txn_type = explicit_type if explicit_type else "expense"
        elif credit_amount is not None and credit_amount:
            parsed_amount = abs(credit_amount)
            txn_type = explicit_type if explicit_type else "income"
        else:
            raise ValueError(
                f"Cannot parse amount from debit: {debit_str!r} or credit: {credit_str!r}"
            )
    else:
        amount_str = _get("amount")
        parsed_amount = _parse_amount(amount_str)
        if parsed_amount is None:
            raise ValueError(f"Cannot parse amount: {amount_str!r}")

        # Honour an explicit type column when present; otherwise infer from the
        # amount sign (negative → expense, positive → income).
        explicit_type = _get("type")
        if explicit_type:
            txn_type = explicit_type
            parsed_amount = abs(parsed_amount)
        elif parsed_amount < 0:
            txn_type = "expense"
            parsed_amount = abs(parsed_amount)
        else:
            txn_type = "income"

    source = _get("source") or "pdf"
    raw_category = _get("category")
    category = raw_category if raw_category else _categorizer.categorize(description)

    return TransactionCreate(
        date=parsed_date,
        description=description,
        amount=parsed_amount,
        type=txn_type,
        source=source,
        category=category,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf(content: bytes) -> list[TransactionCreate]:
    """Parse PDF file content into a list of :class:`TransactionCreate` objects.

    Uses *pdfplumber* to extract tables from every page.  Column positions are
    determined either from a header row (matched against known field-name
    aliases) or inferred automatically via regex patterns for dates and
    amounts.

    Supported column layouts include both a single signed-amount column
    (``amount`` / ``value``) and separate debit/credit columns
    (``debit`` / ``money out`` and ``credit`` / ``money in``).

    Opening/closing balance rows (e.g. "Start balance") are silently skipped.
    Continuation rows that share a date with the preceding transaction may
    have an empty date cell; the date is carried forward automatically.

    Raises :exc:`ValueError` for rows whose required fields cannot be parsed.
    """
    transactions: list[TransactionCreate] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue

                col_map: dict[str, int] | None = None
                header_row: list | None = None
                last_date: datetime.date | None = None

                for row_num, row in enumerate(table):
                    if not row:
                        continue

                    # Detect and consume a header row; reset the column map so
                    # it is rebuilt from the very next data row.
                    if _is_header_row(row):
                        header_row = row
                        col_map = None
                        continue

                    # Build (or rebuild) the column map from the first data row.
                    if col_map is None:
                        col_map = _classify_columns(header_row, row)
                        has_amount = {"amount", "debit", "credit"}.intersection(col_map)
                        if not ({"date", "description"}.issubset(col_map) and has_amount):
                            # Cannot identify all required columns; skip table.
                            break

                    # Skip opening/closing balance rows.
                    if _is_balance_row(row, col_map):
                        continue

                    try:
                        txn = _extract_row(row, col_map, fallback_date=last_date)
                        last_date = txn.date
                        transactions.append(txn)
                    except (ValueError, InvalidOperation) as exc:
                        raise ValueError(
                            f"Invalid data in PDF page {page_num}, row {row_num + 1}: {exc}"
                        ) from exc

    return transactions
