from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas.transaction import TransactionCreate, TransactionResponse, TransactionUpdate

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=list[TransactionResponse])
def list_transactions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.transaction.get_transactions(db, skip=skip, limit=limit)


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(transaction: TransactionCreate, db: Session = Depends(get_db)):
    return crud.transaction.create_transaction(db, transaction)


@router.delete("/", status_code=status.HTTP_200_OK)
def delete_all_transactions(db: Session = Depends(get_db)):
    """Delete every transaction.  Returns the number of deleted records."""
    count = crud.transaction.delete_all_transactions(db)
    return {"deleted": count}


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: int, db: Session = Depends(get_db)):
    db_transaction = crud.transaction.get_transaction(db, transaction_id)
    if db_transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return db_transaction


@router.put("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: int, transaction: TransactionUpdate, db: Session = Depends(get_db)
):
    db_transaction = crud.transaction.update_transaction(db, transaction_id, transaction)
    if db_transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return db_transaction


@router.delete("/{transaction_id}", response_model=TransactionResponse)
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    db_transaction = crud.transaction.delete_transaction(db, transaction_id)
    if db_transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return db_transaction
