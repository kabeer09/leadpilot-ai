"""Company filters/pagination + lead outreach-status tests."""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.product import Product
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.activity import Activity
from app.models.meeting import Meeting

client = TestClient(app)


@pytest.fixture()
def two_fairs():
    """Two sources (fairs) with companies, one with categorized products."""
    db = SessionLocal()
    s1 = Source(name="Fair Alpha", url="https://example.com/alpha", status=SourceStatus.COMPLETED)
    s2 = Source(name="Fair Beta", url="https://example.com/beta", status=SourceStatus.COMPLETED)
    db.add_all([s1, s2])
    db.flush()
    c1 = Company(source_id=s1.id, company_name="Alpha Table Co", country="India")
    c2 = Company(source_id=s2.id, company_name="Beta Chair Co", country="Germany")
    db.add_all([c1, c2])
    db.flush()
    db.add(Product(company_id=c1.id, name="Table X", category="Furniture"))
    db.add(Contact(company_id=c1.id, business_email="a@alpha.example", contact_type=ContactType.EMAIL))
    db.add(Contact(company_id=c2.id, business_email="b@beta.example", contact_type=ContactType.EMAIL))
    db.flush()
    l1 = Lead(company_id=c1.id, status=LeadStatus.SCORED, lead_score=80,
              lead_priority=LeadPriority.HIGH)
    l2 = Lead(company_id=c2.id, status=LeadStatus.SCORED, lead_score=60,
              lead_priority=LeadPriority.MEDIUM)
    db.add_all([l1, l2])
    db.flush()
    o1 = Outreach(lead_id=l1.id, channel=OutreachChannel.EMAIL, status=OutreachStatus.SENT,
                  subject="Hi", message="Hello body here for testing.",
                  sent_at=datetime.utcnow() - timedelta(hours=1))
    db.add(o1)
    db.commit()
    ids = {"s1": s1.id, "s2": s2.id, "c1": c1.id, "c2": c2.id,
           "l1": l1.id, "l2": l2.id}
    db.close()
    yield ids
    db = SessionLocal()
    for lid in (ids["l1"], ids["l2"]):
        db.query(Activity).filter(Activity.lead_id == lid).delete()
        db.query(Meeting).filter(Meeting.lead_id == lid).delete()
        db.query(Outreach).filter(Outreach.lead_id == lid).delete()
        db.query(Lead).filter(Lead.id == lid).delete()
    db.query(Contact).filter(Contact.company_id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(Product).filter(Product.company_id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(Company).filter(Company.id.in_([ids["c1"], ids["c2"]])).delete()
    db.query(Source).filter(Source.id.in_([ids["s1"], ids["s2"]])).delete()
    db.commit()
    db.close()


def test_filter_by_source(two_fairs):
    r = client.get(f"/api/companies?source_id={two_fairs['s1']}")
    assert r.status_code == 200
    names = [c["company_name"] for c in r.json()]
    assert names == ["Alpha Table Co"]
    assert r.headers.get("x-total-count") == "1"


def test_filter_by_category(two_fairs):
    r = client.get("/api/companies?category=Furniture")
    assert r.status_code == 200
    names = [c["company_name"] for c in r.json()]
    assert names == ["Alpha Table Co"]


def test_list_includes_contacts_products(two_fairs):
    r = client.get(f"/api/companies?source_id={two_fairs['s1']}")
    item = r.json()[0]
    assert item["contacts"][0]["business_email"] == "a@alpha.example"
    assert item["products"][0]["name"] == "Table X"


def test_pagination_total_header(two_fairs):
    r = client.get("/api/companies?limit=1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert int(r.headers.get("x-total-count", "0")) >= 2


def test_filters_endpoint(two_fairs):
    r = client.get("/api/companies/filters")
    assert r.status_code == 200
    data = r.json()
    assert any(s["name"] == "Fair Alpha" for s in data["sources"])
    assert "India" in data["countries"]
    assert "Furniture" in data["categories"]


def test_filter_has_contact(two_fairs):
    db = SessionLocal()
    lead = db.query(Lead).filter(Lead.id == two_fairs["l1"]).first()
    from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
    from datetime import datetime, timedelta
    db.add(Outreach(lead_id=lead.id, channel=OutreachChannel.EMAIL,
                    status=OutreachStatus.SENT, subject="Hi",
                    message="Hello body here for testing.",
                    sent_at=datetime.utcnow() - timedelta(hours=1)))
    # l1's company has email contact; l2's company has email too — drop l2's
    c2 = db.query(Contact).filter(Contact.company_id == two_fairs["c2"]).first()
    c2.business_email = None
    c2.phone = None
    db.commit()
    db.close()
    r = client.get("/api/companies?has_contact=true")
    assert r.status_code == 200
    names = [c["company_name"] for c in r.json()]
    assert "Alpha Table Co" in names
    assert "Beta Chair Co" not in names


def test_lead_last_outreach_sent(two_fairs):
    r = client.get("/api/leads?limit=200")
    assert r.status_code == 200
    by_id = {l["id"]: l for l in r.json()}
    assert by_id[two_fairs["l1"]]["last_outreach"]["status"] == "SENT"
    assert by_id[two_fairs["l1"]]["last_outreach"]["channel"] == "EMAIL"
    assert by_id[two_fairs["l2"]]["last_outreach"] is None
