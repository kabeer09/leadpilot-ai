"""Analytics endpoint tests."""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_analytics_overview():
    response = client.get("/api/analytics/overview")
    assert response.status_code == 200
    data = response.json()
    assert "total_companies" in data
    assert "emails_sent" in data
    assert "reply_rate" in data
