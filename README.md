# SpendInsight

A FastAPI backend for tracking personal spending and financial transactions.

## Tech Stack

- **FastAPI** – modern, fast Python web framework
- **SQLAlchemy** – ORM with SQLite database
- **Pydantic v2** – data validation and serialisation
- **Uvicorn** – ASGI server

## Project Structure

```
app/
├── main.py          # FastAPI application entry point
├── database.py      # SQLAlchemy engine, session and base
├── models/
│   └── transaction.py   # SQLAlchemy Transaction model
├── schemas/
│   └── transaction.py   # Pydantic schemas
├── crud/
│   └── transaction.py   # CRUD helper functions
└── routers/
    └── transactions.py  # API route handlers
tests/
└── test_transactions.py
```

## Getting Started

Python version: 3.14

```bash
py -3.14 -m venv .venv
./.venv/Scripts/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Interactive API docs are available at `http://localhost:8000/docs`.

## API Endpoints

| Method | Path                        | Description              |
|--------|-----------------------------|--------------------------|
| GET    | `/`                         | Health check             |
| GET    | `/transactions/`            | List all transactions    |
| POST   | `/transactions/`            | Create a transaction     |
| GET    | `/transactions/{id}`        | Get a transaction by ID  |
| PUT    | `/transactions/{id}`        | Update a transaction     |
| DELETE | `/transactions/{id}`        | Delete a transaction     |

## Transaction Fields

| Field         | Type   | Description                        |
|---------------|--------|------------------------------------|
| `date`        | date   | Transaction date (YYYY-MM-DD)      |
| `description` | string | Short description of the expense   |
| `amount`      | float  | Transaction amount                 |
| `type`        | string | `income` or `expense`              |
| `source`      | string | Payment source (e.g. credit_card)  |
| `category`    | string | Category (e.g. food, transport)    |

## Running Tests

```bash
pytest tests/ -v
```
