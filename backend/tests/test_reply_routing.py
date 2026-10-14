"""Phase 7 — reply classification + routing tests (AI stubbed, rules verified)."""
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
from app.services.reply_processing import (
    rule_classify,
    classify_reply_with_fallback,
    route_reply,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_ollama(monkeypatch):
    """Force the rules fallback (no Ollama dependence in tests)."""
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "UNKNOWN")


@pytest.fixture()
def replied_lead():
    """Lead with a SENT email outreach, ready to receive a reply."""
    db = SessionLocal()
    source = Source(name="reply-test-src", url="https://example.com/exhibitors",
                    status=SourceStatus.PENDING)
    db.add(source)
    db.flush()
    company = Company(source_id=source.id, company_name="Reply Test Co")
    db.add(company)
    db.flush()
    contact = Contact(company_id=company.id, business_email="buyer@reply-test.example",
                      contact_type=ContactType.EMAIL)
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
                     sent_at=datetime.utcnow() - timedelta(hours=2))
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


def _activities(lead_id):
    db = SessionLocal()
    acts = db.query(Activity).filter(Activity.lead_id == lead_id).all()
    db.close()
    return {a.activity_type: a for a in acts}


# -- rules unit tests ---------------------------------------------------

def test_rules_interested():
    assert rule_classify("We are interested, please send your catalogue") == "INTERESTED"


def test_rules_meeting_request():
    assert rule_classify("Let's schedule a meeting next Tuesday, I am available at 10am") == "MEETING_REQUEST"


def test_rules_unsubscribe_wins():
    assert rule_classify("Not interested, please unsubscribe me") == "UNSUBSCRIBE"


def test_rules_out_of_office():
    assert rule_classify("I am out of office, returning on Monday") == "OUT_OF_OFFICE"


def test_rules_question():
    assert rule_classify("What are your delivery timelines for new orders?") == "QUESTION"
    # Negotiation keywords take precedence over a bare question mark
    assert rule_classify("What is your minimum order quantity?") == "NEGOTIATION"


def test_rules_negotiation():
    assert rule_classify("Can you share your best price and payment terms?") == "NEGOTIATION"


def test_rules_unknown():
    assert rule_classify("ok") == "UNKNOWN"
    assert rule_classify("") == "UNKNOWN"
    assert rule_classify(None) == "UNKNOWN"


def test_bounce_detection():
    from app.services.reply_processing import is_bounce
    assert is_bounce("Delivery Status Notification (Failure)", "bla") is True
    assert is_bounce("Undelivered Mail Returned to Sender", "") is True
    assert is_bounce("Re: Hi", "We are interested") is False
    assert is_bounce(None, None) is False


def test_route_bounce_never_replied(replied_lead):
    from app.services.reply_processing import route_reply
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == replied_lead["lead"]).first()
    outreach = db.query(Outreach).filter(Outreach.id == replied_lead["email"]).first()
    category = route_reply(db, lead, outreach, "Delivery failed",
                           "mailer-daemon@google.com",
                           "Delivery Status Notification (Failure)")
    assert category == "BOUNCED"
    db.close()
    assert _lead(replied_lead["lead"]).status == LeadStatus.BOUNCED
    db = SessionLocal()
    o = db.query(Outreach).filter(Outreach.id == replied_lead["email"]).first()
    assert o.status == OutreachStatus.BOUNCED
    db.close()


def test_ai_result_preferred(monkeypatch):
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "NEGOTIATION")
    category, method = classify_reply_with_fallback("whatever text")
    assert (category, method) == ("NEGOTIATION", "ai")


def test_suppression_phrases_override_ai(monkeypatch):
    import app.services.ai_generator as ai_gen
    monkeypatch.setattr(ai_gen, "classify_reply", lambda *a, **k: "INTERESTED")
    category, method = classify_reply_with_fallback("Please unsubscribe me now")
    assert (category, method) == ("UNSUBSCRIBE", "rules-safety")
    category, method = classify_reply_with_fallback("We are not interested at this time")
    assert category == "NOT_INTERESTED"


# -- routing tests -------------------------------------------------------

def _route(replied_lead, body):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == replied_lead["lead"]).first()
    outreach = db.query(Outreach).filter(Outreach.id == replied_lead["email"]).first()
    category = route_reply(db, lead, outreach, body, "buyer@reply-test.example", "Re: Hi")
    db.close()
    return category


def test_route_interested(replied_lead):
    assert _route(replied_lead, "We are interested, please send your catalogue") == "INTERESTED"
    assert _lead(replied_lead["lead"]).status == LeadStatus.INTERESTED


def test_route_meeting_request(replied_lead):
    assert _route(replied_lead, "Let's schedule a meeting, I am available on Tuesday at 10") == "MEETING_REQUEST"
    assert _lead(replied_lead["lead"]).status == LeadStatus.MEETING_PROPOSED
    acts = _activities(replied_lead["lead"])
    assert "MEETING_ACTION_NEEDED" in acts
    assert acts["REPLY_RECEIVED"].metadata_["category"] == "MEETING_REQUEST"


def test_route_unsubscribe(replied_lead):
    assert _route(replied_lead, "Please unsubscribe me from all emails") == "UNSUBSCRIBE"
    assert _lead(replied_lead["lead"]).status == LeadStatus.UNSUBSCRIBED
    assert "SUPPRESSED" in _activities(replied_lead["lead"])


def test_route_not_interested(replied_lead):
    assert _route(replied_lead, "Thanks but we have no interest right now") == "NOT_INTERESTED"
    assert _lead(replied_lead["lead"]).status == LeadStatus.NOT_INTERESTED


def test_route_question_stays_replied(replied_lead):
    assert _route(replied_lead, "What are your delivery timelines for new orders?") == "QUESTION"
    assert _lead(replied_lead["lead"]).status == LeadStatus.REPLIED


def test_route_out_of_office_stays_replied(replied_lead):
    assert _route(replied_lead, "I am out of office until Monday") == "OUT_OF_OFFICE"
    assert _lead(replied_lead["lead"]).status == LeadStatus.REPLIED


def test_webhook_reply_returns_category(replied_lead):
    r = client.post("/api/webhooks/gmail", json={
        "outreach_id": replied_lead["email"],
        "event_type": "reply",
        "from_address": "buyer@reply-test.example",
        "subject": "Re: Hi",
        "body": "We are interested, please send your catalogue",
    })
    assert r.status_code == 200
    assert r.json()["category"] == "INTERESTED"
    assert _lead(replied_lead["lead"]).status == LeadStatus.INTERESTED


def test_manual_classify_endpoint(replied_lead):
    r = client.post(f"/api/leads/{replied_lead['lead']}/classify-reply", json={
        "body": "Remove me from your list please",
    })
    assert r.status_code == 200
    assert r.json()["category"] == "UNSUBSCRIBE"
    assert _lead(replied_lead["lead"]).status == LeadStatus.UNSUBSCRIBED
