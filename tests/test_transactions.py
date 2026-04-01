import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite:///./test_spendinsight.db"

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


SAMPLE_TRANSACTION = {
    "date": "2024-03-15",
    "description": "Grocery shopping",
    "amount": 75.50,
    "type": "expense",
    "source": "credit_card",
    "category": "food",
}


def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to SpendInsight API"}


def test_create_transaction(client):
    response = client.post("/transactions/", json=SAMPLE_TRANSACTION)
    assert response.status_code == 201
    data = response.json()
    assert data["description"] == SAMPLE_TRANSACTION["description"]
    assert float(data["amount"]) == SAMPLE_TRANSACTION["amount"]
    assert data["type"] == SAMPLE_TRANSACTION["type"]
    assert data["source"] == SAMPLE_TRANSACTION["source"]
    assert data["category"] == SAMPLE_TRANSACTION["category"]
    assert "id" in data


def test_list_transactions(client):
    client.post("/transactions/", json=SAMPLE_TRANSACTION)
    client.post("/transactions/", json={**SAMPLE_TRANSACTION, "description": "Second transaction"})
    response = client.get("/transactions/")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_transaction(client):
    create_response = client.post("/transactions/", json=SAMPLE_TRANSACTION)
    transaction_id = create_response.json()["id"]
    response = client.get(f"/transactions/{transaction_id}")
    assert response.status_code == 200
    assert response.json()["id"] == transaction_id


def test_get_transaction_not_found(client):
    response = client.get("/transactions/9999")
    assert response.status_code == 404


def test_update_transaction(client):
    create_response = client.post("/transactions/", json=SAMPLE_TRANSACTION)
    transaction_id = create_response.json()["id"]
    response = client.put(
        f"/transactions/{transaction_id}",
        json={"amount": 99.99, "category": "groceries"},
    )
    assert response.status_code == 200
    data = response.json()
    assert float(data["amount"]) == 99.99
    assert data["category"] == "groceries"
    assert data["description"] == SAMPLE_TRANSACTION["description"]


def test_update_transaction_not_found(client):
    response = client.put("/transactions/9999", json={"amount": 10.0})
    assert response.status_code == 404


def test_delete_transaction(client):
    create_response = client.post("/transactions/", json=SAMPLE_TRANSACTION)
    transaction_id = create_response.json()["id"]
    response = client.delete(f"/transactions/{transaction_id}")
    assert response.status_code == 200
    assert response.json()["id"] == transaction_id
    get_response = client.get(f"/transactions/{transaction_id}")
    assert get_response.status_code == 404


def test_delete_transaction_not_found(client):
    response = client.delete("/transactions/9999")
    assert response.status_code == 404


def test_delete_all_transactions(client):
    client.post("/transactions/", json=SAMPLE_TRANSACTION)
    client.post("/transactions/", json={**SAMPLE_TRANSACTION, "description": "Second transaction"})
    response = client.delete("/transactions/")
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
    list_response = client.get("/transactions/")
    assert list_response.json() == []


def test_delete_all_transactions_empty_db(client):
    response = client.delete("/transactions/")
    assert response.status_code == 200
    assert response.json()["deleted"] == 0
