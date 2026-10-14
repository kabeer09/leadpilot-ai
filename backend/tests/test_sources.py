"""Source endpoint tests."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_test_sources():
    """Remove sources created by these tests (keeps the dashboard clean)."""
    yield
    db = SessionLocal()
    db.query(Source).filter(Source.name == "Test Exhibitor Directory").delete()
    db.commit()
    db.close()


def test_create_source():
    response = client.post("/api/sources", json={
        "name": "Test Exhibitor Directory",
        "url": "https://example.com/exhibitors",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Exhibitor Directory"
    assert data["status"] == "PENDING"


def test_list_sources():
    response = client.get("/api/sources")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_get_source_not_found():
    response = client.get("/api/sources/99999")
    assert response.status_code == 404
