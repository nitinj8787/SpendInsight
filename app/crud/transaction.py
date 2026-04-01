from typing import Optional

from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.schemas.transaction import TransactionCreate, TransactionUpdate


def get_transaction(db: Session, transaction_id: int) -> Optional[Transaction]:
    return db.query(Transaction).filter(Transaction.id == transaction_id).first()


def get_transactions(db: Session, skip: int = 0, limit: int = 100) -> list[Transaction]:
    return db.query(Transaction).offset(skip).limit(limit).all()


def create_transaction(db: Session, transaction: TransactionCreate) -> Transaction:
    db_transaction = Transaction(**transaction.model_dump())
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def update_transaction(
    db: Session, transaction_id: int, transaction: TransactionUpdate
) -> Optional[Transaction]:
    db_transaction = get_transaction(db, transaction_id)
    if db_transaction is None:
        return None
    update_data = transaction.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_transaction, field, value)
    db.commit()
    db.refresh(db_transaction)
    return db_transaction


def delete_transaction(db: Session, transaction_id: int) -> Optional[Transaction]:
    db_transaction = get_transaction(db, transaction_id)
    if db_transaction is None:
        return None
    db.delete(db_transaction)
    db.commit()
    return db_transaction


def delete_all_transactions(db: Session) -> int:
    """Delete every transaction row and return the count of deleted records."""
    count = db.query(Transaction).count()
    db.query(Transaction).delete()
    db.commit()
    return count
