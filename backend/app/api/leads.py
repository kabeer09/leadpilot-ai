"""Lead endpoints."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.activity import Activity
from app.schemas.lead import LeadResponse, LeadDetailResponse, LeadListResponse
from app.services.lead_scoring import score_lead as run_scoring

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("", response_model=list[LeadListResponse])
def list_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=2000),
    status: str | None = None,
    priority: str | None = None,
    source_id: int | None = None,
    category: str | None = None,
    email_filter: str | None = Query(None, description="eligible|sent|not_sent|followup_due"),
    sort: str | None = None,
    db: Session = Depends(get_db),
):
    """List leads with optional filtering (includes company + contact)."""
    from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
    from app.models.product import Product
    from app.config import settings as _settings

    query = db.query(Lead).options(
        selectinload(Lead.company).selectinload(Company.products),
        selectinload(Lead.contact),
    )
    if status:
        query = query.filter(Lead.status == status)
    if priority:
        query = query.filter(Lead.lead_priority == priority)
    if source_id:
        query = query.join(Company, Company.id == Lead.company_id).filter(
            Company.source_id == source_id)
    if category:
        query = query.filter(Lead.company_id.in_(
            db.query(Product.company_id).filter(Product.category.ilike(f"%{category}%"))))

    # Email eligibility filters
    if email_filter == "eligible":
        # Leads that CAN receive email: not sent/replied/bounced/etc, have business email
        blocked = [LeadStatus.EMAIL_SENT, LeadStatus.REPLIED, LeadStatus.UNSUBSCRIBED,
                   LeadStatus.SUPPRESSED, LeadStatus.BOUNCED, LeadStatus.NOT_INTERESTED,
                   LeadStatus.FOLLOWUP_DUE, LeadStatus.WHATSAPP_SENT]
        query = query.filter(~Lead.status.in_(blocked))
        query = query.filter(Lead.contact_id.in_(
            db.query(Contact.id).filter(Contact.business_email.isnot(None))))
    elif email_filter == "sent":
        # Leads that already received an email
        query = query.filter(Lead.status.in_([
            LeadStatus.EMAIL_SENT, LeadStatus.REPLIED, LeadStatus.INTERESTED,
            LeadStatus.MEETING_PROPOSED, LeadStatus.MEETING_BOOKED,
            LeadStatus.FOLLOWUP_DUE, LeadStatus.WHATSAPP_SENT,
            LeadStatus.NOT_INTERESTED, LeadStatus.UNSUBSCRIBED,
            LeadStatus.BOUNCED, LeadStatus.SUPPRESSED,
        ]))
    elif email_filter == "not_sent":
        # Leads that never received any email
        sent_leads = db.query(Outreach.lead_id).filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        ).distinct()
        query = query.filter(~Lead.id.in_(sent_leads))
    elif email_filter == "followup_due":
        # Leads whose 24h follow-up is due (email sent >24h ago, no reply)
        cutoff = datetime.utcnow() - timedelta(hours=_settings.FOLLOWUP_DELAY_HOURS)
        sent_email_leads = (
            db.query(Outreach.lead_id)
            .filter(
                Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
                Outreach.sent_at < cutoff,
            )
            .distinct()
        )
        # Exclude leads with any reply or follow-up already
        replied_leads = db.query(Outreach.lead_id).filter(
            Outreach.status.in_([OutreachStatus.REPLIED, OutreachStatus.BOUNCED])
        ).distinct()
        followup_sent = db.query(Outreach.lead_id).filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        ).distinct()
        # Has a second email sent (follow-up) — exclude
        from sqlalchemy import func
        followup_leads = (
            db.query(Outreach.lead_id)
            .filter(
                Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
            )
            .group_by(Outreach.lead_id)
            .having(func.count(Outreach.id) >= 2)
            .distinct()
        )
        query = query.filter(
            Lead.id.in_(sent_email_leads),
            ~Lead.id.in_(replied_leads),
            ~Lead.id.in_(followup_leads),
        )

    if sort == "score_desc":
        query = query.order_by(Lead.lead_score.desc())
    elif sort == "score_asc":
        query = query.order_by(Lead.lead_score.asc())
    elif sort == "name":
        query = query.join(Company, Company.id == Lead.company_id).order_by(
            Company.company_name.asc())
    elif sort == "updated_desc":
        query = query.order_by(Lead.updated_at.desc())
    else:
        query = query.order_by(Lead.created_at.desc())
    leads = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
    # Attach latest outreach per lead (email sent or not, at a glance)
    if leads:
        latest = (
            db.query(Outreach)
            .filter(Outreach.lead_id.in_([l.id for l in leads]))
            .order_by(Outreach.lead_id, Outreach.created_at.desc())
            .all()
        )
        seen: set[int] = set()
        by_lead: dict[int, object] = {}
        for o in latest:
            if o.lead_id not in seen:
                seen.add(o.lead_id)
                by_lead[o.lead_id] = o
        for lead in leads:
            lead.last_outreach = by_lead.get(lead.id)
    return leads


@router.get("/export/csv")
def export_leads_csv(
    status: str | None = None,
    priority: str | None = None,
    source_id: int | None = None,
    category: str | None = None,
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """Export filtered leads to CSV (respects active filters)."""
    import csv as _csv
    import io as _io
    from fastapi.responses import StreamingResponse
    from app.models.product import Product
    from app.models.outreach import OutreachChannel, OutreachStatus

    query = db.query(Lead).options(
        selectinload(Lead.company),
        selectinload(Lead.contact),
    )
    if status:
        query = query.filter(Lead.status == status)
    if priority:
        query = query.filter(Lead.lead_priority == priority)
    if source_id:
        query = query.join(Company, Company.id == Lead.company_id).filter(
            Company.source_id == source_id)
    if category:
        query = query.filter(Lead.company_id.in_(
            db.query(Product.company_id).filter(Product.category.ilike(f"%{category}%"))))
    leads = query.order_by(Lead.created_at.desc()).limit(limit).all()

    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["lead_id", "company_name", "contact_email", "alternate_email",
                     "phone", "whatsapp", "website", "country", "city",
                     "product_category", "lead_score", "lead_priority",
                     "status", "source_fair", "follow_up_count", "updated_at"])
    for lead in leads:
        company = lead.company
        contact = lead.contact
        # Count follow-up emails for this lead
        followup_count = 0
        sent_emails = [o for o in lead.outreach if o.channel == OutreachChannel.EMAIL and o.status == OutreachStatus.SENT]
        if len(sent_emails) > 1:
            followup_count = len(sent_emails) - 1
        writer.writerow([
            lead.id,
            company.company_name if company else "",
            contact.business_email if contact and contact.business_email else "",
            contact.alternate_email if contact and contact.alternate_email else "",
            contact.phone if contact and contact.phone else "",
            contact.whatsapp_number if contact and contact.whatsapp_number else "",
            company.website if company and company.website else "",
            company.country if company and company.country else "",
            company.city if company and company.city else "",
            company.industry if company and company.industry else "",
            lead.lead_score,
            lead.lead_priority.value if lead.lead_priority else "",
            lead.status.value if lead.status else "",
            company.exhibition_name if company and company.exhibition_name else "",
            followup_count,
            lead.updated_at.isoformat() if lead.updated_at else "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


@router.get("/{lead_id}", response_model=LeadDetailResponse)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """Get a single lead with full details."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/{lead_id}/timeline")
def lead_timeline(lead_id: int, db: Session = Depends(get_db)):
    """Full chronological history: outreach, replies, follow-ups, meetings, notes.

    Every entry carries its timestamp, actor/provider result and links
    (provider message ID, Gmail thread URL) where available.
    """
    from app.models.outreach import Outreach, OutreachChannel
    from app.models.meeting import Meeting
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    events: list[dict] = []
    for o in (db.query(Outreach).filter(Outreach.lead_id == lead_id)
              .order_by(Outreach.created_at.asc()).all()):
        thread_url = (f"https://mail.google.com/mail/u/0/#inbox/{o.provider_thread_id}"
                      if o.provider_thread_id else None)
        events.append({
            "at": o.sent_at or o.created_at, "kind": "outreach",
            "channel": o.channel.value, "status": o.status.value,
            "subject": o.subject, "message": o.message,
            "provider_message_id": o.provider_message_id,
            "thread_url": thread_url,
            "response_at": o.response_at, "error": o.error,
            "follow_up_count": o.follow_up_count,
            "template": o.template_name,
        })
    for a in (db.query(Activity).filter(Activity.lead_id == lead_id)
              .order_by(Activity.created_at.asc()).all()):
        events.append({
            "at": a.created_at, "kind": "activity",
            "activity_type": a.activity_type, "description": a.description,
            "metadata": a.metadata_,
        })
    for m in (db.query(Meeting).filter(Meeting.lead_id == lead_id)
              .order_by(Meeting.created_at.asc()).all()):
        events.append({
            "at": m.created_at, "kind": "meeting",
            "status": m.status, "start_time": m.start_time,
            "end_time": m.end_time, "meet_url": m.meet_url,
        })
    events.sort(key=lambda e: str(e["at"] or ""))
    return {"lead_id": lead_id, "status": lead.status.value,
            "score": lead.lead_score, "events": events}


class ClassifyReplyRequest(BaseModel):
    body: str
    from_address: str | None = None
    subject: str | None = None


@router.post("/{lead_id}/classify-reply")
def classify_reply_endpoint(lead_id: int, payload: ClassifyReplyRequest,
                            db: Session = Depends(get_db)):
    """Manually classify a reply pasted by a human (same AI+rules routing)."""
    from app.models.outreach import Outreach
    from app.services.reply_processing import route_reply

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    latest = (
        db.query(Outreach)
        .filter(Outreach.lead_id == lead_id)
        .order_by(Outreach.created_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail="No outreach found for lead")

    category = route_reply(db, lead, latest, payload.body,
                           payload.from_address, payload.subject)
    return {"lead_id": lead_id, "category": category, "status": lead.status.value}


def _company_data(lead: Lead) -> dict:
    company = lead.company
    return {
        "company_name": company.company_name if company else "Unknown",
        "description": (company.description if company else None) or "",
        "products": [p.name for p in company.products] if company else [],
        "industry": company.industry if company else None,
        "country": company.country if company else None,
    }


@router.post("/{lead_id}/score")
def score_lead_endpoint(lead_id: int, db: Session = Depends(get_db)):
    """(Re)run deterministic lead scoring."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = run_scoring(lead.company, lead.contact)
    lead.lead_score = result.score
    lead.lead_priority = LeadPriority(result.priority)
    if lead.status == LeadStatus.NEW:
        lead.status = LeadStatus.SCORED
    lead.ai_reason = "\n".join(result.reasons)
    db.add(Activity(
        lead_id=lead.id,
        activity_type="LEAD_RESCORDED",
        description=f"Lead rescored: {result.score}/100 ({result.priority})",
    ))
    db.commit()
    return {"lead_id": lead_id, "score": result.score,
            "priority": result.priority, "reasons": result.reasons}


@router.post("/{lead_id}/generate-email")
def generate_email_endpoint(lead_id: int, db: Session = Depends(get_db)):
    """Generate a draft email with Ollama AI (fallback template if AI fails).

    Returns the draft without queueing it. Use POST /api/outreach
    (or /{lead_id}/queue-email) to queue it for n8n sending.
    """
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.contact or not lead.contact.business_email:
        raise HTTPException(status_code=422, detail="Lead has no business email")

    from app.services.ai_generator import generate_email
    from app.services.ai_validator import validate_email, get_fallback_email
    from app.services.seller import get_seller_dict

    seller = get_seller_dict(db)
    company_data = _company_data(lead)
    draft = generate_email(company_data, seller)
    used_fallback = False
    if not draft or not validate_email(draft["subject"], draft["body"], company_data, seller).is_valid:
        draft = get_fallback_email(company_data, seller)
        used_fallback = True

    lead.status = LeadStatus.EMAIL_GENERATED
    lead.ai_summary = f"Draft ready: {draft['subject']}"
    db.add(Activity(
        lead_id=lead.id,
        activity_type="EMAIL_GENERATED",
        description=f"Email draft generated ({'fallback template' if used_fallback else 'AI'})",
    ))
    db.commit()
    return {"lead_id": lead_id, "subject": draft["subject"],
            "body": draft["body"], "used_fallback": used_fallback}


@router.post("/{lead_id}/validate")
def validate_email_endpoint(lead_id: int, db: Session = Depends(get_db)):
    """Validate the pending queued draft, else a fresh AI/fallback draft."""
    from app.models.outreach import Outreach, OutreachChannel, OutreachStatus
    from app.services.ai_generator import generate_email
    from app.services.ai_validator import validate_email, get_fallback_email
    from app.services.seller import get_seller_dict

    seller = get_seller_dict(db)
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    company_data = _company_data(lead)
    pending = (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead.id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.PENDING,
        )
        .order_by(Outreach.created_at.desc())
        .first()
    )
    if pending:
        subject, body = pending.subject, pending.message
    else:
        draft = generate_email(company_data, seller)
        if draft:
            subject, body = draft["subject"], draft["body"]
        else:
            fb = get_fallback_email(company_data, seller)
            subject, body = fb["subject"], fb["body"]

    result = validate_email(subject, body, company_data, seller)
    if result.is_valid and lead.status in (LeadStatus.EMAIL_GENERATED, LeadStatus.SCORED):
        lead.status = LeadStatus.EMAIL_VALIDATED
        db.add(Activity(
            lead_id=lead.id,
            activity_type="EMAIL_VALIDATED",
            description="Email draft passed validation",
        ))
        db.commit()
    return {"lead_id": lead_id, **result.to_dict()}


@router.post("/{lead_id}/queue-email")
def queue_email_endpoint(lead_id: int, db: Session = Depends(get_db)):
    """Generate (AI + fallback), validate, and queue the email for n8n.

    One-shot replacement for the generate → validate → queue clicks.
    """
    from app.services.ai_generator import generate_email
    from app.services.ai_validator import validate_email, get_fallback_email
    from app.services.outreach import queue_email_for_lead
    from app.services.seller import get_seller_dict

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    seller = get_seller_dict(db)
    company_data = _company_data(lead)
    draft = generate_email(company_data, seller)
    if draft and validate_email(draft["subject"], draft["body"], company_data, seller).is_valid:
        subject, message = draft["subject"], draft["body"]
    else:
        fb = get_fallback_email(company_data, seller)
        subject, message = fb["subject"], fb["body"]

    outreach, error = queue_email_for_lead(db, lead, subject, message)
    if error:
        raise HTTPException(status_code=409 if "already has" in error else 422, detail=error)
    return {"lead_id": lead_id, "outreach_id": outreach.id,
            "subject": outreach.subject, "status": "queued"}
