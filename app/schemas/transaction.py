import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class TransactionBase(BaseModel):
    date: datetime.date
    description: str
    amount: Decimal
    type: str
    source: str
    category: str


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    date: Optional[datetime.date] = None
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    type: Optional[str] = None
    source: Optional[str] = None
    category: Optional[str] = None


class TransactionResponse(TransactionBase):
    id: int

    model_config = {"from_attributes": True}
