"""Campaign model — groups leads from a source under a named outreach campaign."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    status = Column(SAEnum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False)
    email_enabled = Column(Boolean, default=True, nullable=False)
    whatsapp_enabled = Column(Boolean, default=False, nullable=False)
    followup_delay_hours = Column(Integer, default=24, nullable=False)
    meeting_cta = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    source = relationship("Source", back_populates="campaigns")
    leads = relationship("Lead", back_populates="campaign", cascade="all, delete-orphan")
