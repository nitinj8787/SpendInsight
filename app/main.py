from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import analytics, transactions, upload

Base.metadata.create_all(bind=engine)

app = FastAPI(title="SpendInsight", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(upload.router)
app.include_router(analytics.router)


@app.get("/")
def root():
    return {"message": "Welcome to SpendInsight API"}
