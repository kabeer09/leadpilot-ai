"""Settings endpoints — seller profile + automation guardrails."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.services.seller import get_seller, update_seller

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SellerUpdate(BaseModel):
    business_name: str | None = None
    sender_name: str | None = None
    business_description: str | None = None
    products: str | list[str] | None = None
    country: str | None = None
    city: str | None = None
    website: str | None = None
    catalogue_url: str | None = None
    meeting_url: str | None = None


@router.get("/seller")
def get_seller_profile(db: Session = Depends(get_db)):
    """Get your business identity used in generated emails/messages."""
    return get_seller(db).to_dict()


@router.put("/seller")
def update_seller_profile(payload: SellerUpdate, db: Session = Depends(get_db)):
    """Update your business identity (takes effect on next generation)."""
    seller = update_seller(db, payload.model_dump(exclude_unset=True))
    return seller.to_dict()


@router.get("/automation")
def get_automation_status(db: Session = Depends(get_db)):
    """Show sending guardrails: kill switch, daily cap, sent-today count."""
    from datetime import datetime
    from app.models.outreach import Outreach, OutreachStatus

    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(Outreach)
        .filter(Outreach.status == OutreachStatus.SENT,
                Outreach.sent_at >= start_of_day)
        .count()
    )
    return {
        "sending_enabled": settings.OUTREACH_SENDING_ENABLED,
        "daily_send_cap": settings.DAILY_SEND_CAP,
        "sent_today": sent_today,
        "remaining_today": max(0, settings.DAILY_SEND_CAP - sent_today),
        "followup_delay_hours": settings.FOLLOWUP_DELAY_HOURS,
        "auto_send_enabled": settings.AUTO_SEND_ENABLED,
        "auto_send_daily_limit": settings.AUTO_SEND_DAILY_LIMIT,
    }


class GoogleClientUpdate(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None


@router.get("/google-client")
def get_google_client(db: Session = Depends(get_db)):
    """Show OAuth client state (secret never exposed, only set/not-set)."""
    from app.models.google_oauth_config import GoogleOAuthConfig
    from app.services import gmail as gmail_service
    row = db.query(GoogleOAuthConfig).order_by(GoogleOAuthConfig.id.asc()).first()
    cid, _, redirect = gmail_service.get_oauth_config()
    return {
        "client_id_set": bool((row.client_id if row else "") or settings.GOOGLE_CLIENT_ID),
        "client_secret_set": bool((row.client_secret if row else "") or settings.GOOGLE_CLIENT_SECRET),
        "redirect_uri": redirect,
        "from_ui": bool(row and (row.client_id or row.client_secret)),
    }


@router.put("/google-client")
def update_google_client(payload: GoogleClientUpdate, db: Session = Depends(get_db)):
    """Save the Google OAuth client from the Settings UI (no .env needed)."""
    from app.models.google_oauth_config import GoogleOAuthConfig
    row = db.query(GoogleOAuthConfig).order_by(GoogleOAuthConfig.id.asc()).first()
    if not row:
        row = GoogleOAuthConfig()
        db.add(row)
    data = payload.model_dump(exclude_unset=True)
    if "client_id" in data and data["client_id"] is not None:
        row.client_id = data["client_id"].strip()
    if "client_secret" in data and data["client_secret"] is not None:
        row.client_secret = data["client_secret"].strip()
    if "redirect_uri" in data and data["redirect_uri"] is not None:
        row.redirect_uri = data["redirect_uri"].strip()
    db.commit()
    return {"message": "Google OAuth client saved"}


class AutomationUpdate(BaseModel):
    auto_send_enabled: bool | None = None
    auto_send_daily_limit: int | None = None


@router.put("/automation")
def update_automation(payload: AutomationUpdate, db: Session = Depends(get_db)):
    """Toggle the daily auto-send schedule (stored in DB, survives restarts)."""
    from app.models.auto_send_state import AutoSendState
    st = db.query(AutoSendState).filter(AutoSendState.id == 1).first()
    if not st:
        st = AutoSendState(id=1)
        db.add(st)
    data = payload.model_dump(exclude_unset=True)
    if "auto_send_enabled" in data and data["auto_send_enabled"] is not None:
        st.enabled = data["auto_send_enabled"]
    if "auto_send_daily_limit" in data and data["auto_send_daily_limit"] is not None:
        st.daily_limit = max(1, min(data["auto_send_daily_limit"], 500))
    db.commit()
    return {"message": "Automation settings saved",
            "auto_send_enabled": st.enabled, "auto_send_daily_limit": st.daily_limit}


@router.get("/auto-send-state")
def get_auto_send_state(db: Session = Depends(get_db)):
    """Show the daily auto-send schedule state."""
    from app.models.auto_send_state import AutoSendState
    st = db.query(AutoSendState).filter(AutoSendState.id == 1).first()
    return {
        "enabled": st.enabled if st and st.enabled is not None else settings.AUTO_SEND_ENABLED,
        "daily_limit": st.daily_limit if st and st.daily_limit else settings.AUTO_SEND_DAILY_LIMIT,
        "send_hour_utc": settings.AUTO_SEND_HOUR,
        "last_run_date": st.last_run_date if st else None,
        "last_sent": st.last_sent if st else 0,
        "last_status": st.last_status if st else "idle",
    }
