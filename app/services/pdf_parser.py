import datetime
import io
from decimal import Decimal, InvalidOperation

import pdfplumber

from app.schemas.transaction import TransactionCreate

_HEADER_KEYWORDS = {"date", "description", "amount", "type", "source", "category"}


def _is_header_row(row: list) -> bool:
    """Return True if a table row looks like a column-header row."""
    return bool(row and any(str(cell).strip().lower() in _HEADER_KEYWORDS for cell in row))


def _parse_row(row: list) -> TransactionCreate:
    """Convert a six-element table row into a TransactionCreate."""
    date_str, description, amount_str, t_type, source, category = (
        str(cell).strip() for cell in row[:6]
    )
    return TransactionCreate(
        date=datetime.date.fromisoformat(date_str),
        description=description,
        amount=Decimal(amount_str.replace(",", "")),
        type=t_type,
        source=source,
        category=category,
    )


def parse_pdf(content: bytes) -> list[TransactionCreate]:
    """Parse PDF file content into a list of TransactionCreate objects.

    Expects the PDF to contain tables with columns:
    date, description, amount, type, source, category (in that order).
    """
    transactions: list[TransactionCreate] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables()
            for table in tables:
                for row_num, row in enumerate(table):
                    if not row or len(row) < 6:
                        continue
                    if _is_header_row(row):
                        continue
                    try:
                        transactions.append(_parse_row(row))
                    except (ValueError, InvalidOperation) as exc:
                        raise ValueError(
                            f"Invalid data in PDF page {page_num}, row {row_num + 1}: {exc}"
                        ) from exc

    return transactions
