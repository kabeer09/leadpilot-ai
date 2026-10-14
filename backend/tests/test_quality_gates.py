"""Quality gates tests: email validation + completeness gate + limit."""
from app.services.contact_validation import (
    validate_contact_email, filter_valid_emails,
)
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead
from app.models.product import Product
from app.models.activity import Activity
from app.models.meeting import Meeting
from app.models.outreach import Outreach
from app.models.duplicate_candidate import DuplicateCandidate
import pytest


def test_validate_ok():
    r = validate_contact_email("sales@abhomeinc.com")
    assert r == {"valid": True, "reason": "ok", "email": "sales@abhomeinc.com"}


def test_validate_bad_syntax():
    assert validate_contact_email("not-an-email")["reason"] == "bad_syntax"
    assert validate_contact_email("a@b")["reason"] == "bad_syntax"
    assert validate_contact_email("")["reason"] == "no_email"
    assert validate_contact_email(None)["reason"] == "no_email"


def test_validate_junk_rejected():
    assert validate_contact_email("x@sentry.io")["reason"] == "junk_domain"
    assert validate_contact_email("x@example.com")["reason"] == "junk_domain"


def test_validate_free_provider_kept_but_flagged():
    r = validate_contact_email("ammarnathbansel@gmail.com")
    assert r["valid"] is True and r["reason"] == "free_provider"


def test_validate_cleans_wrappers():
    r = validate_contact_email("  <Info@Example.COM>,")
    assert r == {"valid": False, "reason": "junk_domain", "email": None}


def test_filter_valid_emails_dedupes():
    out = filter_valid_emails([
        "sales@abhomeinc.com", "SALES@abhomeinc.com",
        "bad@", "x@sentry.io", None, "",
    ])
    assert out == ["sales@abhomeinc.com"]


@pytest.fixture()
def qsource():
    db = SessionLocal()
    s = Source(name="qa-gate-src", url="https://example.com/qa-gate",
               status=SourceStatus.CRAWLING)
    db.add(s)
    db.commit()
    db.refresh(s)
    sid = s.id
    db.close()
    yield sid
    db = SessionLocal()
    for c in db.query(Company).filter(Company.source_id == sid).all():
        for lid in [l.id for l in db.query(Lead).filter(Lead.company_id == c.id).all()]:
            db.query(Activity).filter(Activity.lead_id == lid).delete()
            db.query(Meeting).filter(Meeting.lead_id == lid).delete()
            db.query(Outreach).filter(Outreach.lead_id == lid).delete()
            db.query(Lead).filter(Lead.id == lid).delete()
        db.query(DuplicateCandidate).filter(
            (DuplicateCandidate.company_a_id == c.id) |
            (DuplicateCandidate.company_b_id == c.id)).delete()
        from app.models.contact_item import ContactItem
        db.query(ContactItem).filter(ContactItem.company_id == c.id).delete()
        db.query(Contact).filter(Contact.company_id == c.id).delete()
        db.query(Product).filter(Product.company_id == c.id).delete()
        db.query(Company).filter(Company.id == c.id).delete()
    db.query(Source).filter(Source.id == sid).delete()
    db.commit()
    db.close()


def _thin():
    return {"company_name": "Thin Name Only", "website": None, "description": "",
            "industry": None, "country": None, "city": None,
            "products": [], "profile_url": "u",
            "emails": [], "phones": [], "whatsapp": [], "contact_page_url": None}


def _good():
    d = _thin()
    d.update({
        "company_name": "Good Proper Co",
        "website": "https://goodproper.example",
        "description": "We make proper goods for testing.",
        "country": "India",
        "products": [{"name": "Widget", "category": "Tools", "description": "",
                      "source_url": "u"}],
        "emails": ["info@goodproper.example"],
    })
    return d


def test_gate_drops_thin_row(qsource):
    from app.api.sources import persist_company
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == qsource).first()
    assert persist_company(db, s, s.url, _thin(), min_quality=0.2) is None
    assert db.query(Company).filter(Company.source_id == qsource).count() == 0
    db.close()


def test_gate_default_keeps_thin_row(qsource):
    from app.api.sources import persist_company
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == qsource).first()
    company = persist_company(db, s, s.url, _thin())
    assert company is not None
    assert (company.completeness or 0) == 0.0
    db.close()


def test_gate_keeps_proper_row(qsource):
    from app.api.sources import persist_company
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == qsource).first()
    company = persist_company(db, s, s.url, _good(), min_quality=0.2)
    assert company is not None
    assert (company.completeness or 0) >= 0.2
    contact = db.query(Contact).filter(Contact.company_id == company.id).first()
    assert contact.business_email == "info@goodproper.example"
    db.close()
