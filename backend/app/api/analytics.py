"""Analytics endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead, LeadStatus
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.meeting import Meeting
from app.schemas.analytics import AnalyticsOverview

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(db: Session = Depends(get_db)):
    """Return real analytics from the database."""
    total_companies = db.query(func.count(Company.id)).scalar() or 0
    total_contacts = db.query(func.count(Contact.id)).scalar() or 0
    total_leads = db.query(func.count(Lead.id)).scalar() or 0

    emails_sent = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL, Outreach.status == OutreachStatus.SENT)
        .scalar()
    ) or 0

    emails_failed = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL, Outreach.status == OutreachStatus.FAILED)
        .scalar()
    ) or 0

    replies = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.status == OutreachStatus.REPLIED)
        .scalar()
    ) or 0

    reply_rate = round((replies / emails_sent * 100), 1) if emails_sent > 0 else 0.0

    interested = (
        db.query(func.count(Lead.id)).filter(Lead.status == LeadStatus.INTERESTED).scalar()
    ) or 0

    meetings_booked = (
        db.query(func.count(Meeting.id))
        .filter(Meeting.status.in_(["CONFIRMED", "COMPLETED"]))
        .scalar()
    ) or 0

    qualified = (
        db.query(func.count(Lead.id)).filter(Lead.status == LeadStatus.QUALIFIED).scalar()
    ) or 0

    from datetime import datetime as _dt
    start_of_day = _dt.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    followups_due = (
        db.query(func.count(Lead.id)).filter(Lead.status == LeadStatus.FOLLOWUP_DUE).scalar()
    ) or 0

    whatsapp_sent = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.WHATSAPP, Outreach.status == OutreachStatus.SENT)
        .scalar()
    ) or 0

    emails_sent_today = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
                Outreach.sent_at >= start_of_day)
        .scalar()
    ) or 0

    replies_today = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.status == OutreachStatus.REPLIED,
                Outreach.response_at >= start_of_day)
        .scalar()
    ) or 0

    email_followups_sent = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
                Outreach.follow_up_count >= 2)
        .scalar()
    ) or 0

    unsubscribed = (
        db.query(func.count(Lead.id))
        .filter(Lead.status.in_([LeadStatus.UNSUBSCRIBED, LeadStatus.SUPPRESSED]))
        .scalar()
    ) or 0

    try:
        from app.services.outreach import count_email_followups_due
        email_followups_due = count_email_followups_due(db)
    except Exception:
        email_followups_due = 0

    return AnalyticsOverview(
        total_companies=total_companies,
        total_contacts=total_contacts,
        total_leads=total_leads,
        emails_sent=emails_sent,
        emails_failed=emails_failed,
        replies=replies,
        reply_rate=reply_rate,
        interested=interested,
        meetings_booked=meetings_booked,
        qualified=qualified,
        followups_due=followups_due,
        whatsapp_sent=whatsapp_sent,
        emails_sent_today=emails_sent_today,
        replies_today=replies_today,
        email_followups_due=email_followups_due,
        email_followups_sent=email_followups_sent,
        unsubscribed=unsubscribed,
    )


@router.get("/pipeline")
def analytics_pipeline(db: Session = Depends(get_db)):
    """Workflow stages 1-6: discovered → profiles → websites → validated → saved → displayed."""
    from app.models.company import EnrichmentStatus
    from app.models.product import Product
    total = db.query(func.count(Company.id)).scalar() or 0
    with_website = db.query(func.count(Company.id)).filter(Company.website.isnot(None)).scalar() or 0
    products_total = db.query(func.count(Product.id)).scalar() or 0
    enriched = db.query(func.count(Company.id)).filter(
        Company.enrichment_status == EnrichmentStatus.ENRICHED.value).scalar() or 0
    with_email = db.query(func.count(Contact.id)).filter(Contact.business_email.isnot(None)).scalar() or 0
    with_phone = db.query(func.count(Contact.id)).filter(Contact.phone.isnot(None)).scalar() or 0
    scored = db.query(func.count(Lead.id)).filter(Lead.status != LeadStatus.NEW).scalar() or 0
    return {
        "stages": [
            {"step": 1, "label": "Discover exhibitor listings", "count": total},
            {"step": 2, "label": "Open each exhibitor profile", "count": total,
             "detail": {"name": total, "products": products_total, "websites": with_website}},
            {"step": 3, "label": "Visit the company's website", "count": with_website},
            {"step": 4, "label": "Extract and validate business contacts",
             "count": with_email, "detail": {"emails": with_email, "phones": with_phone}},
            {"step": 5, "label": "Save to PostgreSQL",
             "count": total, "detail": {"enriched": enriched, "scored_leads": scored}},
            {"step": 6, "label": "Display companies in the dashboard", "count": total},
        ],
    }


@router.get("/email-match")
def analytics_email_match(limit: int = 200, db: Session = Depends(get_db)):
    """Domain-match audit: does each contact email belong to the company website?"""
    from app.services.contact_validation import check_email_match
    rows = (
        db.query(Contact, Company)
        .join(Company, Company.id == Contact.company_id)
        .filter(Contact.business_email.isnot(None))
        .limit(limit)
        .all()
    )
    matched = mismatched = 0
    samples: list[dict] = []
    for contact, company in rows:
        res = check_email_match(contact.business_email, company.website)
        if res["match"]:
            matched += 1
        else:
            mismatched += 1
            if len(samples) < 20:
                samples.append({
                    "company": company.company_name,
                    "website": company.website,
                    "email": contact.business_email,
                    "alternate": contact.alternate_email,
                    "reason": res["reason"],
                })
    total = matched + mismatched
    return {"checked": total, "matched": matched, "mismatched": mismatched,
            "match_rate": round(matched / total * 100, 1) if total else 0.0,
            "mismatch_samples": samples}


def _breakdown(db: Session, column, label: str, limit: int = 20,
               source_id: int | None = None) -> list[dict]:
    """Generic top-N breakdown helper (real DB counts, NULL-safe)."""
    q = db.query(column.label("k"), func.count(Company.id).label("v"))
    if source_id:
        q = q.filter(Company.source_id == source_id)
    q = q.filter(column.isnot(None), column != "")
    q = q.group_by(column).order_by(func.count(Company.id).desc()).limit(limit)
    return [{"label": (row.k or "Unknown"), "count": row.v} for row in q.all()]


@router.get("/companies/by-country")
def analytics_by_country(source_id: int | None = None, limit: int = 20,
                         db: Session = Depends(get_db)):
    """Companies by country (real counts)."""
    return _breakdown(db, Company.country, "country", limit, source_id)


@router.get("/companies/by-fair")
def analytics_by_fair(db: Session = Depends(get_db)):
    """Unique companies attributed to each source/fair."""
    from app.models.source import Source
    rows = (
        db.query(Source.id, Source.name, func.count(Company.id))
        .outerjoin(Company, Company.source_id == Source.id)
        .group_by(Source.id, Source.name)
        .order_by(func.count(Company.id).desc())
        .all()
    )
    return [{"source_id": sid, "fair": name, "companies": count}
            for sid, name, count in rows]


@router.get("/companies/by-category")
def analytics_by_category(source_id: int | None = None, limit: int = 20,
                          db: Session = Depends(get_db)):
    """Companies by product category (from product rows)."""
    from app.models.product import Product
    q = db.query(Product.category.label("k"), func.count(
        func.distinct(Product.company_id)).label("v"))
    if source_id:
        q = q.join(Company, Company.id == Product.company_id).filter(
            Company.source_id == source_id)
    q = q.filter(Product.category.isnot(None), Product.category != "")
    q = q.group_by(Product.category).order_by(
        func.count(func.distinct(Product.company_id)).desc()).limit(limit)
    return [{"label": (r.k or "Unknown"), "companies": r.v} for r in q.all()]


@router.get("/companies/by-type")
def analytics_by_type(source_id: int | None = None, db: Session = Depends(get_db)):
    """Companies by company type (manufacturer/wholesaler/…/unknown)."""
    q = db.query(Company.company_type.label("k"),
                 func.count(Company.id).label("v"))
    if source_id:
        q = q.filter(Company.source_id == source_id)
    q = q.group_by(Company.company_type).order_by(func.count(Company.id).desc())
    out = []
    for r in q.all():
        out.append({"label": r.k or "unknown", "count": r.v})
    return out


@router.get("/companies/contact-availability")
def analytics_contact_availability(source_id: int | None = None,
                                   db: Session = Depends(get_db)):
    """Email/phone/website/product availability (real counts)."""
    from app.models.product import Product
    cq = db.query(Company)
    if source_id:
        cq = cq.filter(Company.source_id == source_id)
    total = cq.count()
    with_website = cq.filter(Company.website.isnot(None)).count()
    email = db.query(func.count(func.distinct(Contact.company_id))).filter(
        Contact.business_email.isnot(None))
    phone = db.query(func.count(func.distinct(Contact.company_id))).filter(
        Contact.phone.isnot(None))
    any_contact = db.query(func.count(func.distinct(Contact.company_id)))
    with_products = db.query(func.count(func.distinct(Product.company_id)))
    if source_id:
        email = email.join(Company, Company.id == Contact.company_id).filter(
            Company.source_id == source_id)
        phone = phone.join(Company, Company.id == Contact.company_id).filter(
            Company.source_id == source_id)
        any_contact = any_contact.join(
            Company, Company.id == Contact.company_id).filter(
            Company.source_id == source_id)
        with_products = with_products.join(
            Company, Company.id == Product.company_id).filter(
            Company.source_id == source_id)
    with_any = any_contact.scalar() or 0
    return {
        "total_companies": total,
        "with_email": email.scalar() or 0,
        "with_phone": phone.scalar() or 0,
        "with_website": with_website,
        "with_products": with_products.scalar() or 0,
        "missing_contact": max(0, total - with_any),
    }


@router.get("/companies/completeness")
def analytics_completeness(source_id: int | None = None, db: Session = Depends(get_db)):
    """Data-completeness distribution (buckets of the 0-1 score)."""
    q = db.query(Company.completeness)
    if source_id:
        q = q.filter(Company.source_id == source_id)
    buckets = {"0-25%": 0, "25-50%": 0, "50-75%": 0, "75-100%": 0, "unscored": 0}
    for (score,) in q.all():
        if score is None:
            buckets["unscored"] += 1
        elif score < 0.25:
            buckets["0-25%"] += 1
        elif score < 0.5:
            buckets["25-50%"] += 1
        elif score < 0.75:
            buckets["50-75%"] += 1
        else:
            buckets["75-100%"] += 1
    return [{"bucket": k, "count": v} for k, v in buckets.items()]


@router.get("/companies/discoveries")
def analytics_discoveries(days: int = 30, source_id: int | None = None,
                          db: Session = Depends(get_db)):
    """Companies discovered per day (recent window)."""
    from datetime import datetime, timedelta
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 365)))
    q = db.query(func.date(Company.created_at).label("d"),
                 func.count(Company.id).label("v")).filter(Company.created_at >= since)
    if source_id:
        q = q.filter(Company.source_id == source_id)
    q = q.group_by(func.date(Company.created_at)).order_by("d")
    return [{"date": str(r.d), "companies": r.v} for r in q.all()]


@router.get("/trends")
def analytics_trends(days: int = 30, db: Session = Depends(get_db)):
    """Daily activity trends: discovered, sent, replies, bounces, follow-ups.

    Reply rate per day uses that day's sent-email cohort as denominator.
    """
    from datetime import datetime, timedelta
    from app.models.company import Company as _Company
    days = max(1, min(days, 365))
    since = datetime.utcnow() - timedelta(days=days)
    sent = dict(
        db.query(func.date(Outreach.sent_at).label("d"), func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
                Outreach.sent_at >= since)
        .group_by(func.date(Outreach.sent_at)).all())
    replies = dict(
        db.query(func.date(Outreach.response_at).label("d"), func.count(Outreach.id))
        .filter(Outreach.status == OutreachStatus.REPLIED,
                Outreach.response_at >= since)
        .group_by(func.date(Outreach.response_at)).all())
    bounced = dict(
        db.query(func.date(Outreach.response_at).label("d"), func.count(Outreach.id))
        .filter(Outreach.status == OutreachStatus.BOUNCED,
                Outreach.response_at >= since)
        .group_by(func.date(Outreach.response_at)).all())
    discovered = dict(
        db.query(func.date(_Company.created_at).label("d"), func.count(_Company.id))
        .filter(_Company.created_at >= since)
        .group_by(func.date(_Company.created_at)).all())
    def _get(bucket: dict, day):
        for k in (day, str(day), day.isoformat()):
            if k in bucket:
                return bucket[k]
        return 0

    out = []
    for i in range(days):
        day = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
        s, r, b, d = _get(sent, day), _get(replies, day), _get(bounced, day), _get(discovered, day)
        out.append({"date": day.isoformat(), "discovered": d, "sent": s,
                    "replies": r, "bounced": b,
                    "reply_rate": round(r / s * 100, 1) if s else 0.0})
    return out


@router.get("/crawling")
def analytics_crawling(db: Session = Depends(get_db)):
    """Crawl success vs failure + job totals (real records)."""
    from app.models.crawl_job import CrawlJob
    total = db.query(func.count(CrawlJob.id)).scalar() or 0
    by_status = dict(
        db.query(CrawlJob.status, func.count(CrawlJob.id)).group_by(CrawlJob.status).all())
    return {
        "total_jobs": total,
        "by_status": by_status,
        "successful": by_status.get("COMPLETED", 0),
        "failed": by_status.get("FAILED", 0),
        "running": by_status.get("CRAWLING", 0),
    }
