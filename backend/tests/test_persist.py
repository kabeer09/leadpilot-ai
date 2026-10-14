"""Incremental crawl persistence tests (dashboard fills during crawl)."""
import pytest
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead, LeadStatus
from app.models.product import Product
from app.models.activity import Activity
from app.models.meeting import Meeting
from app.models.outreach import Outreach
from app.api.sources import persist_company, persist_enrichment
from app.services.crawler import ExhibitorCrawler


@pytest.fixture()
def source():
    db = SessionLocal()
    s = Source(name="Persist Fair", url="https://example.com/fair",
               status=SourceStatus.CRAWLING)
    db.add(s)
    db.commit()
    db.refresh(s)
    sid = s.id
    db.close()
    yield sid
    db = SessionLocal()
    cids = [c.id for c in db.query(Company).filter(Company.source_id == sid).all()]
    for cid in cids:
        lids = [l.id for l in db.query(Lead).filter(Lead.company_id == cid).all()]
        for lid in lids:
            db.query(Activity).filter(Activity.lead_id == lid).delete()
            db.query(Meeting).filter(Meeting.lead_id == lid).delete()
            db.query(Outreach).filter(Outreach.lead_id == lid).delete()
            db.query(Lead).filter(Lead.id == lid).delete()
        from app.models.contact_item import ContactItem
        from app.models.duplicate_candidate import DuplicateCandidate
        db.query(ContactItem).filter(ContactItem.company_id == cid).delete()
        db.query(DuplicateCandidate).filter(
            (DuplicateCandidate.company_a_id == cid) |
            (DuplicateCandidate.company_b_id == cid)).delete()
        db.query(Contact).filter(Contact.company_id == cid).delete()
        db.query(Product).filter(Product.company_id == cid).delete()
        db.query(Company).filter(Company.id == cid).delete()
    db.query(Source).filter(Source.id == sid).delete()
    db.commit()
    db.close()


def _data(**over):
    d = {
        "company_name": "Persist Co",
        "website": "https://persist.example",
        "description": "A test company",
        "industry": "Decor",
        "country": "India",
        "city": "Moradabad",
        "hall": "1",
        "booth": "A1",
        "products": [{"name": "Vase", "category": "Decor", "description": "", "source_url": "u"}],
        "profile_url": "https://example.com/fair",
        "emails": [],
        "phones": [],
        "whatsapp": [],
        "contact_page_url": None,
    }
    d.update(over)
    return d


def test_persist_company_saves_all(source):
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == source).first()
    company = persist_company(db, s, s.url, _data())
    assert company is not None
    assert db.query(Product).filter(Product.company_id == company.id).count() == 1
    lead = db.query(Lead).filter(Lead.company_id == company.id).first()
    assert lead is not None and lead.status == LeadStatus.SCORED
    assert db.query(Contact).filter(Contact.company_id == company.id).count() == 0
    db.close()


def test_persist_company_idempotent(source):
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == source).first()
    c1 = persist_company(db, s, s.url, _data())
    c2 = persist_company(db, s, s.url, _data())
    assert c1.id == c2.id
    assert db.query(Company).filter(Company.source_id == source).count() == 1
    db.close()


def test_persist_company_with_directory_contact(source):
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == source).first()
    company = persist_company(db, s, s.url,
                              _data(emails=["dir@persist.example"], phones=["+911234567890"]))
    contact = db.query(Contact).filter(Contact.company_id == company.id).first()
    assert contact.business_email == "dir@persist.example"
    assert contact.email_source == "directory"
    db.close()


def test_persist_enrichment_merges_website_email(source):
    db = SessionLocal()
    s = db.query(Source).filter(Source.id == source).first()
    persist_company(db, s, s.url, _data(emails=["dir@other.com"]))
    persist_enrichment(db, s, s.url, _data(emails=["sales@persist.example"]))
    company = db.query(Company).filter(Company.source_id == source).first()
    contact = db.query(Contact).filter(Contact.company_id == company.id).first()
    # website-domain match wins primary, directory kept as alternate
    assert contact.business_email == "sales@persist.example"
    assert contact.alternate_email == "dir@other.com"
    assert contact.email_source == "website"
    db.close()


def test_crawler_emit_wiring():
    events = []
    crawler = ExhibitorCrawler(start_url="https://example.com/x",
                               progress_cb=lambda e, d: events.append((e, d["company_name"])))
    crawler._emit("company", {"company_name": "A"})
    crawler._emit("enriched", {"company_name": "B"})
    assert events == [("company", "A"), ("enriched", "B")]


def test_crawler_emit_never_raises():
    def bad_cb(event, data):
        raise RuntimeError("boom")
    crawler = ExhibitorCrawler(start_url="https://example.com/x", progress_cb=bad_cb)
    crawler._emit("company", {"company_name": "A"})  # must not raise


def test_concurrent_persist_no_duplicates():
    """8 threads persisting the same company → exactly 1 row (lock-safe)."""
    import threading
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
    from app.api.sources import persist_company

    db = SessionLocal()
    s = Source(name="qa-conc-src", url="https://example.com/qa-conc",
               status=SourceStatus.CRAWLING)
    db.add(s)
    db.commit()
    db.refresh(s)
    sid, surl = s.id, s.url
    lock = threading.Lock()

    data = {
        "company_name": "Concurrent Co", "website": "https://concurrent.example",
        "description": "Race test company.", "industry": None,
        "country": "India", "city": None,
        "products": [{"name": "W", "category": "", "description": "", "source_url": "u"}],
        "profile_url": surl,
        "emails": ["info@concurrent.example"], "phones": [], "whatsapp": [],
        "contact_page_url": None,
    }

    # One shared session behind a lock — mirrors run_full_crawl.
    shared = SessionLocal()
    src = shared.query(Source).filter(Source.id == sid).first()
    errors = []

    def worker():
        try:
            with lock:
                persist_company(shared, src, surl, data)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    shared.close()

    assert errors == []
    db2 = SessionLocal()
    rows = db2.query(Company).filter(Company.source_id == sid).all()
    assert len(rows) == 1
    assert db2.query(Lead).filter(Lead.company_id == rows[0].id).count() == 1
    # cleanup
    for lid in [l.id for l in db2.query(Lead).filter(Lead.company_id == rows[0].id).all()]:
        db2.query(Activity).filter(Activity.lead_id == lid).delete()
        db2.query(Meeting).filter(Meeting.lead_id == lid).delete()
        db2.query(Outreach).filter(Outreach.lead_id == lid).delete()
        db2.query(Lead).filter(Lead.id == lid).delete()
    db2.query(DuplicateCandidate).filter(
        (DuplicateCandidate.company_a_id == rows[0].id) |
        (DuplicateCandidate.company_b_id == rows[0].id)).delete()
    from app.models.contact_item import ContactItem
    db2.query(ContactItem).filter(ContactItem.company_id == rows[0].id).delete()
    db2.query(Contact).filter(Contact.company_id == rows[0].id).delete()
    db2.query(Product).filter(Product.company_id == rows[0].id).delete()
    db2.query(Company).filter(Company.id == rows[0].id).delete()
    db2.query(Source).filter(Source.id == sid).delete()
    db2.commit()
    db2.close()
    db.close()
