"""Phase A tests: dedup identifiers, quality fields, crawl jobs, export, analytics."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.product import Product
from app.models.activity import Activity
from app.models.meeting import Meeting
from app.models.outreach import Outreach
from app.models.crawl_job import CrawlJob
from app.models.duplicate_candidate import DuplicateCandidate
from app.services.dedup import (
    normalize_name, normalize_domain, normalize_email, normalize_phone,
    infer_company_type, completeness_score, fill_missing, flag_duplicates,
)

client = TestClient(app)


def test_normalize_name():
    assert normalize_name("Acme Ltd.") == "acme"
    assert normalize_name("  A & B Home Group  ") == "a b home group"
    assert normalize_name("Müller GmbH & Co. KG") == "m ller"
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_normalize_domain():
    assert normalize_domain("https://www.abhomeinc.com/contact") == "abhomeinc.com"
    assert normalize_domain("sales@abhomeinc.com") == "abhomeinc.com"
    assert normalize_domain("WWW.EXAMPLE.COM") == "example.com"
    assert normalize_domain(None) == ""


def test_normalize_email():
    assert normalize_email("Sales@Example.COM ") == "sales@example.com"
    assert normalize_email("a+b@example.com") == "a@example.com"
    assert normalize_email("not-an-email") == ""
    assert normalize_email(None) == ""


def test_normalize_phone():
    assert normalize_phone("+1 647-300-9043") == "+16473009043"
    assert normalize_phone("647-300-9043", default_country="1") == "+16473009043"
    assert normalize_phone("(0)1993 898319") == "01993898319"
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_infer_company_type():
    assert infer_company_type("Acme", "Leading manufacturer of furniture") == "manufacturer"
    assert infer_company_type("Acme Wholesale Ltd", "") == "wholesaler"
    assert infer_company_type("Acme", "We export worldwide") == "exporter"
    assert infer_company_type("Acme", "We do various things") == "unknown"


def test_fill_missing_never_erases():
    class T:
        description = "known"
        country = ""
        city = None
        website = None
        industry = None
        address = None
        hall = None
        booth = None
        company_type = None

    class S:
        description = "new text"
        country = "India"
        city = None
        website = "https://x.example"
        industry = None
        address = None
        hall = None
        booth = None
        company_type = "brand"

    filled = fill_missing(T(), S())
    t = T()
    fill_missing(t, S())
    assert t.description == "known"  # preserved
    assert t.country == "India" and t.website == "https://x.example"
    assert set(filled) == {"country", "website", "company_type"}


@pytest.fixture()
def two_sources_same_company():
    """Same company Shelly Table Co in two fairs (dedup candidate)."""
    db = SessionLocal()
    s1 = Source(name="qa-fair-a", url="https://example.com/qa-a", status=SourceStatus.COMPLETED)
    s2 = Source(name="qa-fair-b", url="https://example.com/qa-b", status=SourceStatus.COMPLETED)
    db.add_all([s1, s2])
    db.flush()
    c1 = Company(source_id=s1.id, company_name="Shelly Table Co",
                 website="https://shellytable.example",
                 normalized_name="shelly table co",
                 normalized_domain="shellytable.example")
    c2 = Company(source_id=s2.id, company_name="Shelly Table Co Ltd",
                 website="https://shellytable.example",
                 normalized_name="shelly table co",
                 normalized_domain="shellytable.example")
    db.add_all([c1, c2])
    db.commit()
    ids = {"s1": s1.id, "s2": s2.id, "c1": c1.id, "c2": c2.id}
    db.close()
    yield ids
    db = SessionLocal()
    db.query(DuplicateCandidate).filter(
        DuplicateCandidate.company_a_id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(DuplicateCandidate).filter(
        DuplicateCandidate.company_b_id.in_([ids["c1"], ids["c2"]])).delete()
    from app.models.contact_item import ContactItem
    db.query(ContactItem).filter(
        ContactItem.company_id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(Company).filter(Company.id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(Source).filter(Source.id.in_([ids["s1"], ids["s2"]])).delete()
    db.commit()
    db.close()


def test_flag_duplicates_exact_no_merge(two_sources_same_company):
    db = SessionLocal()
    c1 = db.query(Company).filter(Company.id == two_sources_same_company["c1"]).first()
    n = flag_duplicates(db, c1)
    assert n >= 1
    # Still two separate companies — never merged
    assert db.query(Company).filter(
        Company.id.in_([two_sources_same_company["c1"],
                        two_sources_same_company["c2"]])).count() == 2
    # Idempotent rerun creates nothing new
    assert flag_duplicates(db, c1) == 0
    db.close()


def test_duplicates_endpoint_and_resolve(two_sources_same_company):
    db = SessionLocal()
    c1 = db.query(Company).filter(Company.id == two_sources_same_company["c1"]).first()
    flag_duplicates(db, c1)
    db.close()
    r = client.get("/api/companies/duplicates")
    assert r.status_code == 200
    mine = [d for d in r.json()
            if d["company_a"]["id"] == two_sources_same_company["c1"]]
    assert len(mine) >= 1
    assert mine[0]["status"] == "pending"
    assert mine[0]["company_b"] is not None
    rid = client.post(f"/api/companies/duplicates/{mine[0]['id']}/resolve",
                      json={"status": "dismissed"})
    assert rid.status_code == 200


def test_completeness_and_type_on_save():
    from app.api.sources import persist_company
    db = SessionLocal()
    s = Source(name="qa-fair-q", url="https://example.com/qa-q", status=SourceStatus.CRAWLING)
    db.add(s)
    db.commit()
    db.refresh(s)
    company = persist_company(db, s, s.url, {
        "company_name": "Quality Manual Maker",
        "website": "https://qualitymanual.example",
        "description": "We manufacture manuals.",
        "industry": "Print",
        "country": "India",
        "city": "",
        "products": [{"name": "Manual", "category": "", "description": "", "source_url": "u"}],
        "profile_url": "u",
        "emails": ["info@qualitymanual.example"],
        "phones": [],
        "whatsapp": [],
        "contact_page_url": None,
    })
    assert company is not None
    assert company.normalized_name == "quality manual maker"
    assert company.normalized_domain == "qualitymanual.example"
    assert company.company_type == "manufacturer"
    assert 0.0 < (company.completeness or 0) <= 1.0
    # cleanup
    for lid in [l.id for l in db.query(Lead).filter(Lead.company_id == company.id).all()]:
        db.query(Activity).filter(Activity.lead_id == lid).delete()
        db.query(Meeting).filter(Meeting.lead_id == lid).delete()
        db.query(Outreach).filter(Outreach.lead_id == lid).delete()
        db.query(Lead).filter(Lead.id == lid).delete()
    db.query(DuplicateCandidate).filter(
        (DuplicateCandidate.company_a_id == company.id) |
        (DuplicateCandidate.company_b_id == company.id)).delete()
    from app.models.contact_item import ContactItem
    db.query(ContactItem).filter(ContactItem.company_id == company.id).delete()
    db.query(Contact).filter(Contact.company_id == company.id).delete()
    db.query(Product).filter(Product.company_id == company.id).delete()
    db.query(Company).filter(Company.id == company.id).delete()
    db.query(Source).filter(Source.id == s.id).delete()
    db.commit()
    db.close()


def test_crawl_jobs_endpoints_and_guard():
    db = SessionLocal()
    s = Source(name="qa-job-src", url="https://example.com/qa-job",
               status=SourceStatus.CRAWLING)
    db.add(s)
    db.flush()
    db.add(CrawlJob(source_id=s.id, url=s.url, status="CRAWLING"))
    db.commit()
    sid = s.id
    db.close()

    # Guard: duplicate crawl refused, no thread started
    r = client.post(f"/api/sources/{sid}/crawl")
    assert r.status_code == 409

    r = client.get("/api/sources/jobs?limit=5")
    assert r.status_code == 200
    assert any(j["source_id"] == sid for j in r.json())
    jid = [j for j in r.json() if j["source_id"] == sid][0]["id"]
    r = client.get(f"/api/sources/jobs/{jid}")
    assert r.status_code == 200
    assert r.json()["status"] == "CRAWLING"

    # Retry while running is refused
    r = client.post(f"/api/sources/jobs/{jid}/retry")
    assert r.status_code == 409

    db = SessionLocal()
    db.query(CrawlJob).filter(CrawlJob.source_id == sid).delete()
    db.query(Source).filter(Source.id == sid).delete()
    db.commit()
    db.close()


def test_leads_export_csv():
    r = client.get("/api/leads/export/csv?limit=5")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    text = r.text
    assert text.splitlines()[0].startswith("lead_id,company_name,contact_email")


def test_analytics_breakdowns_shape():
    for path in ["/api/analytics/companies/by-country",
                 "/api/analytics/companies/by-fair",
                 "/api/analytics/companies/by-category",
                 "/api/analytics/companies/by-type",
                 "/api/analytics/companies/contact-availability",
                 "/api/analytics/companies/completeness",
                 "/api/analytics/companies/discoveries?days=7",
                 "/api/analytics/crawling"]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert isinstance(r.json(), (list, dict)), path
    by_fair = client.get("/api/analytics/companies/by-fair").json()
    db = SessionLocal()
    from app.models.company import Company as _Company
    total = db.query(_Company).count()
    db.close()
    assert sum(f["companies"] for f in by_fair) == total
    avail = client.get("/api/analytics/companies/contact-availability").json()
    assert avail["total_companies"] >= avail["with_email"]
    assert avail["missing_contact"] >= 0


def test_company_patch_curation(two_sources_same_company):
    cid = two_sources_same_company["c1"]
    r = client.patch(f"/api/companies/{cid}",
                     json={"notes": "Called them.", "verified": True,
                           "company_type": "manufacturer"})
    assert r.status_code == 200
    assert r.json()["notes"] == "Called them."
    assert r.json()["verified"] is True
    assert r.json()["last_verified"] is not None
    r = client.patch(f"/api/companies/{cid}", json={"company_type": "nope"})
    assert r.status_code == 422
