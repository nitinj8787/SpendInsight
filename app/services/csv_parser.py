import csv
import datetime
import io
from decimal import Decimal, InvalidOperation

from app.schemas.transaction import TransactionCreate


def parse_csv(content: bytes) -> list[TransactionCreate]:
    """Parse CSV file content into a list of TransactionCreate objects.

    The CSV must contain headers: date, description, amount, type, source, category.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV file must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(text))

    required_fields = {"date", "description", "amount", "type", "source", "category"}
    fieldnames = set(reader.fieldnames or [])
    missing = required_fields - fieldnames
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")

    transactions: list[TransactionCreate] = []
    for line_num, row in enumerate(reader, start=2):
        try:
            transactions.append(
                TransactionCreate(
                    date=datetime.date.fromisoformat(row["date"].strip()),
                    description=row["description"].strip(),
                    amount=Decimal(row["amount"].strip().replace(",", "")),
                    type=row["type"].strip(),
                    source=row["source"].strip(),
                    category=row["category"].strip(),
                )
            )
        except (ValueError, InvalidOperation, KeyError) as exc:
            raise ValueError(f"Invalid data on CSV row {line_num}: {exc}") from exc

    return transactions
