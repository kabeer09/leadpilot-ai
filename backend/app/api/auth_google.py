"""Google OAuth endpoints — connect Gmail/Calendar (user login)."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.config import settings
from app.models.google_account import GoogleAccount
from app.services import gmail as gmail_service

router = APIRouter(prefix="/api/auth/google", tags=["google-auth"])


@router.get("/login")
def google_login(db: Session = Depends(get_db)):
    """Return the Google consent URL (frontend redirects the user there)."""
    if not gmail_service.is_oauth_configured():
        raise HTTPException(
            status_code=409,
            detail="Google OAuth not configured — set GOOGLE_CLIENT_ID and "
                   "GOOGLE_CLIENT_SECRET, then see docs/gmail_oauth_setup.md",
        )
    return {"auth_url": gmail_service.build_oauth_url()}


@router.get("/callback")
def google_callback(code: str | None = None, error: str | None = None,
                    db: Session = Depends(get_db)):
    """OAuth callback (Google redirects here). Stores tokens, redirects to UI."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    frontend = settings.FRONTEND_URL.rstrip("/")
    if error or not code:
        _log.warning(f"Google callback without code (error={error})")
        return RedirectResponse(f"{frontend}/settings?google=error&reason=denied")
    try:
        tokens = gmail_service.exchange_code(code)
    except Exception as e:
        _log.error(f"Google code exchange failed: {e}")
        return RedirectResponse(f"{frontend}/settings?google=error&reason=token")
    try:
        profile = gmail_service.get_profile(tokens["access_token"])
        email = profile.get("email", "")
        if not email:
            raise RuntimeError("empty email in profile")
    except Exception as e:
        _log.error(f"Google profile fetch failed: {e}")
        return RedirectResponse(f"{frontend}/settings?google=error&reason=profile")

    account = db.query(GoogleAccount).filter(GoogleAccount.email == email).first()
    if not account:
        account = GoogleAccount(email=email)
        db.add(account)
    account.email = email
    account.refresh_token = tokens.get("refresh_token") or account.refresh_token
    account.access_token = tokens.get("access_token")
    account.token_expiry = datetime.utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    account.scopes = " ".join(gmail_service.SCOPES)
    db.commit()
    # Immediate access check: prove the grant works right now (read one
    # inbox page) so the dashboard never shows a dead connection.
    try:
        msgs = gmail_service.list_recent_messages(account, max_results=1)
        account.access_ok = 1
        account.last_verified_at = datetime.utcnow()
        db.commit()
        _log.info(f"Gmail {email}: access verified ({len(msgs)} probe messages)")
        return RedirectResponse(f"{frontend}/settings?google=connected&verified=1")
    except Exception as e:
        _log.warning(f"Gmail {email}: connected but access check failed: {e}")
        account.access_ok = 0
        db.commit()
        return RedirectResponse(f"{frontend}/settings?google=connected&verified=0")


@router.get("/status")
def google_status(db: Session = Depends(get_db)):
    """Show connected Google accounts (tokens never exposed).

    Anyone can connect their own Gmail through the app-level OAuth client
    — no .env edits needed. The most-recently-connected/selected account
    is the active sender.
    """
    from app.services.outreach import get_active_account
    accounts = db.query(GoogleAccount).order_by(GoogleAccount.updated_at.desc()).all()
    active = get_active_account(db)
    return {
        "connected": len(accounts) > 0,
        "email": active.email if active else None,
        "active_id": active.id if active else None,
        "accounts": [{"id": a.id, "email": a.email,
                      "active": bool(active and a.id == active.id),
                      "updated_at": a.updated_at,
                      "access_ok": bool(getattr(a, "access_ok", 0)),
                      "last_verified_at": getattr(a, "last_verified_at", None)} for a in accounts],
        "oauth_configured": gmail_service.is_oauth_configured(),
    }


class SelectRequest(BaseModel):
    account_id: int


@router.post("/select")
def google_select(payload: SelectRequest, db: Session = Depends(get_db)):
    """Select which connected Gmail sends (most-recently-used wins)."""
    from app.services.outreach import touch_account
    account = db.query(GoogleAccount).filter(
        GoogleAccount.id == payload.account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Google account not found")
    touch_account(db, account)
    return {"message": "Active Gmail account updated", "email": account.email}


class DisconnectRequest(BaseModel):
    account_id: int | None = None


@router.post("/disconnect")
def google_disconnect(payload: DisconnectRequest | None = None,
                      db: Session = Depends(get_db)):
    """Remove one (or the active) connected Google account."""
    from app.services.outreach import get_active_account
    account_id = payload.account_id if payload else None
    if account_id:
        account = db.query(GoogleAccount).filter(
            GoogleAccount.id == account_id).first()
    else:
        account = get_active_account(db)
    if not account:
        return {"message": "No account connected"}
    email = account.email
    db.delete(account)
    db.commit()
    return {"message": f"Google account {email} disconnected"}


@router.get("/test-send")
def google_test_send(to: str = Query(...), account_id: int | None = None,
                     db: Session = Depends(get_db)):
    """Send a test email through Gmail (verifies the wiring)."""
    from app.services.outreach import get_active_account
    if account_id:
        account = db.query(GoogleAccount).filter(
            GoogleAccount.id == account_id).first()
    else:
        account = get_active_account(db)
    if not account:
        raise HTTPException(status_code=409, detail="No Google account connected")
    result = gmail_service.send_email(
        account, to,
        "LeadPilot AI test email",
        "This is a test email from LeadPilot AI. Your Gmail connection works.",
    )
    if "error" in result:
        account.access_ok = 0
        db.commit()
        raise HTTPException(status_code=502, detail=f"Gmail send failed: {result['error']}")
    account.access_ok = 1
    account.last_verified_at = datetime.utcnow()
    db.commit()
    return {"message": "Test email sent", **result}


@router.get("/self-test")
def google_self_test(db: Session = Depends(get_db)):
    """Diagnose the OAuth client without user interaction.

    Sends a dummy code exchange to Google and returns Google's EXACT
    error — distinguishes unknown client_id from wrong secret.
    """
    import httpx
    from app.config import settings

    cid = (settings.GOOGLE_CLIENT_ID or "").strip()
    sec = (settings.GOOGLE_CLIENT_SECRET or "").strip()
    if not cid or not sec:
        return {"ok": False, "problem": "GOOGLE_CLIENT_ID/SECRET empty in backend .env"}
    try:
        resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": cid, "client_secret": sec,
                  "code": "dummy-code-for-diagnosis",
                  "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                  "grant_type": "authorization_code"},
            timeout=20.0,
        )
        body = resp.json()
    except Exception as e:
        return {"ok": False, "problem": f"no response from Google: {e}"}
    if body.get("error") == "invalid_grant":
        # Google accepted client_id + secret (it only rejects the dummy code):
        # the pair is VALID. A browser 'client not found' then means a stale
        # consent URL — reconnect fresh from Settings.
        hint = ("credentials VALID (Google only rejects the dummy code). "
                "If the browser consent screen says 'client not found', you opened "
                "a stale consent URL — click Connect with Google again fresh from "
                "Settings and compare its client_id with the prefix below.")
    elif body.get("error") == "invalid_client" and \
            "client" in (body.get("error_description") or "").lower():
        hint = ("client_id unknown to Google — re-copy it from Credentials (exact project). ")
    else:
        hint = ("secret mismatch — Reset secret in Credentials and update backend/.env, "
                "then restart backend.")
    return {
        "ok": False,
        "client_id_prefix": cid[:12] + "...",
        "client_id_suffix": "..." + cid[-30:],
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "google_http_status": resp.status_code,
        "google_error": body.get("error"),
        "google_error_description": body.get("error_description"),
        "hint": hint,
    }
