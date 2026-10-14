"""Gmail integration (OAuth login, direct send, reply polling).

No Google client libraries — plain REST via httpx. Auth model:
- The user connects once via /api/auth/google (OAuth consent, gmail.send
  + gmail.readonly + calendar scopes). Refresh token is stored in DB.
- Sending uses the stored token; reply polling matches Gmail thread IDs
  against outreach.provider_thread_id.
"""
import base64
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]


def get_oauth_config() -> tuple[str, str, str]:
    """Effective OAuth client: Settings-UI values first, .env as fallback.

    Anyone can paste the client ID/secret in Settings → Google Login, so no
    .env editing is ever required after first setup.
    """
    client_id, client_secret, redirect_uri = "", "", ""
    try:
        from app.database import SessionLocal
        from app.models.google_oauth_config import GoogleOAuthConfig
        db = SessionLocal()
        try:
            row = db.query(GoogleOAuthConfig).order_by(GoogleOAuthConfig.id.asc()).first()
            if row:
                client_id = (row.client_id or "").strip()
                client_secret = (row.client_secret or "").strip()
                redirect_uri = (row.redirect_uri or "").strip()
        finally:
            db.close()
    except Exception:
        pass
    return (
        client_id or settings.GOOGLE_CLIENT_ID,
        client_secret or settings.GOOGLE_CLIENT_SECRET,
        redirect_uri or settings.GOOGLE_REDIRECT_URI,
    )


def is_oauth_configured() -> bool:
    """Check the OAuth client (Settings UI or env) is configured."""
    cid, sec, _ = get_oauth_config()
    return bool(cid and sec)


def build_oauth_url(state: str = "leadpilot") -> str:
    """Build the Google consent URL. Raises if client is not configured."""
    cid, _, redirect = get_oauth_config()
    if not is_oauth_configured():
        raise RuntimeError(
            "Google OAuth not configured — paste your Client ID + Secret in "
            "Settings → Google Login (see docs/gmail_oauth_setup.md)"
        )
    params = {
        "client_id": cid,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an OAuth code for tokens. Returns token JSON."""
    cid, sec, redirect = get_oauth_config()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": cid,
            "client_secret": sec,
            "code": code,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an access token. Returns token JSON."""
    cid, sec, _ = get_oauth_config()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": cid,
            "client_secret": sec,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json()


def get_profile(access_token: str) -> dict:
    """Return the Google account profile (email).

    Uses the Gmail API (covered by gmail.readonly) — the generic
    userinfo endpoint needs openid scopes we don't request.
    """
    resp = httpx.get(
        f"{GMAIL_BASE}/profile",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"email": data.get("emailAddress", "")}


def _valid_access_token(account) -> str:
    """Return a usable access token, refreshing when expired."""
    from app.database import SessionLocal

    if account.access_token and account.token_expiry:
        try:
            if datetime.fromisoformat(str(account.token_expiry)) > datetime.utcnow() + timedelta(minutes=2):
                return account.access_token
        except Exception:
            pass
    data = refresh_access_token(account.refresh_token)
    token = data["access_token"]
    db = SessionLocal()
    try:
        acc = db.query(type(account)).filter(type(account).id == account.id).first()
        if acc:
            acc.access_token = token
            acc.token_expiry = datetime.utcnow() + timedelta(seconds=int(data.get("expires_in", 3600)))
            db.commit()
    finally:
        db.close()
    return token


SEND_MAX_ATTEMPTS = 3
SEND_BACKOFF_SECONDS = (5.0, 20.0, 60.0)


def _retry_after_seconds(resp) -> float:
    """Honor Gmail's Retry-After header when present (seconds)."""
    try:
        value = (resp.headers.get("retry-after") or "").strip()
        if value.isdigit():
            return min(float(value), 300.0)
    except Exception:
        pass
    return 0.0


def _is_retryable_status(status_code: int | None) -> bool:
    return status_code in (429, 500, 502, 503)


def send_email(account, to_email: str, subject: str, body: str,
               thread_id: str | None = None) -> dict:
    """Send an email via the Gmail API.

    Pass thread_id to reply inside the original thread (used for 24h
    follow-ups) instead of starting a new thread.

    Rate limits (429) and transient 5xx are retried with backoff (honoring
    Retry-After). Returns {"message_id": ..., "thread_id": ...} or
    {"error": ..., "retryable": True} when the failure is transient and the
    caller should keep the message queued instead of marking it FAILED.
    """
    import time as _time

    token = _valid_access_token(account)
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_email
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload: dict = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id

    last_error = "unknown error"
    for attempt in range(1, SEND_MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(
                f"{GMAIL_BASE}/messages/send",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=20.0,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Gmail sent to {to_email}: {data.get('id')}")
            return {"message_id": data.get("id"), "thread_id": data.get("threadId")}
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            last_error = str(e)[:500]
            if _is_retryable_status(status) and attempt < SEND_MAX_ATTEMPTS:
                wait = _retry_after_seconds(e.response) or SEND_BACKOFF_SECONDS[attempt - 1]
                logger.warning(
                    f"Gmail send to {to_email} hit HTTP {status} "
                    f"(attempt {attempt}/{SEND_MAX_ATTEMPTS}) — retrying in {wait:.0f}s")
                _time.sleep(wait)
                continue
            if _is_retryable_status(status):
                logger.error(f"Gmail send to {to_email} still rate-limited after "
                             f"{SEND_MAX_ATTEMPTS} attempts: {last_error}")
                return {"error": last_error, "retryable": True}
            logger.error(f"Gmail send failed to {to_email}: {last_error}")
            return {"error": last_error}
        except Exception as e:
            last_error = str(e)[:500]
            logger.error(f"Gmail send failed to {to_email}: {last_error}")
            return {"error": last_error}
    return {"error": last_error, "retryable": True}


def list_recent_messages(account, query: str = "newer_than:2d", max_results: int = 50) -> list[dict]:
    """List recent message IDs matching a Gmail search query."""
    try:
        token = _valid_access_token(account)
        resp = httpx.get(
            f"{GMAIL_BASE}/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "maxResults": max_results},
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json().get("messages", [])
    except Exception as e:
        logger.error(f"Gmail list failed: {e}")
        return []


def get_message(account, message_id: str) -> dict | None:
    """Fetch a message's thread ID, headers and snippet."""
    try:
        token = _valid_access_token(account)
        resp = httpx.get(
            f"{GMAIL_BASE}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "In-Reply-To"]},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        headers = {h["name"].lower(): h.get("value", "")
                   for h in data.get("payload", {}).get("headers", [])}
        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "snippet": data.get("snippet", ""),
            "label_ids": data.get("labelIds", []),
        }
    except Exception as e:
        logger.error(f"Gmail get failed for {message_id}: {e}")
        return None
