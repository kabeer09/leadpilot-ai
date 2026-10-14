"""Automation health: last runs, pending jobs, latest errors (all real records)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.outreach import Outreach, OutreachStatus, OutreachChannel
from app.models.crawl_job import CrawlJob
from app.config import settings

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.get("/health")
def automation_health(db: Session = Depends(get_db)):
    """Automation health panel: last successful crawl/email/reply checks, pending, errors."""
    last_crawl = (
        db.query(CrawlJob)
        .filter(CrawlJob.status == "COMPLETED")
        .order_by(CrawlJob.finished_at.desc())
        .first()
    )
    running_crawls = (
        db.query(func.count(CrawlJob.id)).filter(CrawlJob.status == "CRAWLING").scalar() or 0
    )
    last_email = (
        db.query(func.max(Outreach.sent_at))
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.SENT)
        .scalar()
    )
    last_reply = (
        db.query(func.max(Outreach.response_at))
        .filter(Outreach.status == OutreachStatus.REPLIED)
        .scalar()
    )
    last_whatsapp = (
        db.query(func.max(Outreach.sent_at))
        .filter(Outreach.channel == OutreachChannel.WHATSAPP,
                Outreach.status == OutreachStatus.SENT)
        .scalar()
    )
    pending_email = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.EMAIL,
                Outreach.status == OutreachStatus.PENDING)
        .scalar() or 0
    )
    pending_wa = (
        db.query(func.count(Outreach.id))
        .filter(Outreach.channel == OutreachChannel.WHATSAPP,
                Outreach.status == OutreachStatus.PENDING)
        .scalar() or 0
    )
    latest_errors = (
        db.query(Outreach)
        .filter(Outreach.status == OutreachStatus.FAILED)
        .order_by(Outreach.updated_at.desc())
        .limit(5)
        .all()
    )
    from app.models.google_account import GoogleAccount
    gmail_connected = db.query(func.count(GoogleAccount.id)).scalar() or 0
    return {
        "last_crawl_at": getattr(last_crawl, "finished_at", None),
        "running_crawls": running_crawls,
        "last_email_sent_at": last_email,
        "last_reply_at": last_reply,
        "last_whatsapp_sent_at": last_whatsapp,
        "pending_email": pending_email,
        "pending_whatsapp": pending_wa,
        "gmail_accounts_connected": gmail_connected,
        "scheduler": {
            "followup_enabled": settings.FOLLOWUP_SCHEDULER_ENABLED,
            "scan_interval_minutes": settings.FOLLOWUP_SCAN_INTERVAL_MINUTES,
            "auto_send_enabled": settings.AUTO_SEND_ENABLED,
            "followup_auto_send_enabled": settings.FOLLOWUP_AUTO_SEND_ENABLED,
        },
        "latest_errors": [
            {"outreach_id": o.id, "lead_id": o.lead_id, "channel": o.channel.value,
             "error": (o.error or "")[:200], "at": o.updated_at}
            for o in latest_errors
        ],
    }
