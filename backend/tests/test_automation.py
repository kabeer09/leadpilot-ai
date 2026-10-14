"""Automation tests: seller profile, bulk queue, daily cap, kill switch, opt-out."""
import pytest
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
from app.services.outreach import ensure_opt_out, OPT_OUT_LINE

client = TestClient(app)


@pytest.fixture()
def three_leads():
    """Three SCORED leads with business emails."""
    db = SessionLocal()
    source = Source(name="bulk-test-src", url="https://example.com/exhibitors",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    ids = {"leads": [], "contacts": [], "companies": [], "source": source.id}
    for i in range(3):
        company = Company(source_id=source.id, company_name=f"Bulk Co {i}",
                          description="Makes metal decor for testing.")
        db.add(company)
        db.flush()
        contact = Contact(company_id=company.id,
                          business_email=f"buyer{i}@bulk-test.example",
                          contact_type=ContactType.EMAIL)
        db.add(contact)
        db.flush()
        lead = Lead(company_id=company.id, contact_id=contact.id,
                    status=LeadStatus.SCORED, lead_score=70 + i,
                    lead_priority=LeadPriority.MEDIUM)
        db.add(lead)
        db.flush()
        ids["leads"].append(lead.id)
        ids["contacts"].append(contact.id)
        ids["companies"].append(company.id)
    db.commit()
    db.close()
    yield ids
    db = SessionLocal()
    for lid in ids["leads"]:
        db.query(Activity).filter(Activity.lead_id == lid).delete()
        db.query(Meeting).filter(Meeting.lead_id == lid).delete()
        db.query(Outreach).filter(Outreach.lead_id == lid).delete()
        db.query(Lead).filter(Lead.id == lid).delete()
    for cid in ids["contacts"]:
        db.query(Contact).filter(Contact.id == cid).delete()
    for coid in ids["companies"]:
        db.query(Company).filter(Company.id == coid).delete()
    db.query(Source).filter(Source.id == ids["source"]).delete()
    # restore default seller
    from app.services.seller import update_seller
    update_seller(db, {"business_name": "New Look Impex"})
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "generate_email", lambda *a, **k: None)
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "UNKNOWN")


def test_opt_out_footer():
    assert ensure_opt_out("Hello world, this is a long enough test message here.") \
        .endswith(OPT_OUT_LINE)
    already = "Hello world, reply STOP to opt out please."
    assert ensure_opt_out(already) == already
    assert ensure_opt_out("") == ""


def test_source_url_safety(monkeypatch):
    import socket as _socket
    from app.utils.url_safety import validate_public_url
    # Public hostname resolves to a public IP (mocked DNS)
    monkeypatch.setattr(
        _socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert validate_public_url("https://example-fair.com/exhibitors") is None
    # Hostname resolving only to private IPs is blocked (rebinding-safe)
    monkeypatch.setattr(
        _socket, "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.1.10", 0))])
    assert validate_public_url("https://example-fair.com/x") is not None
    # Dual-stack host with one public address is allowed
    monkeypatch.setattr(
        _socket, "getaddrinfo",
        lambda *a, **k: [(23, 1, 6, "", ("64:ff9b::d48:6baf", 0)),
                         (2, 1, 6, "", ("13.72.107.175", 0))])
    assert validate_public_url("https://www.highpointmarket.org/ExhibitorDirectory") is None
    assert validate_public_url("http://localhost:8001/x") is not None
    assert validate_public_url("http://127.0.0.1/") is not None
    assert validate_public_url("http://192.168.1.10/") is not None
    assert validate_public_url("http://10.0.0.5:5432/") is not None
    assert validate_public_url("ftp://example.com/x") is not None
    assert validate_public_url("not a url") is not None
    assert validate_public_url("http://user:pass@example.com/") is not None


def test_create_source_rejects_unsafe():
    r = client.post("/api/sources", json={
        "name": "Evil", "url": "http://127.0.0.1:5432/",
    })
    assert r.status_code == 422
    r = client.post("/api/sources", json={
        "name": "Evil", "url": "http://localhost:8001/",
    })
    assert r.status_code == 422


def test_seller_roundtrip():
    r = client.put("/api/settings/seller", json={"business_name": "Acme Test Ltd",
                                                 "sender_name": "A. Seller"})
    assert r.status_code == 200
    assert r.json()["business_name"] == "Acme Test Ltd"
    r2 = client.get("/api/settings/seller")
    assert r2.json()["sender_name"] == "A. Seller"


def test_bulk_uses_seller_name(three_leads):
    client.put("/api/settings/seller", json={"business_name": "Acme Test Ltd"})
    r = client.post("/api/outreach/queue-bulk",
                    json={"limit": 1, "source_id": three_leads["source"]})
    assert r.status_code == 200
    assert r.json()["queued_count"] == 1
    oid = r.json()["queued"][0]["outreach_id"]
    db = SessionLocal()
    o = db.query(Outreach).filter(Outreach.id == oid).first()
    assert "Acme Test Ltd" in o.message
    assert o.message.endswith(OPT_OUT_LINE)
    db.close()


def test_bulk_dry_run_writes_nothing(three_leads):
    r = client.post("/api/outreach/queue-bulk",
                    json={"limit": 3, "dry_run": True, "source_id": three_leads["source"]})
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert data["queued_count"] == 3
    assert all("to_email" in q for q in data["queued"])
    db = SessionLocal()
    n = db.query(Outreach).filter(
        Outreach.lead_id.in_(three_leads["leads"]),
        Outreach.status == OutreachStatus.PENDING).count()
    db.close()
    assert n == 0


def test_bulk_queues_and_second_run_skips(three_leads):
    src = three_leads["source"]
    r1 = client.post("/api/outreach/queue-bulk", json={"limit": 2, "source_id": src})
    assert r1.json()["queued_count"] == 2
    r2 = client.post("/api/outreach/queue-bulk", json={"limit": 5, "source_id": src})
    # 1 remaining eligible (third lead), first two now have PENDING
    assert r2.json()["queued_count"] == 1
    assert any("already has" in s["reason"] for s in r2.json()["skipped"])


def test_bulk_priority_filter(three_leads):
    r = client.post("/api/outreach/queue-bulk",
                    json={"limit": 10, "priority": "HIGH", "source_id": three_leads["source"]})
    assert r.json()["queued_count"] == 0  # fixture leads are MEDIUM


def test_ready_daily_cap(three_leads, monkeypatch):
    from datetime import datetime
    from app.config import settings
    from app.models.outreach import Outreach, OutreachStatus
    client.post("/api/outreach/queue-bulk",
                json={"limit": 3, "source_id": three_leads["source"]})
    # Cap relative to today's REAL sends: exactly 2 slots remain => 2 items
    db = SessionLocal()
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = db.query(Outreach).filter(
        Outreach.status == OutreachStatus.SENT, Outreach.sent_at >= start_of_day).count()
    db.close()
    monkeypatch.setattr(settings, "DAILY_SEND_CAP", sent_today + 2)
    r = client.get("/api/outreach/ready")
    assert len(r.json()) == 2


def test_ready_kill_switch(three_leads, monkeypatch):
    from app.config import settings
    client.post("/api/outreach/queue-bulk",
                json={"limit": 1, "source_id": three_leads["source"]})
    monkeypatch.setattr(settings, "OUTREACH_SENDING_ENABLED", False)
    try:
        r = client.get("/api/outreach/ready")
        assert r.json() == []
    finally:
        monkeypatch.setattr(settings, "OUTREACH_SENDING_ENABLED", True)


def test_automation_status_shape():
    r = client.get("/api/settings/automation")
    assert r.status_code == 200
    data = r.json()
    assert {"sending_enabled", "daily_send_cap", "sent_today",
            "remaining_today"} <= set(data)
