"""Phase 8 — meeting propose/book tests (Google API mocked)."""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.activity import Activity
from app.models.meeting import Meeting, MeetingStatus

client = TestClient(app)


@pytest.fixture()
def interested_lead():
    db = SessionLocal()
    source = Source(name="meet-test-src", url="https://example.com/exhibitors",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name="Meet Test Co")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email="buyer@meet-test.example",
                      contact_type=ContactType.EMAIL)
    db.add(contact)
    db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id,
                status=LeadStatus.INTERESTED, lead_score=85,
                lead_priority=LeadPriority.HIGH)
    db.add(lead)
    db.commit()
    ids = {"lead": lead.id, "contact": contact.id,
           "company": company.id, "source": source.id}
    db.close()
    yield ids
    db = SessionLocal()
    db.query(Activity).filter(Activity.lead_id == ids["lead"]).delete()
    db.query(Meeting).filter(Meeting.lead_id == ids["lead"]).delete()
    db.query(Outreach).filter(Outreach.lead_id == ids["lead"]).delete()
    db.query(Lead).filter(Lead.id == ids["lead"]).delete()
    db.query(Contact).filter(Contact.id == ids["contact"]).delete()
    db.query(Company).filter(Company.id == ids["company"]).delete()
    db.query(Source).filter(Source.id == ids["source"]).delete()
    db.commit()
    db.close()


def _slot():
    start = datetime.utcnow() + timedelta(days=2)
    start = start.replace(hour=10, minute=0, second=0, microsecond=0)
    return start, start + timedelta(minutes=30)


def test_propose_meeting(interested_lead):
    start, end = _slot()
    r = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "PROPOSED"
    assert data["lead_id"] == interested_lead["lead"]

    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == interested_lead["lead"]).first()
    assert lead.status == LeadStatus.MEETING_PROPOSED
    db.close()


def test_propose_rejects_past(interested_lead):
    start = datetime.utcnow() - timedelta(days=1)
    r = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(),
        "end_time": (start + timedelta(minutes=30)).isoformat(),
    })
    assert r.status_code == 422


def test_propose_blocked_status(interested_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == interested_lead["lead"]).first()
    lead.status = LeadStatus.UNSUBSCRIBED
    db.commit()
    db.close()
    start, end = _slot()
    r = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    })
    assert r.status_code == 422


def test_book_without_config_returns_409(interested_lead):
    start, end = _slot()
    mid = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    }).json()["id"]
    r = client.post(f"/api/meetings/{mid}/book")
    # Calendar not configured in test env
    assert r.status_code == 409
    assert "Calendar" in r.json()["detail"]


def test_book_with_mocked_google(interested_lead, monkeypatch):
    import app.services.calendar as cal_mod

    monkeypatch.setattr(cal_mod.CalendarService, "is_configured", lambda self: True)
    monkeypatch.setattr(cal_mod.CalendarService, "_access_token", lambda self: "fake-token")

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "evt_123", "hangoutLink": "https://meet.google.com/abc-defg-hij",
                    "htmlLink": "https://calendar.google.com/event?eid=123"}

    monkeypatch.setattr(cal_mod.httpx, "post", lambda *a, **k: FakeResp())

    start, end = _slot()
    mid = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    }).json()["id"]

    r = client.post(f"/api/meetings/{mid}/book")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "CONFIRMED"
    assert data["calendar_event_id"] == "evt_123"
    assert data["meet_url"] == "https://meet.google.com/abc-defg-hij"

    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == interested_lead["lead"]).first()
    assert lead.status == LeadStatus.MEETING_BOOKED
    db.close()

    # Idempotent re-book
    r2 = client.post(f"/api/meetings/{mid}/book")
    assert r2.status_code == 200
    assert r2.json()["calendar_event_id"] == "evt_123"


def test_cancel_meeting(interested_lead):
    start, end = _slot()
    mid = client.post("/api/meetings/propose", json={
        "lead_id": interested_lead["lead"],
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    }).json()["id"]
    r = client.post(f"/api/meetings/{mid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"


def test_availability_unconfigured():
    start, end = _slot()
    r = client.post("/api/meetings/availability", json={
        "start_time": start.isoformat(), "end_time": end.isoformat(),
    })
    assert r.status_code == 200
    assert "available" in r.json()
