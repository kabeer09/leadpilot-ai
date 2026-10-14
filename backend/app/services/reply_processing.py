"""Reply classification + routing (Phase 7).

AI (Ollama) classifies first; deterministic keyword rules are the fallback
when AI is unavailable or returns UNKNOWN. The category then routes the
lead to the right status and raises follow-up actions.
"""
import logging
import re

logger = logging.getLogger(__name__)

CATEGORIES = [
    "INTERESTED", "QUESTION", "NEGOTIATION", "MEETING_REQUEST",
    "NOT_INTERESTED", "UNSUBSCRIBE", "OUT_OF_OFFICE", "UNKNOWN",
]

# Category -> LeadStatus value (None = keep REPLIED, human triage)
CATEGORY_TO_STATUS = {
    "INTERESTED": "INTERESTED",
    "MEETING_REQUEST": "MEETING_PROPOSED",
    "NOT_INTERESTED": "NOT_INTERESTED",
    "UNSUBSCRIBE": "UNSUBSCRIBED",
    "OUT_OF_OFFICE": None,
    "QUESTION": None,
    "NEGOTIATION": None,
    "UNKNOWN": None,
}

# Deterministic fallback rules, evaluated in order
RULES: list[tuple[str, list[str]]] = [
    ("UNSUBSCRIBE", ["unsubscribe", "remove me", "stop emailing", "opt out", "opt-out",
                     "do not contact", "don't contact", "no more emails"]),
    ("NOT_INTERESTED", ["not interested", "no interest", "not relevant", "no need",
                        "already have a supplier", "already sourced", "pass on this"]),
    ("OUT_OF_OFFICE", ["out of office", "out-of-office", "on leave", "on vacation",
                       "returning on", "back on", "auto-reply", "automatic reply"]),
    ("MEETING_REQUEST", ["let's meet", "lets meet", "schedule a meeting", "schedule a call",
                         "book a meeting", "google meet", "video call", "zoom call",
                         "propose a time", "send a meeting invite", "meeting invite",
                         "available on", "available at", "call on", "speak on"]),
    ("NEGOTIATION", ["price", "pricing", "quote", "quotation", "discount", "moq",
                     "minimum order", "payment terms", "negotiat", "best price",
                     "sample", "lead time"]),
    ("QUESTION", ["?"]),
    ("INTERESTED", ["interested", "interest", "send catalogue", "send catalog",
                    "send details", "share details", "tell me more", "sounds good",
                    "looks good", "please proceed", "yes please", "love to",
                    "would like to know", "keen to"]),
]


def rule_classify(reply_text: str | None) -> str:
    """Deterministic keyword classification (AI fallback)."""
    if not reply_text or not reply_text.strip():
        return "UNKNOWN"
    text = reply_text.lower()
    for category, keywords in RULES:
        if any(kw in text for kw in keywords):
            return category
    return "UNKNOWN"


BOUNCE_SIGNALS = [
    "delivery status notification",
    "undelivered mail",
    "mail delivery failed",
    "delivery failure",
    "message not delivered",
    "address not found",
    "recipient address rejected",
    "mailbox unavailable",
    "user unknown",
    "message rejected",
    "delivery incomplete",
]


def is_bounce(subject: str | None, body: str | None) -> bool:
    """Detect bounce/DSN messages (must never be treated as replies)."""
    combined = f"{subject or ''} {body or ''}".lower()
    return any(sig in combined for sig in BOUNCE_SIGNALS)


def classify_reply_with_fallback(reply_text: str | None) -> tuple[str, str]:
    """Classify a reply. Returns (category, method).

    Method is 'ai', 'rules', or 'rules-safety'. The suppression
    categories (UNSUBSCRIBE, NOT_INTERESTED) are compliance-critical:
    explicit opt-out / rejection phrases always win over AI, so a
    small-model misjudgment can never keep emailing someone who opted out.
    """
    rules_category = rule_classify(reply_text or "")
    if rules_category in ("UNSUBSCRIBE", "NOT_INTERESTED"):
        return rules_category, "rules-safety"

    from app.services.ai_generator import classify_reply

    try:
        category = classify_reply(reply_text or "")
    except Exception as e:
        logger.warning(f"AI classification failed, using rules: {e}")
        category = "UNKNOWN"

    if category and category in CATEGORIES and category != "UNKNOWN":
        return category, "ai"
    return rules_category, "rules"


def route_reply(db, lead, outreach, reply_body, from_address, subject):
    """Classify a reply and route the lead. Returns the category.

    - outreach -> REPLIED + response_at
    - lead status per CATEGORY_TO_STATUS (default REPLIED)
    - REPLY_RECEIVED + REPLY_CLASSIFIED activities (category in metadata)
    - MEETING_REQUEST also logs a MEETING_ACTION_NEEDED activity (Phase 8 books it)
    - UNSUBSCRIBE logs SUPPRESSED so no further outreach is queued
    """
    from datetime import datetime
    from app.models.outreach import OutreachStatus
    from app.models.lead import LeadStatus
    from app.models.activity import Activity

    # Bounces are delivery failures, not replies — route them first so a
    # DSN can never flip a lead to REPLIED.
    if is_bounce(subject, reply_body):
        outreach.status = OutreachStatus.BOUNCED
        outreach.response_at = datetime.utcnow()
        lead.status = LeadStatus.BOUNCED
        try:
            from app.services.outreach import add_suppression
            addr = (from_address or "")
            import re as _re
            m = _re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", addr)
            if m:
                add_suppression(db, m.group(0), "email", "bounce",
                                source="reply-router", lead_id=lead.id)
        except Exception:
            pass
        db.add(Activity(
            lead_id=lead.id,
            activity_type="EMAIL_BOUNCED",
            description=f"Bounced: {subject or '(no subject)'}",
            metadata_={"from": from_address, "subject": subject,
                       "body": (reply_body or "")[:2000]},
        ))
        db.commit()
        logger.info(f"Lead #{lead.id} bounced (not a reply)")
        return "BOUNCED"

    outreach.status = OutreachStatus.REPLIED
    outreach.response_at = datetime.utcnow()

    category, method = classify_reply_with_fallback(reply_body)
    target = CATEGORY_TO_STATUS.get(category)
    if target:
        lead.status = LeadStatus(target)
    else:
        lead.status = LeadStatus.REPLIED

    db.add(Activity(
        lead_id=lead.id,
        activity_type="REPLY_RECEIVED",
        description=f"Reply received: {subject or '(no subject)'} [{category}]",
        metadata_={"from": from_address, "subject": subject,
                   "body": (reply_body or "")[:2000],
                   "category": category, "method": method},
    ))
    db.add(Activity(
        lead_id=lead.id,
        activity_type="REPLY_CLASSIFIED",
        description=f"Reply classified as {category} (via {method})",
        metadata_={"category": category, "method": method},
    ))

    if category == "MEETING_REQUEST":
        db.add(Activity(
            lead_id=lead.id,
            activity_type="MEETING_ACTION_NEEDED",
            description="Lead requested a meeting — propose a time slot (POST /api/meetings/propose)",
            metadata_={"category": category},
        ))
    elif category == "UNSUBSCRIBE":
        db.add(Activity(
            lead_id=lead.id,
            activity_type="SUPPRESSED",
            description="Lead unsubscribed — excluded from future outreach",
            metadata_={"category": category},
        ))
        try:
            from app.services.outreach import add_suppression
            email = (lead.contact.business_email if lead.contact else None)
            if email:
                add_suppression(db, email, "email", "unsubscribe",
                                source="reply-router", lead_id=lead.id,
                                company_id=lead.company_id)
        except Exception:
            pass

    db.commit()
    logger.info(f"Lead #{lead.id} reply routed: {category} (via {method})")
    return category
