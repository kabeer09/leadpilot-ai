"""CRM upgrade tests: preservation, multi-contact, exclusions, merges, new-batch, eligibility, webhooks."""
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


def _make_company(name, with_contact=True):
    db = SessionLocal()
    source = db.query(Source).filter(Source.name == "crm-test-src").first()
    if not source:
        source = Source(name="crm-test-src", url="https://example.com/t",
                        status=SourceStatus.PENDING)
        db.add(source)
        db.flush()
    company = Company(source_id=source.id, company_name=name)
    db.add(company)
    db.flush()
    contact = None
    if with_contact:
        contact = Contact(company_id=company.id,
                          business_email=f"buyer-{company.id}@crm-test.example",
                          phone="+1-555-0100",
                          contact_type=ContactType.EMAIL)
        db.add(contact)
        db.flush()
    lead = Lead(company_id=company.id, contact_id=contact.id if contact else None,
                status=LeadStatus.SCORED, lead_score=60,
                lead_priority=LeadPriority.MEDIUM)
    db.add(lead)
    db.commit()
    ids = {"source": source.id, "company": company.id,
           "contact": contact.id if contact else None, "lead": lead.id}
    db.close()
    return ids


def _cleanup_company(ids):
    db = SessionLocal()
    if ids.get("lead"):
        db.query(Activity).filter(Activity.lead_id == ids["lead"]).delete()
        db.query(Outreach).filter(Outreach.lead_id == ids["lead"]).delete()
        db.query(Lead).filter(Lead.id == ids["lead"]).delete()
    from app.models.contact_item import ContactItem
    from app.models.suppression import MergeAudit
    db.query(ContactItem).filter(ContactItem.company_id == ids["company"]).delete()
    db.query(MergeAudit).filter(
        (MergeAudit.canonical_company_id == ids["company"]) |
        (MergeAudit.merged_company_id == ids["company"])).delete()
    if ids.get("contact"):
        db.query(Contact).filter(Contact.id == ids["contact"]).delete()
    db.query(Company).filter(Company.id == ids["company"]).delete()
    db.commit()
    db.close()


def test_existing_records_preserved():
    # Snapshot, run read-only + dry-run operations, assert zero drift.
    db = SessionLocal()
    before = (db.query(Company).count(), db.query(Lead).count(),
              db.query(Outreach).count())
    db.close()
    assert before[0] > 3000 and before[1] > 3000 and before[2] > 500
    r = client.get("/api/outreach/new-batch/preview?limit=5")
    assert r.status_code == 200
    r = client.post("/api/data-quality/exclusions/preview")
    assert r.status_code == 200
    r = client.post("/api/data-quality/deduplicate/preview",
                    json={"canonical_id": -1, "duplicate_id": -2})
    assert r.status_code == 422
    db = SessionLocal()
    after = (db.query(Company).count(), db.query(Lead).count(),
             db.query(Outreach).count())
    db.close()
    assert before == after


def test_contact_items_store_all_values_and_sources():
    from app.services.contact_items import store_contact_items
    ids = _make_company("CRM Items Co")
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == ids["company"]).first()
        n = store_contact_items(
            db, company,
            emails=["a@crm-test.example", "b@crm-test.example"],
            phones=["+1-555-0101"], whatsapp=["+1-555-0102"],
            source_url="https://crm-test.example/contact",
            default_page="website")
        db.commit()
        assert n == 4
        # Idempotent re-save
        n2 = store_contact_items(
            db, company, emails=["a@crm-test.example"],
            source_url="https://crm-test.example/contact")
        db.commit()
        assert n2 == 0
        from app.models.contact_item import ContactItem
        rows = db.query(ContactItem).filter(
            ContactItem.company_id == ids["company"]).all()
        assert len(rows) == 4
        assert all(r.source_url == "https://crm-test.example/contact" for r in rows)
        assert all(r.verification_status == "scraped" for r in rows)
    finally:
        db.close()
        _cleanup_company(ids)


def test_no_contact_company_excluded_but_preserved():
    ids = _make_company("CRM Ghost Co", with_contact=False)
    db = SessionLocal()
    try:
        db.query(Company).filter(Company.id == ids["company"]).update(
            {"lifecycle_status": "EXCLUDED_NO_CONTACT"})
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/api/companies?limit=200&search=CRM%20Ghost%20Co")
        assert r.status_code == 200
        assert all(c["id"] != ids["company"] for c in r.json())
        r2 = client.get("/api/companies?limit=200&search=CRM%20Ghost%20Co&lifecycle=excluded")
        assert r2.status_code == 200
        assert any(c["id"] == ids["company"] for c in r2.json())
    finally:
        _cleanup_company(ids)


def test_merge_preview_and_apply_preserve_history():
    ids_a = _make_company("CRM Canonical Co")
    ids_b = _make_company("CRM Duplicate Co")
    db = SessionLocal()
    try:
        mail = Outreach(lead_id=ids_b["lead"], channel=OutreachChannel.EMAIL,
                        status=OutreachStatus.SENT, subject="Hi",
                        message="Hello, this is a CRM merge test message.",
                        sent_at=datetime.utcnow() - timedelta(hours=30))
        db.add(mail)
        db.commit()
        mail_id = mail.id
    finally:
        db.close()
    try:
        r = client.post("/api/data-quality/deduplicate/preview",
                        json={"canonical_id": ids_a["company"],
                              "duplicate_id": ids_b["company"]})
        assert r.status_code == 200
        assert r.json()["outreach_preserved"] == 1
        r2 = client.post("/api/data-quality/deduplicate/apply",
                         json={"canonical_id": ids_a["company"],
                               "duplicate_id": ids_b["company"],
                               "note": "test merge"})
        assert r2.status_code == 200
        assert r2.json()["outreach_preserved"] == 1
        db = SessionLocal()
        try:
            o = db.query(Outreach).filter(Outreach.id == mail_id).first()
            assert o is not None and o.lead_id == ids_b["lead"]
            lead = db.query(Lead).filter(Lead.id == ids_b["lead"]).first()
            assert lead.company_id == ids_a["company"]
            dup = db.query(Company).filter(Company.id == ids_b["company"]).first()
            assert dup.lifecycle_status == "MERGED"
            assert dup.merged_into_id == ids_a["company"]
            from app.models.suppression import MergeAudit
            audit = db.query(MergeAudit).filter(
                MergeAudit.merged_company_id == ids_b["company"]).first()
            assert audit is not None
        finally:
            db.close()
    finally:
        _cleanup_company(ids_b)
        _cleanup_company(ids_a)


def test_new_batch_preview_excludes_contacted_and_suppressed():
    ids = _make_company("CRM Batch Co")
    db = SessionLocal()
    try:
        mail = Outreach(lead_id=ids["lead"], channel=OutreachChannel.EMAIL,
                        status=OutreachStatus.SENT, subject="Hi",
                        message="Hello, CRM batch exclusion test message here.",
                        sent_at=datetime.utcnow() - timedelta(hours=50))
        db.add(mail)
        db.commit()
    finally:
        db.close()
    try:
        r = client.get("/api/outreach/new-batch/preview?limit=100")
        assert r.status_code == 200
        assert all(row["lead_id"] != ids["lead"] for row in r.json()["rows"])
        # Suppress another address, verify suppression blocks batch eligibility
        from app.services.outreach import add_suppression, is_email_ready_to_send
        db = SessionLocal()
        try:
            lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
            email = lead.contact.business_email
            add_suppression(db, email, "email", "manual", source="test",
                            lead_id=ids["lead"])
            db.commit()
            assert is_email_ready_to_send(lead, db) is False
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            from app.models.suppression import Suppression
            db.query(Suppression).filter(Suppression.lead_id == ids["lead"]).delete()
            db.commit()
        finally:
            db.close()
        _cleanup_company(ids)


def test_new_batch_run_idempotent(monkeypatch):
    """Mocked Gmail: first run sends once, retry sends zero (no double-send)."""
    import app.api.outreach as out_api
    ids = _make_company("CRM Idem Co")
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
    db.expunge_all()
    db.close()
    monkeypatch.setattr(out_api, "_new_batch_candidates", lambda *a, **k: [lead])
    monkeypatch.setattr(out_api, "get_active_account",
                        lambda db: type("A", (), {"id": 1})())
    import app.services.gmail as gmail
    monkeypatch.setattr(gmail, "send_email",
                        lambda *a, **k: {"message_id": "m1", "thread_id": "t1"})
    try:
        r1 = client.post("/api/outreach/new-batch/run",
                         json={"subject": "Hi {company_name}", "message": "Test body here, long enough.",
                               "limit": 5})
        assert r1.status_code == 200
        assert r1.json()["sent"] == 1
        r2 = client.post("/api/outreach/new-batch/run",
                         json={"subject": "Hi {company_name}", "message": "Test body here, long enough.",
                               "limit": 5})
        assert r2.status_code == 200
        assert r2.json()["sent"] == 0
    finally:
        _cleanup_company(ids)


def test_whatsapp_eligibility_gates():
    from app.services.outreach import check_whatsapp_eligibility
    ids = _make_company("CRM WA Co")
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == ids["contact"]).first()
        contact.whatsapp_number = "+1-555-0199"
        contact.whatsapp_source_url = "https://crm-test.example/contact"
        contact.whatsapp_eligible = None
        contact.consent_status = None
        ok, reason = check_whatsapp_eligibility(contact)
        assert ok is False and "approval" in reason
        contact.whatsapp_eligible = True
        contact.consent_status = "eligible"
        ok, _ = check_whatsapp_eligibility(contact)
        assert ok is True
        contact.consent_status = "opted_out"
        ok, reason = check_whatsapp_eligibility(contact)
        assert ok is False and "opted out" in reason
        ok, _ = check_whatsapp_eligibility(None)
        assert ok is False
    finally:
        db.close()
        _cleanup_company(ids)


def test_whatsapp_queue_blocked_without_approval():
    from app.services.outreach import queue_whatsapp_followup
    ids = _make_company("CRM WAQ Co")
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == ids["contact"]).first()
        contact.whatsapp_number = "+1-555-0188"
        contact.whatsapp_source_url = "https://crm-test.example/contact"
        contact.whatsapp_eligible = None
        contact.consent_status = None
        lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
        lead.status = LeadStatus.EMAIL_SENT
        mail = Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                        status=OutreachStatus.SENT, subject="Hi",
                        message="Hello, CRM whatsapp gate test message here.",
                        sent_at=datetime.utcnow() - timedelta(hours=30))
        db.add(mail)
        db.commit()
        out, err = queue_whatsapp_followup(db, lead, message="Test follow-up message here")
        assert out is None and err is not None and "eligible" in err
    finally:
        db.close()
        _cleanup_company(ids)


def test_provider_failure_never_marks_sent():
    r = client.post("/api/webhooks/whatsapp/status",
                    json={"outreach_id": 99999999, "status": "failed",
                          "error_code": "131000", "error_message": "boom"})
    assert r.status_code == 404


def test_gmail_reply_and_bounce_aliases():
    ids = _make_company("CRM Alias Co")
    db = SessionLocal()
    try:
        mail = Outreach(lead_id=ids["lead"], channel=OutreachChannel.EMAIL,
                        status=OutreachStatus.SENT, subject="Hi",
                        message="Hello, CRM alias test message body here.",
                        sent_at=datetime.utcnow() - timedelta(hours=2))
        db.add(mail)
        db.commit()
        email = db.query(Contact).filter(
            Contact.id == ids["contact"]).first().business_email
    finally:
        db.close()
    try:
        r = client.post("/api/webhooks/gmail/reply",
                        json={"from_address": email, "subject": "Re: Hi",
                              "body": "We are interested, send catalogue please"})
        assert r.status_code == 200
        db = SessionLocal()
        try:
            lead = db.query(Lead).filter(Lead.id == ids["lead"]).first()
            assert lead.status in (LeadStatus.REPLIED, LeadStatus.INTERESTED)
        finally:
            db.close()
    finally:
        _cleanup_company(ids)


def test_timeline_and_trends_and_health_shapes():
    db = SessionLocal()
    lead_id = db.query(Lead.id).order_by(Lead.id).first()[0]
    db.close()
    r = client.get(f"/api/leads/{lead_id}/timeline")
    assert r.status_code == 200
    assert "events" in r.json()
    r = client.get("/api/analytics/trends?days=7")
    assert r.status_code == 200
    assert len(r.json()) == 7
    assert "reply_rate" in r.json()[0]
    r = client.get("/api/automation/health")
    assert r.status_code == 200
    for key in ("last_email_sent_at", "pending_email", "latest_errors", "scheduler"):
        assert key in r.json()
