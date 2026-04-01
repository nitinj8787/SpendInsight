import csv
import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.schemas.transaction import TransactionCreate

TEST_DATABASE_URL = "sqlite:///./test_upload_spendinsight.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_csv(rows: list[dict] | None = None) -> bytes:
    if rows is None:
        rows = [
            {
                "date": "2024-03-15",
                "description": "Grocery shopping",
                "amount": "75.50",
                "type": "expense",
                "source": "credit_card",
                "category": "food",
            }
        ]
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["date", "description", "amount", "type", "source", "category"],
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


SAMPLE_TRANSACTION = TransactionCreate(
    date="2024-03-15",
    description="Grocery shopping",
    amount=Decimal("75.50"),
    type="expense",
    source="credit_card",
    category="food",
)


# ---------------------------------------------------------------------------
# CSV upload tests
# ---------------------------------------------------------------------------


def test_upload_csv_single_row(client):
    response = client.post(
        "/upload/",
        files={"file": ("transactions.csv", _make_csv(), "text/csv")},
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data) == 1
    assert data[0]["description"] == "Grocery shopping"
    assert data[0]["amount"] == "75.50"
    assert data[0]["type"] == "expense"
    assert data[0]["source"] == "credit_card"
    assert data[0]["category"] == "food"
    assert "id" in data[0]


def test_upload_csv_multiple_rows(client):
    rows = [
        {
            "date": "2024-03-15",
            "description": "Grocery",
            "amount": "75.50",
            "type": "expense",
            "source": "credit_card",
            "category": "food",
        },
        {
            "date": "2024-03-16",
            "description": "Gas",
            "amount": "50.00",
            "type": "expense",
            "source": "debit_card",
            "category": "transport",
        },
    ]
    response = client.post(
        "/upload/",
        files={"file": ("transactions.csv", _make_csv(rows), "text/csv")},
    )
    assert response.status_code == 201
    data = response.json()
    assert len(data) == 2
    assert data[0]["description"] == "Grocery"
    assert data[1]["description"] == "Gas"


def test_upload_csv_detected_by_extension(client):
    """File type should be detected via extension when content-type is generic."""
    response = client.post(
        "/upload/",
        files={"file": ("transactions.csv", _make_csv(), "application/octet-stream")},
    )
    assert response.status_code == 201


def test_upload_csv_missing_columns(client):
    bad_csv = b"date,description\n2024-03-15,Test\n"
    response = client.post(
        "/upload/",
        files={"file": ("bad.csv", bad_csv, "text/csv")},
    )
    assert response.status_code == 422


def test_upload_csv_invalid_date(client):
    bad_csv = b"date,description,amount,type,source,category\nnot-a-date,Test,10.00,expense,bank,food\n"
    response = client.post(
        "/upload/",
        files={"file": ("bad.csv", bad_csv, "text/csv")},
    )
    assert response.status_code == 422


def test_upload_csv_invalid_amount(client):
    bad_csv = b"date,description,amount,type,source,category\n2024-03-15,Test,not-a-number,expense,bank,food\n"
    response = client.post(
        "/upload/",
        files={"file": ("bad.csv", bad_csv, "text/csv")},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# PDF upload tests (parser mocked — no PDF generation library available)
# ---------------------------------------------------------------------------


def test_upload_pdf_routes_to_pdf_parser(client):
    """A .pdf file should be routed to parse_pdf and its results saved."""
    with patch("app.routers.upload.parse_pdf", return_value=[SAMPLE_TRANSACTION]) as mock_parse:
        response = client.post(
            "/upload/",
            files={"file": ("statement.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
    assert response.status_code == 201
    mock_parse.assert_called_once()
    data = response.json()
    assert len(data) == 1
    assert data[0]["description"] == "Grocery shopping"


def test_upload_pdf_detected_by_extension(client):
    """PDF type should also be detected via .pdf extension."""
    with patch("app.routers.upload.parse_pdf", return_value=[SAMPLE_TRANSACTION]):
        response = client.post(
            "/upload/",
            files={"file": ("statement.pdf", b"fake", "application/octet-stream")},
        )
    assert response.status_code == 201


def test_upload_pdf_parser_error_returns_422(client):
    with patch("app.routers.upload.parse_pdf", side_effect=ValueError("bad row")):
        response = client.post(
            "/upload/",
            files={"file": ("statement.pdf", b"fake", "application/pdf")},
        )
    assert response.status_code == 422
    assert "bad row" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Unsupported type tests
# ---------------------------------------------------------------------------


def test_upload_unsupported_content_type(client):
    response = client.post(
        "/upload/",
        files={"file": ("notes.txt", b"some text", "text/plain")},
    )
    assert response.status_code == 415


def test_upload_unsupported_extension(client):
    response = client.post(
        "/upload/",
        files={"file": ("data.xlsx", b"fake xlsx bytes", "application/octet-stream")},
    )
    assert response.status_code == 415
