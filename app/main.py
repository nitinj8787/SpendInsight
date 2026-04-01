from fastapi import FastAPI

from app.database import Base, engine
from app.routers import transactions, upload

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SpendInsight", version="1.0.0")

app.include_router(transactions.router)
app.include_router(upload.router)


@app.get("/")
def root():
    return {"message": "Welcome to SpendInsight API"}
