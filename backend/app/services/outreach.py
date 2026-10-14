"""Outreach service — manages email/WhatsApp sending lifecycle."""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadStatus
from app.models.outreach import Outreach, OutreachChannel, OutreachStatus
from app.models.activity import Activity
from app.config import settings

logger = logging.getLogger(__name__)


def normalized_address(value: str | None) -> str:
    """Lowercased email / digits-only phone for suppression + dedup checks."""
    if not value:
        return ""
    v = value.strip().lower()
    if "@" in v:
        return v
    import re as _re
    return _re.sub(r"\D", "", v)


def is_suppressed(db: Session, email: str | None = None,
                  phone: str | None = None) -> bool:
    """Check the suppression list (unsubscribe/bounce/opt-out, any source)."""
    from app.models.suppression import Suppression
    for value in (normalized_address(email), normalized_address(phone)):
        if value and db.query(Suppression).filter(Suppression.value == value).first():
            return True
    return False


def add_suppression(db: Session, value: str, value_type: str, reason: str,
                    source: str | None = None, company_id: int | None = None,
                    lead_id: int | None = None) -> bool:
    """Append to the suppression list (idempotent). Returns True if new."""
    from app.models.suppression import Suppression
    norm = normalized_address(value)
    if not norm:
        return False
    exists = db.query(Suppression).filter(
        Suppression.value == norm,
        Suppression.value_type == value_type).first()
    if exists:
        return False
    db.add(Suppression(value=norm, value_type=value_type, reason=reason,
                       source=source, company_id=company_id, lead_id=lead_id))
    return True


def is_email_ready_to_send(lead: Lead, db: Session | None = None) -> bool:
    """Check if a lead is ready for email outreach."""
    if lead.status in [LeadStatus.EMAIL_SENT, LeadStatus.REPLIED, LeadStatus.UNSUBSCRIBED,
                       LeadStatus.SUPPRESSED, LeadStatus.BOUNCED, LeadStatus.NOT_INTERESTED]:
        return False
    if not lead.contact or not lead.contact.business_email:
        return False
    if db is not None and is_suppressed(db, email=lead.contact.business_email):
        return False
    return True


def check_whatsapp_eligibility(contact) -> tuple[bool, str]:
    """WhatsApp eligibility gate (never assume a scraped phone has WhatsApp).

    Eligible only when a number exists, is not opted out, and a human or a
    permitted provider check approved it (whatsapp_eligible=True).
    Scraped numbers with a recorded source URL are 'unknown' — they need
    approval first. Returns (eligible, reason).
    """
    if contact is None or not (contact.whatsapp_number or "").strip():
        return False, "no WhatsApp number on file"
    if (contact.consent_status or "") == "opted_out":
        return False, "contact opted out of WhatsApp"
    if is_suppressed_db(contact):
        return False, "number is suppressed (bounce/opt-out)"
    if contact.whatsapp_eligible is True:
        return True, "approved"
    if contact.whatsapp_source_url:
        return False, "scraped number — needs human approval (source on file)"
    return False, "no eligibility evidence — approval required"


def is_suppressed_db(contact) -> bool:
    """Suppression check for a contact without importing a session."""
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            return is_suppressed(db, phone=contact.whatsapp_number)
        finally:
            db.close()
    except Exception:
        return False


def is_whatsapp_followup_due(lead: Lead, db: Session) -> bool:
    """Check if a WhatsApp follow-up is due."""
    if lead.status != LeadStatus.EMAIL_SENT:
        return False

    email_outreach = (
        db.query(Outreach)
        .filter(Outreach.lead_id == lead.id, Outreach.channel == OutreachChannel.EMAIL)
        .order_by(Outreach.sent_at.desc())
        .first()
    )

    if not email_outreach or not email_outreach.sent_at:
        return False

    followup_time = email_outreach.sent_at + timedelta(hours=settings.FOLLOWUP_DELAY_HOURS)
    if datetime.utcnow() < followup_time:
        return False

    if not lead.contact or not lead.contact.whatsapp_number:
        return False

    return True


def mark_followup_due(lead: Lead, db: Session):
    """Mark a lead as FOLLOWUP_DUE and create an activity."""
    lead.status = LeadStatus.FOLLOWUP_DUE
    activity = Activity(
        lead_id=lead.id,
        activity_type="FOLLOWUP_DUE",
        description="24-hour follow-up is due",
    )
    db.add(activity)


OPT_OUT_LINE = "P.S. If this isn't relevant, just reply STOP and we won't contact you again."

_OPTOUT_SIGNALS = ("opt out", "opt-out", "unsubscribe", "reply stop")


def ensure_opt_out(message: str) -> str:
    """Append a one-line opt-out footer unless the message already has one."""
    if not message:
        return message
    lowered = message.lower()
    if any(sig in lowered for sig in _OPTOUT_SIGNALS):
        return message
    return message.rstrip() + "\n\n" + OPT_OUT_LINE


def create_outreach_record(db: Session, lead_id: int, channel: OutreachChannel, subject: str | None, message: str) -> Outreach:
    """Create an outreach record."""
    outreach = Outreach(
        lead_id=lead_id,
        channel=channel,
        status=OutreachStatus.PENDING,
        subject=subject,
        message=message,
    )
    db.add(outreach)
    db.commit()
    db.refresh(outreach)
    return outreach


def queue_email_for_lead(
    db: Session,
    lead: Lead,
    subject: str,
    message: str,
) -> tuple[Outreach | None, str | None]:
    """Queue a validated email for n8n pickup.

    Returns (outreach, error). Blocks duplicates: one PENDING email per lead.
    """
    if not is_email_ready_to_send(lead):
        return None, "Lead is not ready for email outreach (already sent, replied, unsubscribed, or no business email)"

    existing = (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead.id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.PENDING,
        )
        .first()
    )
    if existing:
        return None, f"Lead already has a pending email (outreach #{existing.id})"

    if not subject or not subject.strip():
        return None, "Email subject is required"
    if not message or len(message.strip()) < 20:
        return None, "Email message is required (min 20 chars)"

    outreach = Outreach(
        lead_id=lead.id,
        channel=OutreachChannel.EMAIL,
        status=OutreachStatus.PENDING,
        subject=subject.strip(),
        message=ensure_opt_out(message.strip()),
    )
    db.add(outreach)
    db.flush()

    lead.status = LeadStatus.EMAIL_VALIDATED
    db.add(Activity(
        lead_id=lead.id,
        activity_type="EMAIL_QUEUED",
        description=f"Email queued for sending via n8n (outreach #{outreach.id})",
    ))
    db.commit()
    db.refresh(outreach)
    logger.info(f"Queued email outreach #{outreach.id} for lead #{lead.id}")
    return outreach, None


def build_n8n_payload(outreach: Outreach) -> dict:
    """Build the n8n-ready payload for one outreach item.

    Contains everything the send node needs: recipient, subject, body,
    plus IDs for the sent-ack callback. EMAIL items carry to_email;
    WHATSAPP items carry to_phone.
    """
    lead = outreach.lead
    contact = lead.contact if lead else None
    to_email = contact.business_email if contact else None
    to_phone = None
    if contact:
        to_phone = contact.whatsapp_number or contact.phone
    company_name = lead.company.company_name if lead and lead.company else None
    return {
        "id": outreach.id,
        "lead_id": outreach.lead_id,
        "channel": outreach.channel.value,
        "to_email": to_email,
        "to_phone": to_phone,
        "company_name": company_name,
        "subject": outreach.subject,
        "message": outreach.message,
    }


def is_outreach_payload_sendable(payload: dict) -> bool:
    """Check an n8n payload has a recipient and content for its channel."""
    if not payload.get("message"):
        return False
    if payload.get("channel") == OutreachChannel.WHATSAPP.value:
        return bool(payload.get("to_phone"))
    return bool(payload.get("to_email") and payload.get("subject"))


def mark_outreach_sent(
    db: Session,
    outreach: Outreach,
    message_id: str | None = None,
) -> bool:
    """Mark outreach SENT (idempotent). Returns True if state changed."""
    if outreach.status == OutreachStatus.SENT:
        return False

    from datetime import datetime
    outreach.status = OutreachStatus.SENT
    outreach.sent_at = datetime.utcnow()
    outreach.error = None

    lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()
    if lead:
        if outreach.channel == OutreachChannel.EMAIL:
            lead.status = LeadStatus.EMAIL_SENT
        elif outreach.channel == OutreachChannel.WHATSAPP:
            lead.status = LeadStatus.WHATSAPP_SENT
        db.add(Activity(
            lead_id=lead.id,
            activity_type="EMAIL_SENT" if outreach.channel == OutreachChannel.EMAIL else "WHATSAPP_SENT",
            description=f"{outreach.channel.value} sent (outreach #{outreach.id})",
            metadata_={"message_id": message_id} if message_id else None,
        ))

    db.commit()
    logger.info(f"Outreach #{outreach.id} marked SENT")
    return True


def record_direct_send_result(db: Session, outreach: Outreach, result: dict) -> str:
    """Record a direct-Gmail-send outcome. Returns 'sent'|'retryable'|'failed'.

    Transient Gmail rate limits (429/5xx, result has retryable=True) keep
    the outreach PENDING with the error noted — it retries on the next run
    instead of being permanently marked FAILED. Anything else marks FAILED.
    """
    if "error" not in result:
        mark_outreach_sent(db, outreach, message_id=result.get("message_id"))
        return "sent"
    if result.get("retryable"):
        outreach.status = OutreachStatus.PENDING
        outreach.error = f"rate-limited, will retry: {(result['error'] or '')[:500]}"
        lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()
        if lead:
            db.add(Activity(
                lead_id=lead.id,
                activity_type="SEND_RATE_LIMITED",
                description=f"Gmail rate limit (outreach #{outreach.id}) — kept queued for retry",
            ))
        db.commit()
        logger.warning(f"Outreach #{outreach.id} rate-limited, kept PENDING for retry")
        return "retryable"
    mark_outreach_failed(db, outreach, result["error"])
    return "failed"


def mark_outreach_failed(db: Session, outreach: Outreach, error: str) -> None:
    """Mark outreach FAILED with an error message (n8n error branch)."""
    outreach.status = OutreachStatus.FAILED
    outreach.error = (error or "Unknown send error")[:2000]
    lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()
    if lead:
        db.add(Activity(
            lead_id=lead.id,
            activity_type="OUTREACH_FAILED",
            description=f"Send failed (outreach #{outreach.id}): {outreach.error[:200]}",
        ))
    db.commit()
    logger.warning(f"Outreach #{outreach.id} marked FAILED: {outreach.error[:200]}")


# ----------------------------------------------------------------------
# Phase 6 — 24-hour WhatsApp follow-up
# ----------------------------------------------------------------------

def _latest_email_outreach(db: Session, lead_id: int) -> Outreach | None:
    """Return the most recently sent EMAIL outreach for a lead."""
    return (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead_id,
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        )
        .order_by(Outreach.sent_at.desc())
        .first()
    )


def _has_whatsapp_followup_since(db: Session, lead_id: int, since) -> bool:
    """Check whether a WHATSAPP outreach already exists after `since`."""
    return (
        db.query(Outreach)
        .filter(
            Outreach.lead_id == lead_id,
            Outreach.channel == OutreachChannel.WHATSAPP,
            Outreach.created_at >= since,
        )
        .first()
        is not None
    )


def find_followup_due_leads(db: Session) -> list[Lead]:
    """Find EMAIL_SENT leads whose 24h WhatsApp follow-up is due.

    A lead qualifies when: the latest sent email is older than
    FOLLOWUP_DELAY_HOURS, the contact has a WhatsApp number, and no
    WhatsApp follow-up was created since that email. Replied /
    unsubscribed / bounced leads are excluded by status.
    """
    candidates = (
        db.query(Lead)
        .filter(Lead.status == LeadStatus.EMAIL_SENT)
        .all()
    )
    due: list[Lead] = []
    for lead in candidates:
        if not is_whatsapp_followup_due(lead, db):
            continue
        email_outreach = _latest_email_outreach(db, lead.id)
        if not email_outreach or not email_outreach.sent_at:
            continue
        if _has_whatsapp_followup_since(db, lead.id, email_outreach.sent_at):
            continue
        due.append(lead)
    return due


def queue_whatsapp_followup(
    db: Session,
    lead: Lead,
    message: str | None = None,
) -> tuple[Outreach | None, str | None]:
    """Queue a WhatsApp follow-up for n8n pickup.

    Returns (outreach, error). One follow-up per sent email: a second
    call after a follow-up already exists is rejected.
    """
    if lead.status not in (LeadStatus.EMAIL_SENT, LeadStatus.FOLLOWUP_DUE):
        return None, f"Lead status {lead.status.value} is not eligible for WhatsApp follow-up"

    contact = lead.contact
    if not contact or not contact.whatsapp_number:
        return None, "Lead has no WhatsApp number"

    eligible, reason = check_whatsapp_eligibility(contact)
    if not eligible:
        return None, f"WhatsApp not eligible: {reason}"

    email_outreach = _latest_email_outreach(db, lead.id)
    if not email_outreach or not email_outreach.sent_at:
        return None, "No sent email to follow up on"
    if _has_whatsapp_followup_since(db, lead.id, email_outreach.sent_at):
        return None, "A WhatsApp follow-up already exists for the latest email"

    if not message or len(message.strip()) < 10:
        company = lead.company
        company_data = {
            "company_name": company.company_name if company else "Unknown",
            "description": (company.description if company else None) or "",
            "products": [p.name for p in company.products] if company else [],
            "industry": company.industry if company else None,
            "country": company.country if company else None,
        }
        from app.services.ai_generator import generate_whatsapp_followup
        from app.services.ai_validator import get_fallback_whatsapp
        from app.services.seller import get_seller_dict
        seller = get_seller_dict(db)
        message = (generate_whatsapp_followup(company_data, seller)
                   or get_fallback_whatsapp(company_data, seller))

    outreach = Outreach(
        lead_id=lead.id,
        channel=OutreachChannel.WHATSAPP,
        status=OutreachStatus.PENDING,
        subject=None,
        message=ensure_opt_out(message.strip()),
    )
    db.add(outreach)
    db.flush()

    mark_followup_due(lead, db)
    db.add(Activity(
        lead_id=lead.id,
        activity_type="WHATSAPP_QUEUED",
        description=f"WhatsApp follow-up queued for sending via n8n (outreach #{outreach.id})",
    ))
    db.commit()
    db.refresh(outreach)
    logger.info(f"Queued WhatsApp outreach #{outreach.id} for lead #{lead.id}")
    return outreach, None


def scan_and_queue_followups(db: Session) -> dict:
    """Scan for due follow-ups and queue them. Returns a summary."""
    due = find_followup_due_leads(db)
    queued = 0
    skipped: list[dict] = []
    for lead in due:
        outreach, error = queue_whatsapp_followup(db, lead)
        if outreach:
            queued += 1
        else:
            skipped.append({"lead_id": lead.id, "reason": error})
    summary = {"due_found": len(due), "queued": queued, "skipped": skipped}
    logger.info(f"Follow-up scan: {summary}")
    return summary


# ----------------------------------------------------------------------
# Automatic 24-hour EMAIL follow-ups (scheduler-called, fail-closed)
# ----------------------------------------------------------------------

def get_email_followup_due_leads(db: Session) -> list[dict]:
    """Leads whose 24h email follow-up is due (shared by API + scheduler).

    Returns dicts with lead + original sent outreach. A lead qualifies
    when its latest sent email is older than FOLLOWUP_DELAY_HOURS, it has
    no reply/bounce, and no follow-up email was sent yet.
    """
    from sqlalchemy import func as _func

    cutoff = datetime.utcnow() - timedelta(hours=settings.FOLLOWUP_DELAY_HOURS)
    sent_old = (
        db.query(Outreach.lead_id)
        .filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
            Outreach.sent_at < cutoff,
        )
        .distinct()
    )
    has_reply = (
        db.query(Outreach.lead_id)
        .filter(Outreach.status.in_([OutreachStatus.REPLIED, OutreachStatus.BOUNCED]))
        .distinct()
    )
    already_followed = (
        db.query(Outreach.lead_id)
        .filter(
            Outreach.channel == OutreachChannel.EMAIL,
            Outreach.status == OutreachStatus.SENT,
        )
        .group_by(Outreach.lead_id)
        .having(_func.count(Outreach.id) >= 2)
    )
    candidates = (
        db.query(Lead)
        .filter(
            Lead.id.in_(sent_old),
            ~Lead.id.in_(has_reply),
            ~Lead.id.in_(already_followed),
        )
        .order_by(Lead.lead_score.desc())
        .all()
    )
    due = []
    for lead in candidates:
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
        if sent and sent.sent_at:
            due.append({"lead": lead, "original": sent})
    return due


def count_email_followups_due(db: Session) -> int:
    """Fast count of due email follow-ups (analytics-safe)."""
    return len(get_email_followup_due_leads(db))


def send_due_email_followups(db: Session, limit: int = 20) -> dict:
    """Auto-send 24h follow-up emails (scheduler-called, fail-closed).

    Fail-closed: no connected Gmail account, a fresh reply/bounce, or any
    Gmail/DB error means SKIP — never send blind. One follow-up per lead
    maximum. Returns {"due": n, "sent": n, "skipped": n, "errors": [...]}.
    """
    import time as _time
    from app.services import gmail as _gmail
    from app.services.ai_validator import get_fallback_email
    from app.services.seller import get_seller_dict

    account = get_active_account(db)
    if not account:
        return {"due": 0, "sent": 0, "skipped": 0,
                "errors": ["no Google account connected — fail-closed, nothing sent"]}

    try:
        seller = get_seller_dict(db)
    except Exception:
        seller = {}

    due = get_email_followup_due_leads(db)
    sent = skipped = 0
    errors: list[str] = []
    for item in due[:max(1, limit)]:
        lead, original = item["lead"], item["original"]
        try:
            # Re-check reply/bounce immediately before sending (fail-closed)
            fresh_reply = (
                db.query(Outreach)
                .filter(
                    Outreach.lead_id == lead.id,
                    Outreach.status.in_([OutreachStatus.REPLIED, OutreachStatus.BOUNCED]),
                )
                .first()
            )
            if fresh_reply:
                skipped += 1
                continue
            contact = lead.contact
            if not contact or not contact.business_email:
                skipped += 1
                continue
            company = lead.company
            cdata = {
                "company_name": company.company_name if company else "Unknown",
                "description": (company.description if company else None) or "",
                "products": [p.name for p in company.products] if company else [],
                "industry": company.industry if company else None,
                "country": company.country if company else None,
            }
            fb = get_fallback_email(cdata, seller)
            subject = f"Following up: {fb['subject']}"
            message = ensure_opt_out(
                f"Hi {cdata['company_name']} team,\n\nJust following up on my "
                f"previous email — would still love to share our catalogue if "
                f"relevant.\n\nBest regards")
            result = _gmail.send_email(
                account, contact.business_email, subject, message,
                thread_id=original.provider_thread_id)
            if "error" in result:
                skipped += 1
                errors.append(f"lead {lead.id}: {result['error'][:120]}")
                if result.get("retryable"):
                    break  # pause — hammering a throttled API only extends the ban
                continue
            followup = Outreach(
                lead_id=lead.id,
                channel=OutreachChannel.EMAIL,
                status=OutreachStatus.SENT,
                subject=subject,
                message=message,
                sent_at=datetime.utcnow(),
                provider_message_id=result.get("message_id"),
                provider_thread_id=result.get("thread_id") or original.provider_thread_id,
                follow_up_count=2,
                follow_up_sent_at=datetime.utcnow(),
            )
            db.add(followup)
            db.add(Activity(
                lead_id=lead.id,
                activity_type="FOLLOWUP_SENT",
                description=f"Auto 24h follow-up sent (outreach #{original.id} → thread)",
                metadata_={"original_outreach_id": original.id, "auto": True},
            ))
            db.commit()
            sent += 1
        except Exception as e:
            db.rollback()
            skipped += 1
            errors.append(f"lead {lead.id}: {str(e)[:120]}")
        _time.sleep(settings.BULK_SEND_DELAY_SECONDS)

    summary = {"due": len(due), "sent": sent, "skipped": skipped, "errors": errors[:5]}
    logger.info(f"Auto email follow-ups: {summary}")
    return summary


# ----------------------------------------------------------------------
# Bulk custom-template sending
# ----------------------------------------------------------------------

TEMPLATE_FIELDS = ("company_name", "country", "city", "website", "contact_email")


def render_template(text: str | None, lead: Lead) -> str:
    """Render {company_name} {country} {city} {website} {contact_email}.

    Unknown placeholders are left untouched; missing values render empty.
    """
    if not text:
        return ""
    company = lead.company
    contact = lead.contact
    mapping = {
        "company_name": company.company_name if company else "",
        "country": (company.country if company else None) or "",
        "city": (company.city if company else None) or "",
        "website": (company.website if company else None) or "",
        "contact_email": (contact.business_email if contact else None) or "",
    }
    rendered = text
    for key, value in mapping.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def unrendered_placeholders(text: str) -> list[str]:
    """Return {placeholder} tokens still present after rendering."""
    import re as _re
    return sorted(set(_re.findall(r"\{[A-Za-z_]+\}", text or "")))


def get_active_account(db):
    """The sending account: most recently connected/selected.

    Lets many people connect their own Gmail through the one app-level
    OAuth client — no .env edits for end users, ever.
    """
    from app.models.google_account import GoogleAccount
    return db.query(GoogleAccount).order_by(
        GoogleAccount.updated_at.desc(), GoogleAccount.id.desc()).first()


def touch_account(db, account):
    """Mark an account most-recently-used (select it for sending)."""
    from datetime import datetime
    account.updated_at = datetime.utcnow()
    db.commit()


def apply_daily_cap(payloads: list[dict], sent_today: int, cap: int) -> list[dict]:
    """Cap n8n-ready items by remaining daily quota (pure function).

    sent_today counts ALL sends (direct bulk + n8n) since Gmail quota is
    shared. Never returns more than cap - sent_today items.
    """
    remaining = max(0, cap - sent_today)
    return payloads[:remaining]


def poll_gmail_replies(db: Session, account_id: int | None = None) -> dict:
    """Poll Gmail for replies; match by thread, classify + route.

    Shared by POST /api/outreach/check-replies and the hourly scheduler.
    Uses the given account, else the active (most-recently-used) one.
    Returns {"checked": n, "matched": n, "categories": {...}}.
    Raises RuntimeError when no Google account is connected.
    """
    from app.services import gmail as _gmail
    from app.services.reply_processing import route_reply
    from app.models.google_account import GoogleAccount

    if account_id:
        account = db.query(GoogleAccount).filter(GoogleAccount.id == account_id).first()
    else:
        account = get_active_account(db)
    if not account:
        raise RuntimeError("No Google account connected")

    sent = (
        db.query(Outreach)
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT,
                Outreach.provider_thread_id.isnot(None))
        .all()
    )
    by_thread = {o.provider_thread_id: o for o in sent}
    if not by_thread:
        return {"checked": 0, "matched": 0, "categories": {}}

    messages = _gmail.list_recent_messages(account)
    matched = 0
    categories: dict[str, int] = {}
    seen_threads = set()
    for m in messages:
        full = _gmail.get_message(account, m["id"])
        if not full or full["thread_id"] not in by_thread:
            continue
        if full["thread_id"] in seen_threads:
            continue
        # Skip our own sent copies
        if "SENT" in (full.get("label_ids") or []):
            continue
        outreach = by_thread[full["thread_id"]]
        if outreach.status == OutreachStatus.REPLIED:
            continue
        lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()
        if not lead:
            continue
        category = route_reply(db, lead, outreach, full.get("snippet", ""),
                               full.get("from", ""), full.get("subject", ""))
        categories[category] = categories.get(category, 0) + 1
        matched += 1
        seen_threads.add(full["thread_id"])

    return {"checked": len(messages), "matched": matched, "categories": categories}


def run_auto_send(db: Session) -> dict:
    """Run the daily automated send (scheduler-called, Gmail quota-aware).

    Sends fallback-template emails (fast, deterministic) to top-scoring
    eligible leads: at most AUTO_SEND_DAILY_LIMIT, and never pushing the
    day's total sends past AUTO_SEND_DAY_QUOTA. Runs once per UTC day
    (tracked in AutoSendState). Returns a summary dict.
    """
    import time as _time
    from datetime import datetime
    from app.config import settings as _settings
    from app.models.auto_send_state import AutoSendState
    from app.services import gmail as _gmail
    from app.services.ai_validator import get_fallback_email

    def _state():
        st = db.query(AutoSendState).filter(AutoSendState.id == 1).first()
        if not st:
            st = AutoSendState(id=1)
            db.add(st)
            db.commit()
        return st

    enabled = _settings.AUTO_SEND_ENABLED
    daily_limit = _settings.AUTO_SEND_DAILY_LIMIT
    st = _state()
    if st.enabled is not None:
        enabled = st.enabled
    if st.daily_limit:
        daily_limit = st.daily_limit
    if not enabled:
        return {"ran": False, "reason": "auto-send disabled"}
    if datetime.utcnow().hour < _settings.AUTO_SEND_HOUR:
        return {"ran": False, "reason": "before send hour"}

    today = datetime.utcnow().strftime("%Y-%m-%d")
    if st.last_run_date == today:
        return {"ran": False, "reason": "already ran today"}

    account = get_active_account(db)
    if not account:
        return {"ran": False, "reason": "no Google account connected"}

    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = db.query(Outreach).filter(
        Outreach.status == OutreachStatus.SENT,
        Outreach.sent_at >= start_of_day).count()
    remaining_quota = max(0, _settings.AUTO_SEND_DAY_QUOTA - sent_today)
    batch = min(daily_limit, remaining_quota)
    if batch <= 0:
        st.last_run_date = today
        st.last_sent = 0
        st.last_status = "quota-exhausted"
        db.commit()
        return {"ran": True, "sent": 0, "reason": "day quota exhausted"}

    leads = sendable_leads(db, batch)
    sent = failed = skipped = 0
    errors: list[str] = []
    for lead in leads:
        try:
            company = lead.company
            cdata = {
                "company_name": company.company_name if company else "Unknown",
                "description": (company.description if company else None) or "",
                "products": [p.name for p in company.products] if company else [],
                "industry": company.industry if company else None,
                "country": company.country if company else None,
            }
            fb = get_fallback_email(cdata)
            outreach, error = queue_email_for_lead(db, lead, fb["subject"], fb["body"])
            if error:
                skipped += 1
                continue
            result = _gmail.send_email(
                account, lead.contact.business_email, fb["subject"], fb["body"])
            if "error" not in result:
                outreach.provider_message_id = result.get("message_id")
                outreach.provider_thread_id = result.get("thread_id")
            outcome = record_direct_send_result(db, outreach, result)
            if outcome == "sent":
                sent += 1
            elif outcome == "retryable":
                skipped += 1
                errors.append(f"lead {lead.id}: rate-limited, kept queued")
                break  # pause the batch — hammering a throttled API only extends the ban
            else:
                failed += 1
                errors.append(f"lead {lead.id}: {result['error'][:120]}")
        except Exception as e:
            failed += 1
            errors.append(f"lead {lead.id}: {str(e)[:120]}")
        _time.sleep(_settings.BULK_SEND_DELAY_SECONDS)

    st.last_run_date = today
    st.last_sent = sent
    st.last_status = "done" if failed == 0 else "done-with-errors"
    db.commit()
    summary = {"ran": True, "sent": sent, "failed": failed, "skipped": skipped,
               "errors": errors[:5]}
    logger.info(f"Auto-send: {summary}")
    return summary


def sendable_leads(db: Session, limit: int) -> list[Lead]:
    """Top-scoring leads eligible for a bulk email run."""
    leads = (
        db.query(Lead)
        .order_by(Lead.lead_score.desc(), Lead.created_at.asc())
        .limit(max(limit * 3, limit + 20))
        .all()
    )
    eligible = [l for l in leads if is_email_ready_to_send(l)]
    return eligible[:limit]
