"""Phase 6 — 24h WhatsApp follow-up tests."""
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
from app.models.meeting import Meeting
from app.services.ai_validator import get_fallback_whatsapp
from app.services.outreach import (
    find_followup_due_leads,
    queue_whatsapp_followup,
    scan_and_queue_followups,
    is_outreach_payload_sendable,
)

client = TestClient(app)

WA_MESSAGE = "Hello Test Co team, following up on our email about metal decor. Open to a short Google Meet? Reply STOP to opt out."


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    """Deterministic routing (no Ollama dependence in tests)."""
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "UNKNOWN")


@pytest.fixture()
def sent_lead():
    """Lead with EMAIL_SENT 25h ago + WhatsApp number (follow-up due)."""
    db = SessionLocal()
    source = Source(name="wa-test-src", url="https://example.com/exhibitors",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name="WA Test Co",
                      description="Makes metal decor for testing.")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email="buyer@wa-test.example",
                      whatsapp_number="+15551234567", contact_type=ContactType.EMAIL,
                      whatsapp_source_url="https://wa-test.example/contact",
                      consent_status="eligible", whatsapp_eligible=True)
    db.add(contact)
    db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id,
                status=LeadStatus.EMAIL_SENT, lead_score=70,
                lead_priority=LeadPriority.MEDIUM)
    db.add(lead)
    db.flush()
    email = Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                     status=OutreachStatus.SENT, subject="Hi",
                     message="Hello, this is a test message body.",
                     sent_at=datetime.utcnow() - timedelta(hours=25))
    db.add(email)
    db.commit()
    ids = {"lead": lead.id, "contact": contact.id,
           "company": company.id, "source": source.id, "email": email.id}
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


def _lead(lead_id):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    db.close()
    return lead


def test_fallback_whatsapp_message():
    msg = get_fallback_whatsapp({"company_name": "Acme Ltd"})
    assert "Acme Ltd" in msg
    assert "STOP" in msg
    assert len(msg.split()) <= 80


def test_find_followup_due(sent_lead):
    db = SessionLocal()
    due = find_followup_due_leads(db)
    assert sent_lead["lead"] in [l.id for l in due]
    db.close()


def test_not_due_when_email_fresh(sent_lead):
    db = SessionLocal()
    email = db.query(Outreach).filter(Outreach.id == sent_lead["email"]).first()
    email.sent_at = datetime.utcnow() - timedelta(hours=1)
    db.commit()
    due = find_followup_due_leads(db)
    assert sent_lead["lead"] not in [l.id for l in due]
    db.close()


def test_queue_whatsapp_creates_pending(sent_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    outreach, error = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    assert error is None
    assert outreach.channel == OutreachChannel.WHATSAPP
    assert outreach.status == OutreachStatus.PENDING
    assert outreach.message.startswith(WA_MESSAGE)
    assert "STOP" in outreach.message  # opt-out footer
    db.close()
    assert _lead(sent_lead["lead"]).status == LeadStatus.FOLLOWUP_DUE


def test_queue_whatsapp_uses_fallback_when_ai_down(sent_lead, monkeypatch):
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "generate_whatsapp_followup", lambda *a, **k: None)
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    outreach, error = queue_whatsapp_followup(db, lead)
    assert error is None
    assert "WA Test Co" in outreach.message
    assert "STOP" in outreach.message
    db.close()


def test_queue_whatsapp_duplicate_blocked(sent_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    o1, e1 = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    assert e1 is None
    o2, e2 = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    assert o2 is None
    assert "already exists" in e2
    db.close()


def test_queue_whatsapp_no_number(sent_lead):
    db = SessionLocal()
    contact = db.query(Contact).filter(Contact.id == sent_lead["contact"]).first()
    contact.whatsapp_number = None
    db.commit()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    db.refresh(lead)
    outreach, error = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    assert outreach is None
    assert "WhatsApp number" in error
    db.close()


def test_replied_lead_excluded_from_scan(sent_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    lead.status = LeadStatus.REPLIED
    db.commit()
    due = find_followup_due_leads(db)
    assert sent_lead["lead"] not in [l.id for l in due]
    db.close()


def test_ready_whatsapp_channel_has_to_phone(sent_lead, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DAILY_SEND_CAP", 1000000)
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    outreach, _ = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    oid = outreach.id
    db.close()

    resp = client.get("/api/outreach/ready?channel=WHATSAPP")
    assert resp.status_code == 200
    items = [i for i in resp.json() if i["id"] == oid]
    assert len(items) == 1
    assert items[0]["to_phone"] == "+15551234567"
    assert is_outreach_payload_sendable(items[0]) is True


def test_sent_ack_sets_whatsapp_sent(sent_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    outreach, _ = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    oid = outreach.id
    db.close()

    r = client.post(f"/api/outreach/{oid}/sent", json={"message_id": "wa-1"})
    assert r.status_code == 200
    assert _lead(sent_lead["lead"]).status == LeadStatus.WHATSAPP_SENT


def test_scan_endpoint_queues_due(sent_lead):
    r = client.post("/api/outreach/followups/scan")
    assert r.status_code == 200
    data = r.json()
    assert data["queued"] >= 1

    r2 = client.get("/api/outreach/followups/due")
    assert r2.status_code == 200
    # Already queued → no longer due
    assert sent_lead["lead"] not in [d["lead_id"] for d in r2.json()]


def test_whatsapp_reply_webhook(sent_lead):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == sent_lead["lead"]).first()
    outreach, _ = queue_whatsapp_followup(db, lead, message=WA_MESSAGE)
    oid = outreach.id
    from app.services.outreach import mark_outreach_sent
    mark_outreach_sent(db, outreach, message_id="wa-1")
    db.close()

    r = client.post("/api/webhooks/whatsapp", json={
        "outreach_id": oid, "event_type": "reply",
        "from_number": "+15551234567", "body": "Sounds good, send catalogue",
    })
    assert r.status_code == 200
    # "send catalogue" routes to INTERESTED (Phase 7 classification)
    assert _lead(sent_lead["lead"]).status == LeadStatus.INTERESTED
