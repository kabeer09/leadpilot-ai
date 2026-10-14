"""Outreach endpoints — the n8n ↔ LeadPilot contract (Phase 5).

n8n loop:
  1. GET /api/outreach/ready        → poll queued emails (includes to_email/subject/message)
  2. Gmail node sends each item
  3. POST /api/outreach/{id}/sent   → ack (idempotent)
     POST /api/outreach/{id}/failed → error branch
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging
import threading
from app.database import get_db
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.google_account import GoogleAccount
from app.models.company import Company
from app.models.contact import Contact
from app.models.lead import Lead, LeadStatus
from app.models.activity import Activity
from app.schemas.lead import OutreachResponse
from app.services.outreach import (
    build_n8n_payload,
    is_outreach_payload_sendable,
    apply_daily_cap,
    is_email_ready_to_send,
    mark_outreach_sent,
    mark_outreach_failed,
    queue_email_for_lead,
    queue_whatsapp_followup,
    find_followup_due_leads,
    scan_and_queue_followups,
    render_template,
    sendable_leads,
    get_active_account,
    ensure_opt_out,
)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])

logger = logging.getLogger(__name__)


class QueueEmailRequest(BaseModel):
    lead_id: int
    subject: str | None = None
    message: str | None = None


class SentAckRequest(BaseModel):
    message_id: str | None = None


class FailedRequest(BaseModel):
    error: str = "Unknown send error"


@router.get("", response_model=list[OutreachResponse])
def list_outreach(
    status: str | None = None,
    channel: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List outreach items (dashboard / debugging)."""
    query = db.query(Outreach)
    if status:
        query = query.filter(Outreach.status == status)
    if channel:
        query = query.filter(Outreach.channel == channel)
    return query.order_by(Outreach.created_at.desc()).limit(limit).all()


@router.get("/ready")
def get_ready_outreach(channel: str | None = None, limit: int = Query(100, ge=1, le=500),
                       db: Session = Depends(get_db)):
    """Get outreach items ready to be sent (polled by n8n).

    Guardrails: when OUTREACH_SENDING_ENABLED=false the queue reads empty
    (kill switch); items are additionally capped by DAILY_SEND_CAP so n8n
    can never burn the Gmail quota in one day.

    Each item carries everything the send node needs plus the IDs
    required for the sent-ack callback. EMAIL items include to_email;
    WHATSAPP items include to_phone. Use ?channel=WHATSAPP for the
    WhatsApp workflow. Items without a recipient for their channel
    are never returned.
    """
    from datetime import datetime
    from app.config import settings as app_settings

    if not app_settings.OUTREACH_SENDING_ENABLED:
        logger.info("Outreach polling: sending disabled by kill switch")
        return []

    query = (
        db.query(Outreach)
        .filter(Outreach.status == OutreachStatus.PENDING)
        .order_by(Outreach.created_at.asc())
    )
    if channel:
        query = query.filter(Outreach.channel == channel)
    payloads = []
    for o in query.all():
        p = build_n8n_payload(o)
        if is_outreach_payload_sendable(p):
            payloads.append(p)

    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(Outreach)
        .filter(Outreach.status == OutreachStatus.SENT,
                Outreach.sent_at >= start_of_day)
        .count()
    )
    capped = apply_daily_cap(payloads, sent_today, app_settings.DAILY_SEND_CAP)
    if len(capped) < len(payloads):
        logger.info(f"Outreach polling: daily cap {app_settings.DAILY_SEND_CAP}, "
                    f"sent {sent_today}, returning {len(capped)}/{len(payloads)}")
    return capped[:min(limit, len(capped))]


@router.post("", response_model=OutreachResponse, status_code=201)
def queue_outreach(payload: QueueEmailRequest, db: Session = Depends(get_db)):
    """Queue a validated email for n8n pickup.

    If subject/message are omitted, they are generated with Ollama
    (AI) and validated; the deterministic fallback template is used
    when AI is unavailable or output is invalid.
    """
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    subject, message = payload.subject, payload.message
    if not subject or not message:
        from app.services.ai_generator import generate_email
        from app.services.ai_validator import validate_email, get_fallback_email
        from app.services.seller import get_seller_dict
        seller = get_seller_dict(db)
        company = lead.company
        company_data = {
            "company_name": company.company_name if company else "Unknown",
            "description": (company.description if company else None) or "",
            "products": [p.name for p in company.products] if company else [],
            "industry": company.industry if company else None,
            "country": company.country if company else None,
        }
        draft = generate_email(company_data, seller)
        if draft and validate_email(draft["subject"], draft["body"], company_data, seller).is_valid:
            subject, message = draft["subject"], draft["body"]
        else:
            fb = get_fallback_email(company_data, seller)
            subject, message = fb["subject"], fb["body"]

    outreach, error = queue_email_for_lead(db, lead, subject or "", message or "")
    if error:
        raise HTTPException(status_code=409 if "already has" in error else 422, detail=error)
    return outreach


class QueueBulkRequest(BaseModel):
    priority: str | None = None  # HIGH, MEDIUM, LOW
    status: str | None = None  # e.g. SCORED (defaults to SCORED + EMAIL_VALIDATED)
    source_id: int | None = None  # scope to one fair directory / crawl
    limit: int = 50
    dry_run: bool = False


@router.post("/queue-bulk")
def queue_bulk(payload: QueueBulkRequest, db: Session = Depends(get_db)):
    """Queue validated emails for many leads at once (the 'send to these' button).

    Picks eligible leads (have a business email, no PENDING email already,
    not sent/replied/unsubscribed/bounced) ordered by score descending,
    generates each email (AI + validated fallback + opt-out footer) and
    queues it for n8n. With dry_run=true nothing is written — returns the
    would-queue list for review first.
    """
    from app.models.lead import LeadPriority
    from app.services.ai_generator import generate_email
    from app.services.ai_validator import validate_email, get_fallback_email
    from app.services.seller import get_seller_dict
    from app.services.outreach import is_email_ready_to_send, ensure_opt_out

    statuses = [payload.status] if payload.status else ["SCORED", "EMAIL_VALIDATED", "EMAIL_GENERATED"]
    query = db.query(Lead).filter(Lead.status.in_(statuses))
    if payload.priority:
        query = query.filter(Lead.lead_priority == LeadPriority(payload.priority))
    if payload.source_id:
        query = query.filter(Lead.company_id.in_(
            db.query(Company.id).filter(Company.source_id == payload.source_id)))
    leads = query.order_by(Lead.lead_score.desc()).limit(payload.limit * 2).all()

    seller = get_seller_dict(db)
    queued: list[dict] = []
    skipped: list[dict] = []

    for lead in leads:
        if len(queued) >= payload.limit:
            break
        contact = lead.contact
        if not contact or not contact.business_email:
            skipped.append({"lead_id": lead.id, "reason": "no business email"})
            continue
        if not is_email_ready_to_send(lead):
            skipped.append({"lead_id": lead.id, "reason": f"status {lead.status.value}"})
            continue
        company = lead.company
        company_data = {
            "company_name": company.company_name if company else "Unknown",
            "description": (company.description if company else None) or "",
            "products": [p.name for p in company.products] if company else [],
            "industry": company.industry if company else None,
            "country": company.country if company else None,
        }
        draft = generate_email(company_data, seller)
        if draft and validate_email(draft["subject"], draft["body"], company_data, seller).is_valid:
            subject, message = draft["subject"], draft["body"]
        else:
            fb = get_fallback_email(company_data, seller)
            subject, message = fb["subject"], fb["body"]
        message = ensure_opt_out(message)

        if payload.dry_run:
            queued.append({"lead_id": lead.id,
                           "to_email": contact.business_email,
                           "company": company.company_name if company else None,
                           "subject": subject})
            continue

        outreach, error = queue_email_for_lead(db, lead, subject, message)
        if outreach:
            queued.append({"lead_id": lead.id, "outreach_id": outreach.id,
                           "to_email": contact.business_email,
                           "company": company.company_name if company else None,
                           "subject": subject})
        else:
            skipped.append({"lead_id": lead.id, "reason": error})

    return {"queued": queued, "skipped": skipped,
            "queued_count": len(queued), "dry_run": payload.dry_run}


@router.post("/{outreach_id}/sent")
def mark_outreach_sent_endpoint(
    outreach_id: int,
    payload: SentAckRequest | None = None,
    db: Session = Depends(get_db),
):
    """Mark an outreach item as sent (called by n8n after Gmail send).

    Idempotent: repeated acks return 'Already sent'.
    """
    outreach = db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")

    changed = mark_outreach_sent(
        db, outreach, message_id=(payload.message_id if payload else None)
    )
    if not changed:
        return {"message": "Already sent", "id": outreach_id}
    return {"message": "Marked as sent", "id": outreach_id}


@router.post("/{outreach_id}/failed")
def mark_outreach_failed_endpoint(
    outreach_id: int,
    payload: FailedRequest,
    db: Session = Depends(get_db),
):
    """Mark an outreach item as failed (n8n error branch)."""
    outreach = db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    if outreach.status == OutreachStatus.SENT:
        raise HTTPException(status_code=409, detail="Outreach already sent")

    mark_outreach_failed(db, outreach, payload.error)
    return {"message": "Marked as failed", "id": outreach_id}


# ----------------------------------------------------------------------
# Phase 6 — WhatsApp follow-up endpoints
# ----------------------------------------------------------------------

class QueueWhatsappRequest(BaseModel):
    lead_id: int
    message: str | None = None


@router.get("/followups/due")
def get_followups_due(db: Session = Depends(get_db)):
    """List leads whose 24h WhatsApp follow-up is due (dashboard)."""
    due = find_followup_due_leads(db)
    result = []
    for lead in due:
        sent = (
            db.query(Outreach)
            .filter(
                Outreach.lead_id == lead.id,
                Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
            )
            .order_by(Outreach.sent_at.desc())
            .first()
        )
        result.append({
            "lead_id": lead.id,
            "company_name": lead.company.company_name if lead.company else None,
            "to_phone": (lead.contact.whatsapp_number or lead.contact.phone)
            if lead.contact else None,
            "email_sent_at": sent.sent_at if sent else None,
        })
    return result


@router.post("/followups/scan")
def scan_followups(db: Session = Depends(get_db)):
    """Manually trigger the follow-up scan (the scheduler runs it hourly)."""
    return scan_and_queue_followups(db)


@router.post("/followups/queue", response_model=OutreachResponse, status_code=201)
def queue_followup(payload: QueueWhatsappRequest, db: Session = Depends(get_db)):
    """Queue a WhatsApp follow-up for one lead (AI message + fallback)."""
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    outreach, error = queue_whatsapp_followup(db, lead, message=payload.message)
    if error:
        raise HTTPException(status_code=409 if "already exists" in error else 422, detail=error)
    return outreach


# ----------------------------------------------------------------------
# Bulk Gmail sending (custom template or AI, direct via connected Gmail)
# ----------------------------------------------------------------------

class SendAllRequest(BaseModel):
    subject: str | None = None
    message: str | None = None
    use_ai: bool = False
    limit: int = 50
    dry_run: bool = False
    account_id: int | None = None  # sending Gmail account (default: active)


_bulk_job: dict = {"state": "idle", "total": 0, "sent": 0,
                   "failed": 0, "skipped": 0, "errors": []}


def _bulk_job_reset(total: int):
    _bulk_job.update({"state": "running", "total": total, "sent": 0,
                      "failed": 0, "skipped": 0, "errors": []})


@router.get("/send-all/status")
def bulk_send_status():
    """Progress of the current/last bulk send job."""
    return _bulk_job


@router.post("/send-all")
def send_all(payload: SendAllRequest, db: Session = Depends(get_db)):
    """Queue + send email to top-scoring eligible leads via Gmail.

    Sends from the given account_id, else the active (most-recently-used)
    connected Gmail. Custom template: subject/message with {company_name}
    {country} {city} {website} {contact_email}. Omit both + use_ai=true
    for per-lead AI emails (slow). dry_run=true previews without sending.
    Runs in background; poll GET /api/outreach/send-all/status.
    """
    from app.config import settings as _settings
    from app.services.outreach import get_active_account

    limit = max(1, min(payload.limit, 500))
    leads = sendable_leads(db, limit)

    if payload.dry_run or (not payload.subject and not payload.message and not payload.use_ai):
        preview = []
        for lead in leads:
            subj = render_template(payload.subject or "Partnership inquiry for {company_name}", lead)
            preview.append({
                "lead_id": lead.id,
                "company_name": lead.company.company_name if lead.company else None,
                "to_email": lead.contact.business_email if lead.contact else None,
                "lead_score": lead.lead_score,
                "subject": subj,
            })
        return {"dry_run": True, "count": len(preview), "preview": preview[:25],
                "note": "dry_run: nothing queued or sent"}

    if payload.account_id:
        account = db.query(GoogleAccount).filter(
            GoogleAccount.id == payload.account_id).first()
    else:
        account = get_active_account(db)
    if not account:
        raise HTTPException(status_code=409, detail="No Google account connected — connect Gmail in Settings first")

    if _bulk_job.get("state") == "running":
        raise HTTPException(status_code=409, detail="A bulk send job is already running")

    job_leads = [(l.id) for l in leads]
    _bulk_job_reset(len(job_leads))

    thread = threading.Thread(
        target=_run_bulk_send,
        args=(job_leads, payload.subject, payload.message, payload.use_ai, account.id),
        daemon=True,
    )
    thread.start()
    return {"message": "Bulk send started", "total": len(job_leads),
            "status_url": "/api/outreach/send-all/status"}


def _run_bulk_send(lead_ids: list[int], subject_tpl: str | None,
                   message_tpl: str | None, use_ai: bool, account_id: int):
    """Background bulk sender (own DB session per run)."""
    import time as _time
    from app.database import SessionLocal
    from app.config import settings as _settings

    db = SessionLocal()
    try:
        account = db.query(GoogleAccount).filter(GoogleAccount.id == account_id).first()
        if not account:
            _bulk_job["state"] = "failed"
            _bulk_job["errors"].append("Google account disconnected mid-run")
            return
        from app.services import gmail as _gmail

        for lid in lead_ids:
            lead = db.query(Lead).filter(Lead.id == lid).first()
            if not lead or not is_email_ready_to_send(lead):
                _bulk_job["skipped"] += 1
                continue
            try:
                if subject_tpl or message_tpl:
                    subject = render_template(
                        subject_tpl or "Partnership inquiry for {company_name}", lead)
                    message = render_template(message_tpl or "", lead)
                    if not message.strip():
                        _bulk_job["skipped"] += 1
                        _bulk_job["errors"].append(f"lead {lid}: empty message after render")
                        continue
                else:
                    # AI path with deterministic fallback
                    from app.services.ai_generator import generate_email
                    from app.services.ai_validator import validate_email, get_fallback_email
                    company = lead.company
                    cdata = {
                        "company_name": company.company_name if company else "Unknown",
                        "description": (company.description if company else None) or "",
                        "products": [p.name for p in company.products] if company else [],
                        "industry": company.industry if company else None,
                        "country": company.country if company else None,
                    }
                    draft = generate_email(cdata)
                    if draft and validate_email(draft["subject"], draft["body"], cdata).is_valid:
                        subject, message = draft["subject"], draft["body"]
                    else:
                        fb = get_fallback_email(cdata)
                        subject, message = fb["subject"], fb["body"]

                outreach, error = queue_email_for_lead(db, lead, subject, message)
                if error:
                    _bulk_job["skipped"] += 1
                    continue

                to_email = lead.contact.business_email
                result = _gmail.send_email(account, to_email, subject, message)
                if "error" not in result:
                    outreach.provider_message_id = result.get("message_id")
                    outreach.provider_thread_id = result.get("thread_id")
                from app.services.outreach import record_direct_send_result
                outcome = record_direct_send_result(db, outreach, result)
                if outcome == "sent":
                    _bulk_job["sent"] += 1
                elif outcome == "retryable":
                    _bulk_job["skipped"] += 1
                    _bulk_job["errors"].append(f"lead {lid}: rate-limited, kept queued")
                    break  # pause the batch — hammering a throttled API only extends the ban
                else:
                    _bulk_job["failed"] += 1
                    _bulk_job["errors"].append(f"lead {lid}: {result['error'][:120]}")
            except Exception as e:
                _bulk_job["failed"] += 1
                _bulk_job["errors"].append(f"lead {lid}: {str(e)[:120]}")
            _time.sleep(_settings.BULK_SEND_DELAY_SECONDS)
    finally:
        db.close()
        if _bulk_job.get("state") == "running":
            _bulk_job["state"] = "done"


@router.post("/check-replies")
def check_replies(account_id: int | None = None, db: Session = Depends(get_db)):
    """Poll Gmail for replies; match by thread, classify + route.

    Checks the given account, else the active one. Matches inbound
    messages against outreach.provider_thread_id from sent emails, then
    runs the Phase 7 AI+rules router on each new reply.
    The hourly scheduler runs the same check automatically.
    """
    from app.services.outreach import poll_gmail_replies
    try:
        return poll_gmail_replies(db, account_id=account_id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ----------------------------------------------------------------------
# 24-hour email follow-up (Workflow C)
# ----------------------------------------------------------------------

class FollowUpDueResponse(BaseModel):
    lead_id: int
    company_name: str | None
    to_email: str | None
    email_sent_at: datetime | None
    thread_id: str | None


class SendFollowUpRequest(BaseModel):
    lead_id: int
    subject: str | None = None
    message: str | None = None
    dry_run: bool = False


class BulkFollowUpRequest(BaseModel):
    limit: int = 20
    dry_run: bool = False


@router.get("/followups/email-due", response_model=list[FollowUpDueResponse])
def get_email_followups_due(db: Session = Depends(get_db)):
    """List leads whose 24h email follow-up is due.

    A lead qualifies when: latest sent email is older than
    FOLLOWUP_DELAY_HOURS, no reply/bounce/unsubscribe, and no previous
    follow-up email exists for that lead.

    NOTE: this lives at /followups/email-due because GET /followups/due
    is the WhatsApp queue (registered first) — same path would shadow it.
    """
    from app.services.outreach import get_email_followup_due_leads

    result = []
    for item in get_email_followup_due_leads(db):
        lead, sent = item["lead"], item["original"]
        result.append(FollowUpDueResponse(
            lead_id=lead.id,
            company_name=lead.company.company_name if lead.company else None,
            to_email=lead.contact.business_email if lead.contact else None,
            email_sent_at=sent.sent_at,
            thread_id=sent.provider_thread_id,
        ))
    return result


@router.post("/{lead_id}/follow-up", response_model=OutreachResponse, status_code=201)
def send_follow_up(payload: SendFollowUpRequest, lead_id: int, db: Session = Depends(get_db)):
    """Send a 24-hour follow-up email to a lead (in the original thread).

    Finds the original sent email, sends a polite follow-up in the same
    Gmail thread, and tracks follow_up_count + follow_up_message_id.
    """
    from datetime import datetime, timedelta
    from app.config import settings as _settings

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Find the original sent email
    original = (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead_id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        )
        .order_by(Outreach.sent_at.desc())
        .first()
    )
    if not original:
        raise HTTPException(status_code=409, detail="No sent email to follow up on")
    if not original.sent_at:
        raise HTTPException(status_code=409, detail="Original email has no sent_at timestamp")

    # Check 24h has passed
    cutoff = datetime.utcnow() - timedelta(hours=_settings.FOLLOWUP_DELAY_HOURS)
    if original.sent_at > cutoff:
        raise HTTPException(
            status_code=409,
            detail=f"Follow-up not due yet — original email sent less than {_settings.FOLLOWUP_DELAY_HOURS}h ago",
        )

    # Check no reply/bounce
    has_reply = (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead_id,
            Outreach.status.in_([OutreachStatus.REPLIED, OutreachStatus.BOUNCED]),
        )
        .first()
    )
    if has_reply:
        raise HTTPException(status_code=409, detail="Lead has replied or bounced — no follow-up needed")

    # Count existing follow-ups
    followup_count = (
        db.query(func.count(Outreach.id))
        .filter(
            Outreach.lead_id == lead_id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        )
        .scalar()
    )
    if followup_count >= 2:
        raise HTTPException(status_code=409, detail="Maximum follow-ups reached (1 per lead)")

    if payload.dry_run:
        return OutreachResponse(
            id=0, lead_id=lead_id, channel="EMAIL", status="PENDING",
            subject=payload.subject or "Following up: Partnership inquiry",
            message=payload.message or "", sent_at=None, scheduled_at=None,
            response_at=None, error=None, provider_message_id=None,
            provider_thread_id=original.provider_thread_id,
            created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )

    # Build follow-up message
    from app.services.ai_validator import get_fallback_email
    from app.services.seller import get_seller_dict

    seller = get_seller_dict(db)
    company = lead.company
    company_data = {
        "company_name": company.company_name if company else "Unknown",
        "description": (company.description if company else None) or "",
        "products": [p.name for p in company.products] if company else [],
        "industry": company.industry if company else None,
        "country": company.country if company else None,
    }

    if payload.subject and payload.message:
        subject = payload.subject
        message = payload.message
    else:
        fb = get_fallback_email(company_data, seller)
        subject = f"Following up: {fb['subject']}"
        message = f"Hi {company_data['company_name']} team,\n\nJust following up on my previous email — would still love to share our catalogue if relevant.\n\nBest regards"

    from app.services.outreach import ensure_opt_out
    message = ensure_opt_out(message)

    # Get active account
    account = get_active_account(db)
    if not account:
        raise HTTPException(status_code=409, detail="No Google account connected")

    from app.services import gmail as _gmail
    to_email = lead.contact.business_email if lead.contact else None
    if not to_email:
        raise HTTPException(status_code=422, detail="Lead has no business email")

    # Send via Gmail (in thread if possible)
    result = _gmail.send_email(account, to_email, subject, message,
                                thread_id=original.provider_thread_id)
    if "error" in result:
        raise HTTPException(status_code=502, detail=f"Gmail send failed: {result['error']}")

    outreach = Outreach(
        lead_id=lead_id,
        channel=OutreachChannel.EMAIL,
        status=OutreachStatus.SENT,
        subject=subject,
        message=message,
        sent_at=datetime.utcnow(),
        provider_message_id=result.get("message_id"),
        provider_thread_id=result.get("thread_id") or original.provider_thread_id,
        error=None,
    )
    # Store follow-up metadata
    outreach.follow_up_count = followup_count + 1
    outreach.follow_up_sent_at = datetime.utcnow()

    db.add(outreach)
    lead.status = LeadStatus.EMAIL_SENT
    lead.updated_at = datetime.utcnow()
    db.add(Activity(
        lead_id=lead_id,
        activity_type="FOLLOWUP_SENT",
        description=f"24h follow-up email sent (outreach #{outreach.id})",
        metadata_={"follow_up_count": followup_count + 1,
                   "original_outreach_id": original.id},
    ))
    db.commit()
    db.refresh(outreach)
    logger.info(f"Follow-up email sent to lead #{lead_id} (outreach #{outreach.id})")
    return outreach


@router.post("/followups/bulk", response_model=dict)
def bulk_follow_up(payload: BulkFollowUpRequest, db: Session = Depends(get_db)):
    """Send follow-up emails to all eligible leads (up to limit)."""
    from app.services.outreach import get_email_followup_due_leads, send_due_email_followups

    if payload.dry_run:
        due = get_email_followup_due_leads(db)
        return {"due": len(due), "sent": 0, "skipped": 0,
                "errors": [], "dry_run": True}
    return send_due_email_followups(db, limit=payload.limit)


# ----------------------------------------------------------------------
# Dashboard: outreach summary + sent-emails tracking
# ----------------------------------------------------------------------

@router.get("/summary")
def outreach_summary(db: Session = Depends(get_db)):
    """Dashboard metrics derived from real outreach/lead records.

    A Gmail send ack means 'accepted by Gmail', not inbox delivery —
    delivery is only counted on DELIVERED events.
    """
    from app.models.meeting import Meeting

    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_q = db.query(Outreach).filter(
        Outreach.channel == OutreachChannel.EMAIL,
        Outreach.status == OutreachStatus.SENT)

    sent_today = sent_q.filter(Outreach.sent_at >= start_of_day).count()
    replies_today = db.query(Outreach).filter(
        Outreach.status == OutreachStatus.REPLIED,
        Outreach.response_at >= start_of_day).count()
    bounced = db.query(Outreach).filter(
        Outreach.status == OutreachStatus.BOUNCED).count()
    followups_sent = db.query(Outreach).filter(
        Outreach.channel == OutreachChannel.EMAIL,
        Outreach.status == OutreachStatus.SENT,
        Outreach.follow_up_count >= 2).count()
    unsubscribed = db.query(Lead).filter(
        Lead.status.in_([LeadStatus.UNSUBSCRIBED, LeadStatus.SUPPRESSED])).count()
    interested = db.query(Lead).filter(
        Lead.status.in_([LeadStatus.INTERESTED, LeadStatus.MEETING_PROPOSED,
                         LeadStatus.MEETING_BOOKED, LeadStatus.QUALIFIED])).count()
    eligible = db.query(Lead).filter(
        ~Lead.status.in_([LeadStatus.EMAIL_SENT, LeadStatus.REPLIED,
                          LeadStatus.UNSUBSCRIBED, LeadStatus.SUPPRESSED,
                          LeadStatus.BOUNCED, LeadStatus.NOT_INTERESTED,
                          LeadStatus.FOLLOWUP_DUE, LeadStatus.WHATSAPP_SENT])).count()
    meetings = db.query(func.count(Meeting.id)).scalar() or 0

    from app.services.outreach import count_email_followups_due
    try:
        followups_due = count_email_followups_due(db)
    except Exception:
        followups_due = 0

    return {
        "total_companies": db.query(func.count(Company.id)).scalar() or 0,
        "total_leads": db.query(func.count(Lead.id)).scalar() or 0,
        "eligible_leads": eligible,
        "emails_sent_total": sent_q.count(),
        "emails_sent_today": sent_today,
        "replies_today": replies_today,
        "interested": interested,
        "bounced": bounced,
        "followups_due": followups_due,
        "followups_sent": followups_sent,
        "unsubscribed": unsubscribed,
        "meetings_booked": meetings,
    }


@router.get("/sent")
def sent_emails(limit: int = Query(100, ge=1, le=500),
                db: Session = Depends(get_db)):
    """Track all sent emails: company, recipient, campaign, times, thread.

    Each row carries a Gmail thread link, reply state, follow-up count and
    the computed next action (wait / follow-up due / stop).
    """
    rows = (
        db.query(Outreach)
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT)
        .order_by(Outreach.sent_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for o in rows:
        lead = db.query(Lead).filter(Lead.id == o.lead_id).first()
        company = lead.company if lead else None
        contact = lead.contact if lead else None
        reply_at = None
        reply = (
            db.query(Outreach)
            .filter(Outreach.lead_id == o.lead_id,
                    Outreach.status == OutreachStatus.REPLIED)
            .order_by(Outreach.response_at.desc())
            .first()
        )
        if reply and reply.response_at:
            reply_at = reply.response_at
        thread_url = (f"https://mail.google.com/mail/u/0/#inbox/{o.provider_thread_id}"
                      if o.provider_thread_id else None)
        sent_count = (
            db.query(func.count(Outreach.id))
            .filter(Outreach.lead_id == o.lead_id,
                    Outreach.channel == OutreachChannel.EMAIL,
                    Outreach.status == OutreachStatus.SENT)
            .scalar() or 0
        )
        if reply_at:
            next_action = "stop — replied"
        elif (lead and lead.status in (LeadStatus.BOUNCED, LeadStatus.UNSUBSCRIBED,
                                       LeadStatus.SUPPRESSED, LeadStatus.NOT_INTERESTED)):
            next_action = "stop — suppressed"
        elif sent_count >= 2:
            next_action = "done — follow-up sent"
        else:
            next_action = "wait — follow-up due after 24h"
        out.append({
            "outreach_id": o.id,
            "lead_id": o.lead_id,
            "company": company.company_name if company else None,
            "to_email": contact.business_email if contact else None,
            "campaign_id": o.campaign_id or (lead.campaign_id if lead else None),
            "subject": o.subject,
            "sent_at": o.sent_at,
            "reply_at": reply_at,
            "thread_id": o.provider_thread_id,
            "thread_url": thread_url,
            "status": (lead.status.value if lead and lead.status else o.status.value),
            "follow_up_count": max(0, sent_count - 1),
            "next_action": next_action,
        })
    return out


# ----------------------------------------------------------------------
# New-batch sending (preview + idempotent run)
# ----------------------------------------------------------------------

class NewBatchRequest(BaseModel):
    subject: str | None = None
    message: str | None = None
    campaign_id: int | None = None
    limit: int = 20
    min_score: int = 0
    source_id: int | None = None


def _new_batch_candidates(db: Session, min_score: int = 0,
                          source_id: int | None = None,
                          limit: int = 200) -> list:
    """Eligible leads for a NEW batch (never-contacted only).

    Excludes: any lead with a prior SENT email outreach, any normalized
    address ever used in a SENT outreach (cross-lead dedup), replies,
    bounces, opt-outs, suppressions, and invalid/no-email records.
    """
    from app.services.outreach import is_email_ready_to_send, normalized_address

    sent_addresses: set[str] = set()
    for (lead_id_,) in db.query(Outreach.lead_id).filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT).distinct().all():
        sent_addresses.add(f"lead:{lead_id_}")
    for (email_,) in db.query(Contact.business_email).join(
            Lead, Lead.contact_id == Contact.id).join(
            Outreach, Outreach.lead_id == Lead.id).filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT).distinct().all():
        if email_:
            sent_addresses.add(normalized_address(email_))

    query = db.query(Lead).filter(Lead.lead_score >= min_score)
    if source_id:
        query = query.filter(Lead.company_id.in_(
            db.query(Company.id).filter(Company.source_id == source_id)))
    leads = query.order_by(Lead.lead_score.desc()).limit(limit * 3).all()

    eligible = []
    for lead in leads:
        if len(eligible) >= limit:
            break
        if f"lead:{lead.id}" in sent_addresses:
            continue
        contact = lead.contact
        if not contact or not contact.business_email:
            continue
        if normalized_address(contact.business_email) in sent_addresses:
            continue
        if not is_email_ready_to_send(lead, db):
            continue
        eligible.append(lead)
    return eligible


@router.get("/new-batch/preview")
def new_batch_preview(subject: str | None = None, message: str | None = None,
                      campaign_id: int | None = None, limit: int = Query(20, ge=1, le=100),
                      min_score: int = 0, source_id: int | None = None,
                      db: Session = Depends(get_db)):
    """Preview the next new batch: company, recipient, source, score, subject, body.

    Read-only. Only never-contacted, eligible business contacts appear.
    """
    rows = []
    for lead in _new_batch_candidates(db, min_score, source_id, limit):
        company = lead.company
        subj = render_template(subject or "Partnership inquiry for {company_name}", lead)
        body = render_template(message or "", lead)
        rows.append({
            "lead_id": lead.id,
            "company": company.company_name if company else None,
            "to_email": lead.contact.business_email,
            "source": company.exhibition_name if company else None,
            "source_id": company.source_id if company else None,
            "relevance_score": lead.lead_score,
            "priority": lead.lead_priority.value if lead.lead_priority else None,
            "country": company.country if company else None,
            "subject": subj, "body": body,
        })
    return {"count": len(rows), "campaign_id": campaign_id,
            "rows": rows, "dry_run": True,
            "note": "Nobody on this list has ever received a campaign email."}


@router.post("/new-batch/run")
def new_batch_run(payload: NewBatchRequest, db: Session = Depends(get_db)):
    """Send the approved batch via Gmail (idempotent per lead).

    Each lead row is locked (SELECT ... FOR UPDATE) before claiming, so two
    concurrent runs can never send the same campaign twice. Retries re-check
    SENT state before every send. Marks nothing SENT before Gmail confirms.
    """
    import time as _time
    from app.config import settings as _settings
    from app.services.outreach import ensure_opt_out

    account = get_active_account(db)
    if not account:
        raise HTTPException(status_code=409,
                            detail="No Google account connected — connect Gmail in Settings first")
    from app.services import gmail as _gmail

    candidates = _new_batch_candidates(db, payload.min_score, payload.source_id, payload.limit)
    sent, failed, skipped = 0, 0, []
    errors: list[str] = []
    for lead in candidates:
        # Atomic claim: lock the lead row, re-verify, create PENDING.
        row = (db.query(Lead).filter(Lead.id == lead.id)
               .with_for_update().first())
        if not row or not is_email_ready_to_send(row, db):
            skipped.append({"lead_id": lead.id, "reason": "became ineligible"})
            db.rollback()
            continue
        already = (db.query(Outreach).filter(
            Outreach.lead_id == row.id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT).first())
        if already:
            skipped.append({"lead_id": lead.id, "reason": "already sent"})
            db.rollback()
            continue
        subject = render_template(
            payload.subject or "Partnership inquiry for {company_name}", row)
        body = ensure_opt_out(render_template(payload.message or "", row))
        if not body.strip():
            skipped.append({"lead_id": lead.id, "reason": "empty body"})
            db.rollback()
            continue
        claim = Outreach(lead_id=row.id, channel=OutreachChannel.EMAIL,
                         status=OutreachStatus.PENDING, subject=subject,
                         message=body, campaign_id=payload.campaign_id)
        db.add(claim)
        db.commit()

        to_email = row.contact.business_email
        result = _gmail.send_email(account, to_email, subject, body)
        if "error" in result:
            if result.get("retryable"):
                # Claim stays PENDING for the next run; pause this batch.
                claim.error = f"rate-limited, will retry: {result['error'][:300]}"
                db.commit()
                skipped.append({"lead_id": row.id, "reason": "rate-limited, kept queued"})
                errors.append(f"lead {row.id}: rate-limited, kept queued")
                break
            mark_outreach_failed(db, claim, result["error"])
            failed += 1
            errors.append(f"lead {row.id}: {result['error'][:120]}")
        else:
            claim.provider_message_id = result.get("message_id")
            claim.provider_thread_id = result.get("thread_id")
            claim.campaign_id = payload.campaign_id
            mark_outreach_sent(db, claim, message_id=result.get("message_id"))
            sent += 1
        _time.sleep(_settings.BULK_SEND_DELAY_SECONDS)
    return {"sent": sent, "failed": failed, "skipped": skipped,
            "errors": errors[:5], "campaign_id": payload.campaign_id}
