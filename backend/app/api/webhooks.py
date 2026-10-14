"""Webhook endpoints for n8n / external integrations."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models.outreach import Outreach, OutreachStatus
from app.models.lead import Lead, LeadStatus
from app.models.activity import Activity

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class GmailWebhookPayload(BaseModel):
    outreach_id: int | None = None
    event_type: str  # reply, bounce, delivery
    from_address: str | None = None
    subject: str | None = None
    body: str | None = None


class WhatsAppWebhookPayload(BaseModel):
    outreach_id: int
    event_type: str  # sent, delivered, read, reply
    from_number: str | None = None
    body: str | None = None


@router.post("/gmail")
def gmail_webhook(payload: GmailWebhookPayload, db: Session = Depends(get_db)):
    """Receive Gmail events from n8n (replies, bounces, deliveries).

    outreach_id may be omitted for replies: the outreach is then resolved
    by matching from_address to the contact's business email (latest SENT
    email outreach wins). This is what the n8n Gmail-reply workflow uses,
    since Gmail push notifications carry no LeadPilot IDs.
    """
    from app.models.contact import Contact
    from app.models.outreach import OutreachChannel

    outreach = None
    if payload.outreach_id is not None:
        outreach = db.query(Outreach).filter(Outreach.id == payload.outreach_id).first()
        if not outreach:
            raise HTTPException(status_code=404, detail="Outreach not found")
    elif payload.from_address:
        contacts = (
            db.query(Contact)
            .filter(Contact.business_email.ilike(payload.from_address.strip()))
            .all()
        )
        lead_ids = [lead.id for c in contacts for lead in c.leads]
        if lead_ids:
            outreach = (
                db.query(Outreach)
                .filter(
                    Outreach.lead_id.in_(lead_ids),
                    Outreach.channel == OutreachChannel.EMAIL,
                    Outreach.status == OutreachStatus.SENT,
                )
                .order_by(Outreach.sent_at.desc())
                .first()
            )
        if not outreach:
            raise HTTPException(
                status_code=404,
                detail="No sent outreach found for from_address",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide outreach_id or from_address",
        )

    lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()

    if payload.event_type == "reply":
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found for outreach")
        from app.services.reply_processing import route_reply
        category = route_reply(db, lead, outreach, payload.body,
                               payload.from_address, payload.subject)
        # route_reply commits; the trailing db.commit() below is a no-op then
        return {"message": "Webhook processed", "event_type": payload.event_type,
                "category": category}

    elif payload.event_type == "bounce":
        outreach.status = OutreachStatus.BOUNCED
        if lead:
            lead.status = LeadStatus.BOUNCED

    elif payload.event_type == "delivery":
        outreach.status = OutreachStatus.DELIVERED

    db.commit()
    return {"message": "Webhook processed", "event_type": payload.event_type}


class GmailReplyPayload(BaseModel):
    from_address: str
    subject: str | None = None
    body: str | None = None
    outreach_id: int | None = None


class GmailBouncePayload(BaseModel):
    from_address: str | None = None
    subject: str | None = None
    body: str | None = None
    outreach_id: int | None = None


@router.post("/gmail/reply")
def gmail_reply_webhook(payload: GmailReplyPayload, db: Session = Depends(get_db)):
    """Dedicated inbound-reply endpoint (aliases /gmail with event_type=reply)."""
    return gmail_webhook(GmailWebhookPayload(
        outreach_id=payload.outreach_id, event_type="reply",
        from_address=payload.from_address, subject=payload.subject,
        body=payload.body), db)


@router.post("/gmail/bounce")
def gmail_bounce_webhook(payload: GmailBouncePayload, db: Session = Depends(get_db)):
    """Dedicated bounce endpoint (aliases /gmail with event_type=bounce)."""
    return gmail_webhook(GmailWebhookPayload(
        outreach_id=payload.outreach_id, event_type="bounce",
        from_address=payload.from_address, subject=payload.subject,
        body=payload.body), db)


class WhatsAppIncomingPayload(BaseModel):
    from_number: str | None = None
    provider_message_id: str | None = None
    outreach_id: int | None = None
    body: str | None = None


class WhatsAppStatusPayload(BaseModel):
    provider_message_id: str | None = None
    outreach_id: int | None = None
    status: str  # sent|delivered|read|failed
    error_code: str | None = None
    error_message: str | None = None


def _resolve_whatsapp_outreach(db, outreach_id=None, provider_message_id=None,
                               from_number=None):
    from app.models.outreach import OutreachChannel
    from app.models.contact import Contact
    if outreach_id is not None:
        return db.query(Outreach).filter(Outreach.id == outreach_id).first()
    if provider_message_id:
        found = db.query(Outreach).filter(
            Outreach.provider_message_id == provider_message_id).first()
        if found:
            return found
    if from_number:
        digits = "".join(c for c in from_number if c.isdigit())[-10:]
        contact = db.query(Contact).filter(
            Contact.whatsapp_number.ilike(f"%{digits}")).first()
        if contact:
            lead_ids = [lead.id for lead in contact.leads]
            if lead_ids:
                return (db.query(Outreach)
                        .filter(Outreach.lead_id.in_(lead_ids),
                                Outreach.channel == OutreachChannel.WHATSAPP,
                                Outreach.status == OutreachStatus.SENT)
                        .order_by(Outreach.sent_at.desc()).first())
    return None


@router.post("/whatsapp/incoming")
def whatsapp_incoming(payload: WhatsAppIncomingPayload, db: Session = Depends(get_db)):
    """Official-provider inbound WhatsApp handler.

    Routes the reply (stops follow-ups on interest/refusal/opt-out), flags
    STOP-style opt-outs on the contact. Never sends anything back.
    """
    outreach = _resolve_whatsapp_outreach(
        db, payload.outreach_id, payload.provider_message_id, payload.from_number)
    if not outreach:
        raise HTTPException(status_code=404, detail="No matching WhatsApp outreach")
    lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found for outreach")
    from app.services.reply_processing import route_reply
    category = route_reply(db, lead, outreach, payload.body or "",
                           payload.from_number, "(WhatsApp)")
    text = (payload.body or "").lower()
    if any(k in text for k in ("stop", "unsubscribe", "opt out", "opt-out")):
        contact = lead.contact
        if contact:
            contact.consent_status = "opted_out"
            contact.whatsapp_eligible = False
            db.commit()
    return {"message": "WhatsApp reply processed", "category": category}


@router.post("/whatsapp/status")
def whatsapp_status(payload: WhatsAppStatusPayload, db: Session = Depends(get_db)):
    """Official-provider delivery/failure receipts (queued/sent/delivered/read/failed)."""
    outreach = _resolve_whatsapp_outreach(db, payload.outreach_id,
                                          payload.provider_message_id)
    if not outreach:
        raise HTTPException(status_code=404, detail="No matching WhatsApp outreach")
    mapping = {"sent": OutreachStatus.SENT, "delivered": OutreachStatus.DELIVERED,
               "read": OutreachStatus.DELIVERED, "failed": OutreachStatus.FAILED}
    if payload.status not in mapping:
        raise HTTPException(status_code=422, detail="status must be sent|delivered|read|failed")
    # Provider errors never mark messages sent.
    if payload.status == "failed" and outreach.status == OutreachStatus.SENT:
        raise HTTPException(status_code=409, detail="Outreach already sent")
    outreach.status = mapping[payload.status]
    if payload.status == "sent" and not outreach.sent_at:
        outreach.sent_at = datetime.utcnow()
    if payload.status == "failed":
        outreach.error = f"{payload.error_code or ''} {payload.error_message or ''}".strip()[:2000] or "Provider reported failure"
    db.commit()
    return {"message": "WhatsApp status updated", "status": payload.status}


@router.post("/whatsapp")
def whatsapp_webhook(payload: WhatsAppWebhookPayload, db: Session = Depends(get_db)):
    """Receive WhatsApp events from n8n."""
    outreach = db.query(Outreach).filter(Outreach.id == payload.outreach_id).first()
    if not outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")

    lead = db.query(Lead).filter(Lead.id == outreach.lead_id).first()

    if payload.event_type == "reply":
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found for outreach")
        from app.services.reply_processing import route_reply
        category = route_reply(db, lead, outreach, payload.body,
                               payload.from_number, "(WhatsApp)")
        return {"message": "Webhook processed", "event_type": payload.event_type,
                "category": category}

    elif payload.event_type == "delivered":
        outreach.status = OutreachStatus.DELIVERED

    elif payload.event_type == "sent":
        outreach.status = OutreachStatus.SENT
        outreach.sent_at = datetime.utcnow()

    db.commit()
    return {"message": "Webhook processed", "event_type": payload.event_type}
