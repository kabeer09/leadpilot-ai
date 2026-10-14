"""Health endpoint tests."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "leadpilot-ai"
    assert "status" in data
    assert "database" in data


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "LeadPilot AI"
