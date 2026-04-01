from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.transaction import Transaction


def get_analytics(db: Session) -> dict:
    total_income: Decimal = (
        db.query(func.sum(Transaction.amount))
        .filter(Transaction.type == "income")
        .scalar()
        or Decimal("0.00")
    )

    total_expenses: Decimal = (
        db.query(func.sum(Transaction.amount))
        .filter(Transaction.type == "expense")
        .scalar()
        or Decimal("0.00")
    )

    savings: Decimal = total_income - total_expenses

    category_rows = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .group_by(Transaction.category)
        .order_by(Transaction.category)
        .all()
    )
    category_breakdown = [
        {"category": row.category, "total": row.total} for row in category_rows
    ]

    # func.strftime is SQLite-specific; this service targets SQLite exclusively.
    monthly_rows = (
        db.query(
            func.strftime("%Y-%m", Transaction.date).label("month"),
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
        )
        .group_by("month", Transaction.type)
        .order_by("month")
        .all()
    )

    monthly_data: dict[str, dict] = {}
    for row in monthly_rows:
        month = row.month
        if month not in monthly_data:
            monthly_data[month] = {
                "month": month,
                "income": Decimal("0.00"),
                "expenses": Decimal("0.00"),
            }
        if row.type == "income":
            monthly_data[month]["income"] = row.total
        elif row.type == "expense":
            monthly_data[month]["expenses"] = row.total

    monthly_trends = sorted(monthly_data.values(), key=lambda x: x["month"])

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "savings": savings,
        "category_breakdown": category_breakdown,
        "monthly_trends": monthly_trends,
    }
