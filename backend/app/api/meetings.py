"""Meeting endpoints (Phase 8 — propose → book on Google Calendar + Meet)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.lead import Lead, LeadStatus
from app.models.meeting import Meeting, MeetingStatus
from app.models.activity import Activity
from app.schemas.lead import MeetingResponse
from app.services.calendar import CalendarService

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# Lead states that may receive a meeting proposal
PROPOSABLE = {
    LeadStatus.INTERESTED,
    LeadStatus.MEETING_PROPOSED,
    LeadStatus.REPLIED,
    LeadStatus.QUALIFIED,
    LeadStatus.SCORED,
    LeadStatus.EMAIL_SENT,
    LeadStatus.WHATSAPP_SENT,
}

BLOCKED = {LeadStatus.UNSUBSCRIBED, LeadStatus.SUPPRESSED,
           LeadStatus.BOUNCED, LeadStatus.NOT_INTERESTED}


class ProposeRequest(BaseModel):
    lead_id: int
    start_time: datetime
    end_time: datetime


@router.get("", response_model=list[MeetingResponse])
def list_meetings(db: Session = Depends(get_db)):
    """List all meetings (newest first)."""
    return db.query(Meeting).order_by(Meeting.start_time.desc()).all()


@router.post("/propose", response_model=MeetingResponse, status_code=201)
def propose_meeting(payload: ProposeRequest, db: Session = Depends(get_db)):
    """Propose a meeting slot for a lead (no calendar event yet)."""
    lead = db.query(Lead).filter(Lead.id == payload.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if lead.status in BLOCKED:
        raise HTTPException(status_code=422, detail=f"Lead is {lead.status.value} — meeting not allowed")
    if not lead.contact or not lead.contact.business_email:
        raise HTTPException(status_code=422, detail="Lead has no business email for the invite")
    if payload.end_time <= payload.start_time:
        raise HTTPException(status_code=422, detail="end_time must be after start_time")
    if payload.start_time <= datetime.utcnow():
        raise HTTPException(status_code=422, detail="start_time must be in the future")

    meeting = Meeting(
        lead_id=lead.id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status=MeetingStatus.PROPOSED,
    )
    db.add(meeting)
    db.flush()

    lead.status = LeadStatus.MEETING_PROPOSED
    company = lead.company.company_name if lead.company else f"Lead #{lead.id}"
    db.add(Activity(
        lead_id=lead.id,
        activity_type="MEETING_PROPOSED",
        description=f"Meeting proposed with {company}: {payload.start_time} – {payload.end_time}",
    ))
    db.commit()
    db.refresh(meeting)
    return meeting


@router.post("/{meeting_id}/book", response_model=MeetingResponse)
def book_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """Book a proposed meeting on Google Calendar (creates the Meet link)."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == MeetingStatus.CANCELLED:
        raise HTTPException(status_code=409, detail="Meeting was cancelled")
    if meeting.calendar_event_id:
        return meeting  # idempotent: already booked

    lead = db.query(Lead).filter(Lead.id == meeting.lead_id).first()
    service = CalendarService()
    if not service.is_configured():
        raise HTTPException(
            status_code=409,
            detail="Google Calendar not configured — set GOOGLE_CALENDAR_ENABLED=true plus "
                   "GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN (see docs/calendar_setup.md)",
        )

    company = lead.company.company_name if lead and lead.company else f"Lead #{meeting.lead_id}"
    attendee = lead.contact.business_email if lead and lead.contact else ""
    result = service.book_meeting(
        lead_id=meeting.lead_id,
        start_time=meeting.start_time,
        end_time=meeting.end_time,
        summary=f"Intro call — {company}",
        description=f"Introductory B2B call with {company} (via LeadPilot AI).",
        attendee_email=attendee,
    )
    if not result["success"]:
        raise HTTPException(status_code=502, detail=f"Calendar booking failed: {result['error']}")

    meeting.calendar_event_id = result["event_id"]
    meeting.meet_url = result.get("meet_url")
    meeting.status = MeetingStatus.CONFIRMED
    if lead:
        lead.status = LeadStatus.MEETING_BOOKED
        db.add(Activity(
            lead_id=lead.id,
            activity_type="MEETING_BOOKED",
            description=f"Meeting booked with {company}: {meeting.meet_url or result['event_id']}",
            metadata_={"event_id": result["event_id"], "meet_url": result.get("meet_url")},
        ))
    db.commit()
    db.refresh(meeting)
    return meeting


@router.post("/{meeting_id}/cancel", response_model=MeetingResponse)
def cancel_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """Cancel a meeting (also deletes the calendar event when booked)."""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if meeting.status == MeetingStatus.CANCELLED:
        return meeting

    if meeting.calendar_event_id:
        CalendarService().delete_event(meeting.calendar_event_id)
        meeting.calendar_event_id = None
        meeting.meet_url = None

    meeting.status = MeetingStatus.CANCELLED
    lead = db.query(Lead).filter(Lead.id == meeting.lead_id).first()
    if lead:
        db.add(Activity(lead_id=lead.id, activity_type="MEETING_CANCELLED",
                        description=f"Meeting #{meeting.id} cancelled"))
    db.commit()
    db.refresh(meeting)
    return meeting


class AvailabilityRequest(BaseModel):
    start_time: datetime
    end_time: datetime


@router.post("/availability")
def check_availability(payload: AvailabilityRequest, db: Session = Depends(get_db)):
    """Check calendar availability for a time range."""
    return CalendarService().check_availability(payload.start_time, payload.end_time)


@router.get("/slots")
def available_slots(days_ahead: int = 7, db: Session = Depends(get_db)):
    """Suggest bookable weekday slots (freeBusy-verified when configured)."""
    return CalendarService().find_available_slots(days_ahead=days_ahead)
