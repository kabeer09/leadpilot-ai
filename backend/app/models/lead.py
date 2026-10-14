"""Lead model — the central entity tracked through the outreach pipeline."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class LeadStatus(str, enum.Enum):
    # Main flow
    NEW = "NEW"
    ENRICHED = "ENRICHED"
    SCORED = "SCORED"
    EMAIL_GENERATED = "EMAIL_GENERATED"
    EMAIL_VALIDATED = "EMAIL_VALIDATED"
    EMAIL_SENT = "EMAIL_SENT"
    FOLLOWUP_DUE = "FOLLOWUP_DUE"
    WHATSAPP_SENT = "WHATSAPP_SENT"
    REPLIED = "REPLIED"
    INTERESTED = "INTERESTED"
    MEETING_PROPOSED = "MEETING_PROPOSED"
    MEETING_BOOKED = "MEETING_BOOKED"
    QUALIFIED = "QUALIFIED"
    # Alternative states
    INVALID = "INVALID"
    FAILED = "FAILED"
    NO_RESPONSE = "NO_RESPONSE"
    NOT_INTERESTED = "NOT_INTERESTED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    BOUNCED = "BOUNCED"
    SUPPRESSED = "SUPPRESSED"


class LeadPriority(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True, index=True)
    lead_score = Column(Integer, default=0, nullable=False)
    lead_priority = Column(SAEnum(LeadPriority), default=LeadPriority.LOW, nullable=False)
    ai_summary = Column(Text, nullable=True)
    ai_reason = Column(Text, nullable=True)
    status = Column(SAEnum(LeadStatus), default=LeadStatus.NEW, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="leads")
    contact = relationship("Contact", back_populates="leads")
    campaign = relationship("Campaign", back_populates="leads")
    outreach = relationship("Outreach", back_populates="lead", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="lead", cascade="all, delete-orphan")
    activities = relationship("Activity", back_populates="lead", cascade="all, delete-orphan")
