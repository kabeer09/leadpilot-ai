"""Phase 5 — n8n ↔ Gmail outreach contract tests."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.services.outreach import (
    queue_email_for_lead,
    build_n8n_payload,
    mark_outreach_sent,
    mark_outreach_failed,
    is_email_ready_to_send,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    """Deterministic routing (no Ollama dependence in tests)."""
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "UNKNOWN")

SUBJECT = "Partnership inquiry from New Look Impex"
MESSAGE = "Dear team at Test Co, we manufacture metal decor. Would you like our catalogue? Happy to schedule a Google Meet."


@pytest.fixture()
def lead_with_email():
    db = SessionLocal()
    source = Source(name="n8n-test-src", url="https://example.com/exhibitors",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name="N8N Test Co",
                      description="Makes metal decor for testing.")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email="buyer@n8n-test.example",
                      contact_type=ContactType.EMAIL)
    db.add(contact)
    db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id,
                status=LeadStatus.SCORED, lead_score=70,
                lead_priority=LeadPriority.MEDIUM)
    db.add(lead)
    db.commit()
    ids = {"lead": lead.id, "contact": contact.id,
           "company": company.id, "source": source.id}
    db.close()
    yield ids
    db = SessionLocal()
    from app.models.activity import Activity
    from app.models.meeting import Meeting
    db.query(Activity).filter(Activity.lead_id == ids["lead"]).delete()
    db.query(Meeting).filter(Meeting.lead_id == ids["lead"]).delete()
    db.query(Outreach).filter(Outreach.lead_id == ids["lead"]).delete()
    db.query(Lead).filter(Lead.id == ids["lead"]).delete()
    db.query(Contact).filter(Contact.id == ids["contact"]).delete()
    db.query(Company).filter(Company.id == ids["company"]).delete()
    db.query(Source).filter(Source.id == ids["source"]).delete()
    db.commit()
    db.close()


def _fresh_lead(lead_id):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    db.expunge_all()
    db.close()
    # Re-query per use; return id-based loader instead
    return lead_id


def _get_lead(lead_id):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    db.close()
    return lead


def test_queue_email_creates_pending(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    assert is_email_ready_to_send(lead) is True
    outreach, error = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    assert error is None
    assert outreach.id is not None
    assert outreach.status == OutreachStatus.PENDING
    assert outreach.subject == SUBJECT
    db.close()

    lead = _get_lead(lead_with_email["lead"])
    assert lead.status == LeadStatus.EMAIL_VALIDATED


def test_queue_duplicate_blocked(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    o1, e1 = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    assert e1 is None
    o2, e2 = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    assert o2 is None
    assert "already has" in e2
    db.close()


def test_queue_blocked_without_email(lead_with_email):
    db = SessionLocal()
    contact = db.query(Contact).filter(Contact.id == lead_with_email["contact"]).first()
    contact.business_email = None
    db.commit()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    db.refresh(lead)
    outreach, error = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    assert outreach is None
    assert error is not None
    db.close()


def test_n8n_payload_shape(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    payload = build_n8n_payload(outreach)
    assert payload["to_email"] == "buyer@n8n-test.example"
    assert payload["company_name"] == "N8N Test Co"
    assert payload["subject"] == SUBJECT
    assert payload["message"].startswith(MESSAGE)
    assert "STOP" in payload["message"]  # opt-out footer
    db.close()


def test_ready_endpoint_includes_recipient(lead_with_email, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_SEND_CAP", 1000000)
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    oid = outreach.id
    db.close()

    resp = client.get("/api/outreach/ready?limit=500")
    assert resp.status_code == 200
    items = [i for i in resp.json() if i["id"] == oid]
    assert len(items) == 1
    assert items[0]["to_email"] == "buyer@n8n-test.example"


def test_sent_ack_idempotent_and_updates_lead(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    oid = outreach.id
    db.close()

    r1 = client.post(f"/api/outreach/{oid}/sent", json={"message_id": "gmail-123"})
    assert r1.status_code == 200
    assert r1.json()["message"] == "Marked as sent"

    r2 = client.post(f"/api/outreach/{oid}/sent", json={"message_id": "gmail-123"})
    assert r2.status_code == 200
    assert r2.json()["message"] == "Already sent"

    lead = _get_lead(lead_with_email["lead"])
    assert lead.status == LeadStatus.EMAIL_SENT


def test_failed_endpoint(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    oid = outreach.id
    db.close()

    r = client.post(f"/api/outreach/{oid}/failed", json={"error": "Gmail 403 quota"})
    assert r.status_code == 200
    db = SessionLocal()
    o = db.query(Outreach).filter(Outreach.id == oid).first()
    assert o.status == OutreachStatus.FAILED
    assert "quota" in o.error
    db.close()


def test_reply_webhook_resolves_by_from_address(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    mark_outreach_sent(db, outreach, message_id="gmail-123")
    oid = outreach.id
    db.close()

    r = client.post("/api/webhooks/gmail", json={
        "event_type": "reply",
        "from_address": "buyer@n8n-test.example",
        "subject": "Re: Partnership inquiry",
        "body": "We are interested, send catalogue.",
    })
    assert r.status_code == 200

    db = SessionLocal()
    o = db.query(Outreach).filter(Outreach.id == oid).first()
    assert o.status == OutreachStatus.REPLIED
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    # "We are interested..." routes to INTERESTED (Phase 7 classification)
    assert lead.status == LeadStatus.INTERESTED
    db.close()


def test_mark_sent_service_idempotent(lead_with_email):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_with_email["lead"]).first()
    outreach, _ = queue_email_for_lead(db, lead, SUBJECT, MESSAGE)
    assert mark_outreach_sent(db, outreach) is True
    assert mark_outreach_sent(db, outreach) is False
    mark_outreach_failed(db, outreach, "late failure")  # service-level call works
    db.close()
