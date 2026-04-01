from sqlalchemy import Column, Date, Integer, Numeric, String
from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    category = Column(String, nullable=False)
