"""Outreach tracking tests: summary, sent list, email-due route, thread send, fail-closed auto follow-ups."""
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

client = TestClient(app)


def _make_old_sent_lead(hours_ago=25, with_reply=False):
    """Lead whose first email was sent `hours_ago` (due when >24h)."""
    db = SessionLocal()
    source = Source(name="track-test-src", url="https://example.com/t",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name="Track Test Co")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email="buyer@track-test.example",
                      contact_type=ContactType.EMAIL)
    db.add(contact)
    db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id,
                status=LeadStatus.EMAIL_SENT, lead_score=80,
                lead_priority=LeadPriority.HIGH)
    db.add(lead)
    db.flush()
    email = Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                     status=OutreachStatus.SENT, subject="Partnership",
                     message="Hello, this is a test message body for tracking.",
                     sent_at=datetime.utcnow() - timedelta(hours=hours_ago),
                     provider_message_id="msg-123",
                     provider_thread_id="thread-abc")
    db.add(email)
    db.flush()
    if with_reply:
        reply = Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                         status=OutreachStatus.REPLIED, subject="Re: Partnership",
                         message="Thanks, interested!",
                         sent_at=datetime.utcnow() - timedelta(hours=1),
                         response_at=datetime.utcnow() - timedelta(hours=1))
        db.add(reply)
    db.commit()
    ids = {"lead": lead.id, "contact": contact.id,
           "company": company.id, "source": source.id}
    db.close()
    return ids


def _cleanup(ids):
    db = SessionLocal()
    db.query(Activity).filter(Activity.lead_id == ids["lead"]).delete()
    db.query(Outreach).filter(Outreach.lead_id == ids["lead"]).delete()
    db.query(Lead).filter(Lead.id == ids["lead"]).delete()
    db.query(Contact).filter(Contact.id == ids["contact"]).delete()
    db.query(Company).filter(Company.id == ids["company"]).delete()
    db.query(Source).filter(Source.id == ids["source"]).delete()
    db.commit()
    db.close()


def test_summary_reflects_db():
    db = SessionLocal()
    sent_total = db.query(Outreach).filter(
        Outreach.channel == OutreachChannel.EMAIL,
        Outreach.status == OutreachStatus.SENT).count()
    db.close()
    r = client.get("/api/outreach/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["emails_sent_total"] == sent_total
    assert data["total_companies"] > 0
    for key in ("emails_sent_today", "replies_today", "followups_due",
                "followups_sent", "unsubscribed", "eligible_leads",
                "bounced", "interested", "meetings_booked"):
        assert key in data


def test_sent_list_shape():
    r = client.get("/api/outreach/sent?limit=5")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    row = rows[0]
    for key in ("outreach_id", "lead_id", "company", "to_email", "subject",
                "sent_at", "reply_at", "thread_id", "thread_url",
                "status", "follow_up_count", "next_action"):
        assert key in row
    if row["thread_id"]:
        assert row["thread_url"].endswith(row["thread_id"])


def test_email_due_route_lists_old_sent():
    ids = _make_old_sent_lead(hours_ago=25)
    try:
        r = client.get("/api/outreach/followups/email-due")
        assert r.status_code == 200
        found = [x for x in r.json() if x["lead_id"] == ids["lead"]]
        assert len(found) == 1
        assert found[0]["thread_id"] == "thread-abc"
    finally:
        _cleanup(ids)


def test_reply_stops_followup():
    ids = _make_old_sent_lead(hours_ago=30, with_reply=True)
    try:
        r = client.get("/api/outreach/followups/email-due")
        assert r.status_code == 200
        assert all(x["lead_id"] != ids["lead"] for x in r.json())
    finally:
        _cleanup(ids)


def test_fresh_email_not_due():
    ids = _make_old_sent_lead(hours_ago=2)
    try:
        r = client.get("/api/outreach/followups/email-due")
        assert r.status_code == 200
        assert all(x["lead_id"] != ids["lead"] for x in r.json())
    finally:
        _cleanup(ids)


def test_whatsapp_due_route_unchanged():
    # GET /followups/due is still the WhatsApp queue (to_phone shape)
    r = client.get("/api/outreach/followups/due")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_send_email_threads_followup(monkeypatch):
    """Gmail send passes threadId so follow-ups stay in-thread."""
    import app.services.gmail as gmail
    captured = {}

    monkeypatch.setattr(gmail, "_valid_access_token", lambda acc: "tok")
    import httpx

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "m1", "threadId": "thread-abc"}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(json or {})
        return FakeResp()

    monkeypatch.setattr(httpx, "post", fake_post)
    out = gmail.send_email(object(), "a@b.com", "Hi", "Body", thread_id="thread-abc")
    assert out["thread_id"] == "thread-abc"
    assert captured.get("threadId") == "thread-abc"


def test_auto_followups_fail_closed_without_account(monkeypatch):
    """No Gmail account -> nothing sent, error recorded."""
    import app.services.outreach as out
    monkeypatch.setattr(out, "get_active_account", lambda db: None)
    db = SessionLocal()
    try:
        summary = out.send_due_email_followups(db, limit=5)
    finally:
        db.close()
    assert summary["sent"] == 0
    assert summary["errors"]


def test_bulk_followup_dry_run():
    r = client.post("/api/outreach/followups/bulk", json={"limit": 5, "dry_run": True})
    assert r.status_code == 200
    data = r.json()
    assert data.get("dry_run") is True
    assert "due" in data
