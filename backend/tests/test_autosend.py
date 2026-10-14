"""Auto-send scheduler + multi-account tests (Gmail mocked)."""
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.outreach import Outreach, OutreachStatus
from app.models.activity import Activity
from app.models.meeting import Meeting
from app.models.google_account import GoogleAccount
from app.models.auto_send_state import AutoSendState
from app.services.outreach import run_auto_send, get_active_account, touch_account

client = TestClient(app)


@pytest.fixture()
def send_fixture():
    db = SessionLocal()
    db.query(GoogleAccount).delete()
    db.query(AutoSendState).delete()
    s = Source(name="auto-src", url="https://example.com/auto", status=SourceStatus.PENDING)
    db.add(s)
    db.flush()
    c = Company(source_id=s.id, company_name="Auto Co", website="https://auto.example")
    db.add(c)
    db.flush()
    ct = Contact(company_id=c.id, business_email="buyer@auto.example",
                 contact_type=ContactType.EMAIL)
    db.add(ct)
    db.flush()
    lead = Lead(company_id=c.id, contact_id=ct.id, status=LeadStatus.SCORED,
                lead_score=90, lead_priority=LeadPriority.HIGH)
    db.add(lead)
    db.commit()
    ids = {"lead": lead.id, "contact": ct.id, "company": c.id, "source": s.id}
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
    db.query(GoogleAccount).delete()
    db.query(AutoSendState).delete()
    db.commit()
    db.close()


def _add_account(email):
    db = SessionLocal()
    acc = GoogleAccount(email=email, refresh_token="rt-" + email)
    db.add(acc)
    db.commit()
    db.refresh(acc)
    aid = acc.id
    db.close()
    return aid


def test_multi_account_select(send_fixture):
    a1 = _add_account("one@test.example")
    a2 = _add_account("two@test.example")
    db = SessionLocal()
    assert get_active_account(db).id == a2  # most recently added... see note
    touch_account(db, db.query(GoogleAccount).filter(GoogleAccount.id == a1).first())
    assert get_active_account(db).id == a1
    db.close()


def test_status_lists_accounts(send_fixture):
    _add_account("one@test.example")
    _add_account("two@test.example")
    r = client.get("/api/auth/google/status")
    assert r.status_code == 200
    data = r.json()
    assert data["connected"] is True
    assert len(data["accounts"]) == 2


def test_auto_send_disabled_by_default(send_fixture, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "AUTO_SEND_ENABLED", False)
    db = SessionLocal()
    assert run_auto_send(db)["ran"] is False
    db.close()


def test_auto_send_runs_once_daily(send_fixture, monkeypatch):
    import app.services.gmail as gmail_mod
    from app.config import settings
    monkeypatch.setattr(settings, "AUTO_SEND_ENABLED", True)
    monkeypatch.setattr(settings, "AUTO_SEND_HOUR", 0)
    monkeypatch.setattr(settings, "AUTO_SEND_DAILY_LIMIT", 1)
    monkeypatch.setattr(settings, "BULK_SEND_DELAY_SECONDS", 0)
    monkeypatch.setattr(gmail_mod, "send_email",
                        lambda account, to, subj, body: {"message_id": "m1", "thread_id": "t1"})
    _add_account("sender@test.example")

    # Enable via DB state (this is what the scheduler honors)
    client.put("/api/settings/automation", json={"auto_send_enabled": True})
    db = SessionLocal()
    first = run_auto_send(db)
    assert first["ran"] is True
    assert first["sent"] == 1
    second = run_auto_send(db)
    assert second["ran"] is False  # already ran today
    db.close()

    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == send_fixture["lead"]).first()
    assert lead.status == LeadStatus.EMAIL_SENT
    st = db.query(AutoSendState).filter(AutoSendState.id == 1).first()
    assert st.last_sent == 1 and st.last_status == "done"
    db.close()
    client.put("/api/settings/automation", json={"auto_send_enabled": False})


def test_automation_toggle_endpoint(send_fixture):
    r = client.put("/api/settings/automation",
                   json={"auto_send_enabled": True, "auto_send_daily_limit": 25})
    assert r.status_code == 200
    assert r.json()["auto_send_enabled"] is True
    r2 = client.get("/api/settings/auto-send-state")
    assert r2.json()["daily_limit"] == 25
    # restore default for other tests / real runs
    client.put("/api/settings/automation", json={"auto_send_enabled": False})
