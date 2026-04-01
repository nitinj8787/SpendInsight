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


INCOME_TRANSACTION = {
    "date": "2024-03-15",
    "description": "Monthly salary",
    "amount": 3000.00,
    "type": "income",
    "source": "bank_transfer",
    "category": "income",
}

EXPENSE_FOOD = {
    "date": "2024-03-20",
    "description": "Tesco groceries",
    "amount": 75.50,
    "type": "expense",
    "source": "credit_card",
    "category": "food",
}

EXPENSE_TRANSPORT = {
    "date": "2024-03-22",
    "description": "Uber ride",
    "amount": 15.00,
    "type": "expense",
    "source": "credit_card",
    "category": "transport",
}

INCOME_APRIL = {
    "date": "2024-04-15",
    "description": "April salary",
    "amount": 3200.00,
    "type": "income",
    "source": "bank_transfer",
    "category": "income",
}

EXPENSE_APRIL = {
    "date": "2024-04-18",
    "description": "Netflix",
    "amount": 10.99,
    "type": "expense",
    "source": "credit_card",
    "category": "entertainment",
}


def test_analytics_empty_db(client):
    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()
    assert float(data["total_income"]) == 0.0
    assert float(data["total_expenses"]) == 0.0
    assert float(data["savings"]) == 0.0
    assert data["category_breakdown"] == []
    assert data["monthly_trends"] == []


def test_analytics_total_income_and_expenses(client):
    client.post("/transactions/", json=INCOME_TRANSACTION)
    client.post("/transactions/", json=EXPENSE_FOOD)
    client.post("/transactions/", json=EXPENSE_TRANSPORT)

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()
    assert float(data["total_income"]) == 3000.00
    assert float(data["total_expenses"]) == pytest.approx(90.50, rel=1e-4)
    assert float(data["savings"]) == pytest.approx(2909.50, rel=1e-4)


def test_analytics_savings_negative_when_expenses_exceed_income(client):
    client.post("/transactions/", json={**INCOME_TRANSACTION, "amount": 50.00})
    client.post("/transactions/", json=EXPENSE_FOOD)

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()
    assert float(data["savings"]) == pytest.approx(-25.50, rel=1e-4)


def test_analytics_category_breakdown(client):
    client.post("/transactions/", json=INCOME_TRANSACTION)
    client.post("/transactions/", json=EXPENSE_FOOD)
    client.post("/transactions/", json=EXPENSE_TRANSPORT)
    client.post("/transactions/", json={**EXPENSE_FOOD, "amount": 24.50})

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()

    breakdown = {item["category"]: float(item["total"]) for item in data["category_breakdown"]}
    assert breakdown["food"] == pytest.approx(100.00, rel=1e-4)
    assert breakdown["transport"] == pytest.approx(15.00, rel=1e-4)
    assert breakdown["income"] == pytest.approx(3000.00, rel=1e-4)


def test_analytics_monthly_trends(client):
    client.post("/transactions/", json=INCOME_TRANSACTION)
    client.post("/transactions/", json=EXPENSE_FOOD)
    client.post("/transactions/", json=INCOME_APRIL)
    client.post("/transactions/", json=EXPENSE_APRIL)

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()

    trends = {item["month"]: item for item in data["monthly_trends"]}
    assert "2024-03" in trends
    assert "2024-04" in trends

    assert float(trends["2024-03"]["income"]) == pytest.approx(3000.00, rel=1e-4)
    assert float(trends["2024-03"]["expenses"]) == pytest.approx(75.50, rel=1e-4)
    assert float(trends["2024-04"]["income"]) == pytest.approx(3200.00, rel=1e-4)
    assert float(trends["2024-04"]["expenses"]) == pytest.approx(10.99, rel=1e-4)


def test_analytics_monthly_trends_ordered(client):
    client.post("/transactions/", json=INCOME_APRIL)
    client.post("/transactions/", json=INCOME_TRANSACTION)

    response = client.get("/analytics/")
    assert response.status_code == 200
    months = [item["month"] for item in response.json()["monthly_trends"]]
    assert months == sorted(months)


def test_analytics_month_with_only_income(client):
    client.post("/transactions/", json=INCOME_TRANSACTION)

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()
    trends = {item["month"]: item for item in data["monthly_trends"]}
    assert float(trends["2024-03"]["income"]) == pytest.approx(3000.00, rel=1e-4)
    assert float(trends["2024-03"]["expenses"]) == 0.0


def test_analytics_month_with_only_expenses(client):
    client.post("/transactions/", json=EXPENSE_FOOD)

    response = client.get("/analytics/")
    assert response.status_code == 200
    data = response.json()
    trends = {item["month"]: item for item in data["monthly_trends"]}
    assert float(trends["2024-03"]["income"]) == 0.0
    assert float(trends["2024-03"]["expenses"]) == pytest.approx(75.50, rel=1e-4)
