"""Google Calendar + Meet integration (Phase 8).

Uses the Google Calendar REST API directly via httpx (no extra
dependencies). Auth is a user-supplied OAuth refresh token:

  GOOGLE_CALENDAR_ENABLED=true
  GOOGLE_CLIENT_ID=...
  GOOGLE_CLIENT_SECRET=...
  GOOGLE_REFRESH_TOKEN=...

See docs/calendar_setup.md for how to obtain the refresh token.
Without credentials every method returns a clear "not configured"
result instead of failing obscurely.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"


class CalendarService:
    """Service for Google Calendar operations."""

    def __init__(self):
        self.enabled = settings.GOOGLE_CALENDAR_ENABLED

    def is_configured(self) -> bool:
        """Check Google OAuth credentials are present and enabled."""
        return bool(
            self.enabled
            and settings.GOOGLE_CLIENT_ID
            and settings.GOOGLE_CLIENT_SECRET
            and settings.GOOGLE_REFRESH_TOKEN
        )

    def _access_token(self) -> str:
        """Exchange the refresh token for a short-lived access token."""
        resp = httpx.post(
            TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": settings.GOOGLE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token()}"}

    # -- availability -------------------------------------------------

    def check_availability(self, start_time: datetime, end_time: datetime) -> dict:
        """Check if a time slot is free via the freeBusy API."""
        if not self.is_configured():
            return {"available": True, "conflicts": [],
                    "message": "Calendar integration not configured — slot assumed free"}
        try:
            resp = httpx.post(
                f"{CALENDAR_BASE}/freeBusy",
                headers=self._headers(),
                json={
                    "timeMin": start_time.isoformat(),
                    "timeMax": end_time.isoformat(),
                    "items": [{"id": "primary"}],
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            busy = resp.json().get("calendars", {}).get("primary", {}).get("busy", [])
            return {"available": len(busy) == 0, "conflicts": busy,
                    "message": "Free" if not busy else f"{len(busy)} conflict(s)"}
        except Exception as e:
            logger.error(f"Availability check failed: {e}")
            return {"available": True, "conflicts": [],
                    "message": f"Check failed ({e}); slot assumed free"}

    def find_available_slots(self, days_ahead: int = 7, duration_minutes: int | None = None) -> list[dict]:
        """Suggest weekday 9-11/14-16 slots in the next N days.

        When configured, each candidate is verified with freeBusy;
        otherwise slots are returned unchecked.
        """
        duration = duration_minutes or settings.MEETING_DURATION_MINUTES
        slots = []
        now = datetime.utcnow()
        for day_offset in range(days_ahead):
            day = now + timedelta(days=day_offset)
            if day.weekday() >= 5:
                continue
            for hour in [9, 10, 11, 14, 15, 16]:
                slot_start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                slot_end = slot_start + timedelta(minutes=duration)
                if slot_start <= now:
                    continue
                if self.is_configured():
                    if not self.check_availability(slot_start, slot_end)["available"]:
                        continue
                slots.append({"start": slot_start, "end": slot_end})
                if len(slots) >= 10:
                    return slots
        return slots

    # -- booking --------------------------------------------------------

    def book_meeting(self, lead_id: int, start_time: datetime, end_time: datetime,
                     summary: str, description: str = "",
                     attendee_email: str = "") -> dict:
        """Create a Calendar event with a Google Meet link. Returns
        {"success": True, "event_id": ..., "meet_url": ...} or
        {"success": False, "error": ...}."""
        if not self.is_configured():
            return {"success": False, "error": "Calendar integration not configured"}
        try:
            body: dict = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_time.isoformat()},
                "end": {"dateTime": end_time.isoformat()},
                "conferenceData": {
                    "createRequest": {"requestId": f"leadpilot-{lead_id}-{int(start_time.timestamp())}"}
                },
            }
            if attendee_email:
                body["attendees"] = [{"email": attendee_email}]
            resp = httpx.post(
                f"{CALENDAR_BASE}/calendars/primary/events?conferenceDataVersion=1",
                headers=self._headers(),
                json=body,
                timeout=20.0,
            )
            resp.raise_for_status()
            event = resp.json()
            meet_url = event.get("hangoutLink", "")
            if not meet_url:
                for ep in event.get("conferenceData", {}).get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_url = ep.get("uri", "")
                        break
            logger.info(f"Booked calendar event {event.get('id')} for lead #{lead_id}")
            return {"success": True, "event_id": event.get("id"),
                    "meet_url": meet_url, "html_link": event.get("htmlLink", "")}
        except Exception as e:
            logger.error(f"Calendar booking failed: {e}")
            return {"success": False, "error": str(e)[:500]}

    def check_conflicts(self, start_time: datetime, end_time: datetime) -> list[dict]:
        """Return busy periods overlapping the range (empty when unconfigured)."""
        if not self.is_configured():
            return []
        return self.check_availability(start_time, end_time).get("conflicts", [])

    def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event (used when a meeting is cancelled)."""
        if not self.is_configured():
            return False
        try:
            resp = httpx.delete(
                f"{CALENDAR_BASE}/calendars/primary/events/{event_id}",
                headers=self._headers(),
                timeout=15.0,
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.error(f"Calendar delete failed: {e}")
            return False
