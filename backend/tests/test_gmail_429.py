"""Gmail 429 handling: retries with backoff, retryable stays PENDING (never FAILED)."""
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.lead import Lead, LeadStatus
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.activity import Activity

client = TestClient(app)


class Fake429(httpx.HTTPStatusError):
    def __init__(self):
        req = httpx.Request("POST", "https://gmail.googleapis.com/x")
        resp = httpx.Response(429, headers={"retry-after": "1"}, request=req)
        super().__init__("429", request=req, response=resp)


class FakeOK:
    def raise_for_status(self):
        pass

    def json(self):
        return {"id": "m1", "threadId": "t1"}


def _patch_token(monkeypatch):
    import app.services.gmail as gmail
    monkeypatch.setattr(gmail, "_valid_access_token", lambda acc: "tok")


def test_send_retries_429_then_succeeds(monkeypatch):
    import time
    import app.services.gmail as gmail
    _patch_token(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise Fake429()
        return FakeOK()

    monkeypatch.setattr(httpx, "post", fake_post)
    out = gmail.send_email(object(), "a@b.com", "Hi", "Body text here")
    assert out["message_id"] == "m1"
    assert len(calls) == 2


def test_send_gives_up_retryable_after_3(monkeypatch):
    import time
    import app.services.gmail as gmail
    _patch_token(monkeypatch)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        raise Fake429()

    monkeypatch.setattr(httpx, "post", fake_post)
    out = gmail.send_email(object(), "a@b.com", "Hi", "Body text here")
    assert "error" in out and out.get("retryable") is True
    assert len(calls) == 3


def test_send_400_is_not_retryable(monkeypatch):
    import app.services.gmail as gmail
    _patch_token(monkeypatch)

    class Fake400(httpx.HTTPStatusError):
        def __init__(self):
            req = httpx.Request("POST", "https://gmail.googleapis.com/x")
            resp = httpx.Response(400, request=req)
            super().__init__("400", request=req, response=resp)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(Fake400()))
    out = gmail.send_email(object(), "a@b.com", "Hi", "Body text here")
    assert "error" in out and not out.get("retryable")


def test_retryable_result_keeps_pending():
    from app.services.outreach import record_direct_send_result
    db = SessionLocal()
    lead_id = db.query(Lead.id).order_by(Lead.id).first()[0]
    o = Outreach(lead_id=lead_id, channel=OutreachChannel.EMAIL,
                 status=OutreachStatus.PENDING, subject="t",
                 message="Hello, this is a 429 retry test message.")
    db.add(o)
    db.commit()
    try:
        action = record_direct_send_result(
            db, o, {"error": "429 Too Many Requests", "retryable": True})
        assert action == "retryable"
        db.refresh(o)
        assert o.status == OutreachStatus.PENDING
        action = record_direct_send_result(db, o, {"error": "400 Bad Request"})
        assert action == "failed"
        db.refresh(o)
        assert o.status == OutreachStatus.FAILED
    finally:
        db.query(Activity).filter(Activity.lead_id == lead_id,
                                  Activity.activity_type == "SEND_RATE_LIMITED").delete()
        db.query(Outreach).filter(Outreach.id == o.id).delete()
        db.commit()
        db.close()
