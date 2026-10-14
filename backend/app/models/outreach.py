"""Outreach model — email or WhatsApp messages sent to a lead."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class OutreachChannel(str, enum.Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"


class OutreachStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"


class Outreach(Base):
    __tablename__ = "outreach"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    channel = Column(SAEnum(OutreachChannel), nullable=False)
    status = Column(SAEnum(OutreachStatus), default=OutreachStatus.PENDING, nullable=False)
    subject = Column(String(500), nullable=True)
    message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    response_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    # Gmail provider IDs (threading for reply detection)
    provider_message_id = Column(String(255), nullable=True, index=True)
    provider_thread_id = Column(String(255), nullable=True, index=True)
    # Follow-up tracking (Workflow C)
    follow_up_count = Column(Integer, default=0, nullable=False)
    follow_up_sent_at = Column(DateTime, nullable=True)
    # WhatsApp official-template + consent evidence (NULL for email rows)
    template_name = Column(String(255), nullable=True)
    template_language = Column(String(20), nullable=True)
    consent_evidence = Column(Text, nullable=True)
    # Campaign that produced this message (nullable; set by new-batch runs)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    lead = relationship("Lead", back_populates="outreach")
