"""Meeting model — Google Calendar events with Google Meet links."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class MeetingStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    calendar_event_id = Column(String(500), nullable=True)
    meet_url = Column(String(2048), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(SAEnum(MeetingStatus), default=MeetingStatus.PROPOSED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="meetings")
