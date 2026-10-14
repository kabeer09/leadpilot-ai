"""Contact model — publicly listed business contact information."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class ContactType(str, enum.Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    WHATSAPP = "WHATSAPP"


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    business_email = Column(String(255), nullable=True, index=True)
    phone = Column(String(50), nullable=True)
    whatsapp_number = Column(String(50), nullable=True)
    # Second email when directory and website disagree (see email_source)
    alternate_email = Column(String(255), nullable=True)
    # Where business_email came from: 'directory' | 'website'
    email_source = Column(String(20), default="directory", nullable=False)
    # Normalized dedup identifiers (exact-match first, never auto-merge)
    normalized_email = Column(String(255), nullable=True, index=True)
    normalized_phone = Column(String(50), nullable=True, index=True)
    email_source_url = Column(String(2048), nullable=True)
    whatsapp_source_url = Column(String(2048), nullable=True)
    verified = Column(Boolean, default=False, nullable=False)
    contact_type = Column(SAEnum(ContactType), default=ContactType.EMAIL, nullable=False)
    # WhatsApp eligibility (NULL = unevaluated; never assume a phone has WhatsApp)
    # eligible | ineligible | opted_out | unknown
    consent_status = Column(String(20), nullable=True)
    whatsapp_eligible = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="contacts")
    leads = relationship("Lead", back_populates="contact", cascade="all, delete-orphan")
