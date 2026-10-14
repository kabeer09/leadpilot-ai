"""Google OAuth + bulk Gmail + email-match tests (all offline/mocked)."""
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
from app.models.google_account import GoogleAccount
from app.services.contact_validation import (
    domain_of, check_email_match, pick_best_email,
)
from app.services.outreach import render_template, unrendered_placeholders, sendable_leads, apply_daily_cap

client = TestClient(app)


# -- oauth ---------------------------------------------------------------

def test_oauth_url(monkeypatch):
    from app.config import settings
    import app.services.gmail as gmail
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://x/callback")
    url = gmail.build_oauth_url()
    assert "test-client-id" in url
    assert "gmail.send" in url
    assert "access_type=offline" in url


def test_oauth_url_unconfigured(monkeypatch):
    from app.config import settings
    import app.services.gmail as gmail
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    with pytest.raises(RuntimeError):
        gmail.build_oauth_url()


def test_google_status_disconnected():
    db = SessionLocal()
    db.query(GoogleAccount).delete()
    db.commit()
    db.close()
    r = client.get("/api/auth/google/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_google_login_unconfigured(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    r = client.get("/api/auth/google/login")
    assert r.status_code == 409


# -- contact validation ----------------------------------------------------

def test_domain_of():
    assert domain_of("info@abhomeinc.com") == "abhomeinc.com"
    assert domain_of("https://www.abhomeinc.com/contact") == "abhomeinc.com"
    assert domain_of("www.abhomeinc.com") == "abhomeinc.com"
    assert domain_of(None) == ""
    assert domain_of("") == ""


def test_check_match():
    assert check_email_match("cs@abhomeinc.com", "https://www.abhomeinc.com") == \
        {"match": True, "reason": "domain_match"}
    assert check_email_match("vincent@2m2.se", "https://www.2m2.se")["match"] is True
    assert check_email_match("raviselvan@abinayahome.in",
                             "https://www.abinayahome.com") == \
        {"match": True, "reason": "domain_match_sld"}
    assert check_email_match("arif@acmold.com.tr",
                             "https://www.mutfac.com")["reason"] == "domain_mismatch"
    r = check_email_match("info@other.com", "https://www.abhomeinc.com")
    assert r == {"match": False, "reason": "domain_mismatch"}
    assert check_email_match("someone@gmail.com", "https://example.com")["reason"] == "free_provider"
    assert check_email_match("a@b.com", None)["reason"] == "no_website"
    assert check_email_match(None, "https://example.com")["reason"] == "no_email"


def test_pick_best_website_match_wins():
    primary, alternate, source = pick_best_email(
        "directory@other.com", "sales@abhomeinc.com", "https://www.abhomeinc.com")
    assert primary == "sales@abhomeinc.com"
    assert alternate == "directory@other.com"
    assert source == "website"


def test_pick_best_directory_kept():
    primary, alternate, source = pick_best_email(
        "info@abhomeinc.com", "other@random.com", "https://www.abhomeinc.com")
    assert primary == "info@abhomeinc.com"
    assert alternate == "other@random.com"
    assert source == "directory"


def test_pick_best_empty():
    assert pick_best_email(None, None, None) == (None, None, "directory")


# -- templates + bulk eligibility ------------------------------------------

def _make_lead(db, name="Bulk Co", email="buyer@bulk.example", status=LeadStatus.SCORED,
               score=100):
    source = Source(name="bulk-src", url="https://example.com/x", status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name=name, website="https://bulk.example",
                      country="India")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email=email,
                      contact_type=ContactType.EMAIL)
    db.add(contact)
    db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id, status=status,
                lead_score=score, lead_priority=LeadPriority.HIGH)
    db.add(lead)
    db.commit()
    return {"lead": lead.id, "contact": contact.id, "company": company.id, "source": source.id}


def _cleanup(ids):
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


def test_render_template():
    db = SessionLocal()
    ids = _make_lead(db)
    lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
    out = render_template("Hi {company_name} from {country} — see {website} ({contact_email})", lead)
    assert out == "Hi Bulk Co from India — see https://bulk.example (buyer@bulk.example)"
    assert unrendered_placeholders(out) == []
    assert unrendered_placeholders("Hello {unknown_field}") == ["{unknown_field}"]
    db.close()
    _cleanup(ids)


def test_sendable_leads_filters():
    db = SessionLocal()
    good = _make_lead(db, name="Good Co", email="g@g.example")
    bad_status = _make_lead(db, name="Sent Co", email="s@s.example", status=LeadStatus.EMAIL_SENT)
    no_email = _make_lead(db, name="NoMail Co", email=None)
    eligible = sendable_leads(db, 10)
    eids = [l.id for l in eligible]
    assert good["lead"] in eids
    assert bad_status["lead"] not in eids
    assert no_email["lead"] not in eids
    db.close()
    for ids in (good, bad_status, no_email):
        _cleanup(ids)


def test_send_all_requires_account():
    db = SessionLocal()
    db.query(GoogleAccount).delete()
    db.commit()
    db.close()
    r = client.post("/api/outreach/send-all", json={
        "subject": "Hi {company_name}", "message": "Body here, long enough to pass.",
        "limit": 5,
    })
    assert r.status_code == 409


def test_send_all_dry_run():
    db = SessionLocal()
    ids = _make_lead(db)
    db.close()
    r = client.post("/api/outreach/send-all", json={
        "subject": "Hi {company_name}", "message": "Body here, long enough to pass.",
        "limit": 5, "dry_run": True,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert any(p["lead_id"] == ids["lead"] for p in data["preview"])
    _cleanup(ids)


def test_check_replies_matches_thread(monkeypatch):
    import app.services.gmail as gmail_mod
    db = SessionLocal()
    ids = _make_lead(db, status=LeadStatus.EMAIL_SENT)
    lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
    outreach = Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                        status=OutreachStatus.SENT, subject="Hi", message="Hello body here.",
                        sent_at=datetime.utcnow() - timedelta(hours=3),
                        provider_message_id="m1", provider_thread_id="t1")
    db.add(outreach)
    db.commit()
    db.close()

    # Fake Google account (tokens unused — gmail fns mocked)
    db = SessionLocal()
    db.query(GoogleAccount).delete()
    db.add(GoogleAccount(email="me@test.example", refresh_token="rt"))
    db.commit()
    db.close()

    monkeypatch.setattr(gmail_mod, "list_recent_messages",
                        lambda account, query="newer_than:2d", max_results=50: [{"id": "m2"}])
    monkeypatch.setattr(gmail_mod, "get_message",
                        lambda account, mid: {"id": "m2", "thread_id": "t1",
                                              "from": "buyer@bulk.example",
                                              "subject": "Re: Hi",
                                              "snippet": "We are interested, send catalogue",
                                              "label_ids": ["INBOX"]})
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "UNKNOWN")

    r = client.post("/api/outreach/check-replies")
    assert r.status_code == 200
    data = r.json()
    assert data["matched"] == 1
    assert data["categories"].get("INTERESTED") == 1

    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
    assert lead.status == LeadStatus.INTERESTED
    db.query(GoogleAccount).delete()
    db.commit()
    db.close()
    _cleanup(ids)


def test_daily_cap_math():
    items = [{"id": i} for i in range(5)]
    assert apply_daily_cap(items, 0, 100) == items
    assert apply_daily_cap(items, 98, 100) == items[:2]
    assert apply_daily_cap(items, 100, 100) == []
    assert apply_daily_cap(items, 500, 100) == []
