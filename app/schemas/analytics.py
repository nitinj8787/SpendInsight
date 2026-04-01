from decimal import Decimal

from pydantic import BaseModel


class CategoryBreakdown(BaseModel):
    category: str
    total: Decimal


class MonthlyTrend(BaseModel):
    month: str
    income: Decimal
    expenses: Decimal


class AnalyticsResponse(BaseModel):
    total_income: Decimal
    total_expenses: Decimal
    savings: Decimal
    category_breakdown: list[CategoryBreakdown]
    monthly_trends: list[MonthlyTrend]
