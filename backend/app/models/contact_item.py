"""ContactItem model — one row per discovered contact value.

The legacy `contacts` row stays the primary-contact rollup (never removed).
Every email/phone/WhatsApp the crawler finds is ALSO stored here with its
exact source URL + page type, so nothing is overwritten and every value
is auditable. Tables are additive; no existing data is touched.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class ContactItem(Base):
    __tablename__ = "contact_items"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    # EMAIL | PHONE | WHATSAPP
    contact_type = Column(String(20), nullable=False, index=True)
    # Normalized value for duplicate detection (lowercased email / E.164-ish digits)
    normalized_value = Column(String(255), nullable=False, index=True)
    # Original displayed value (never normalized — shown in UI)
    display_value = Column(String(500), nullable=False)
    # Exact page where it was found
    source_url = Column(String(2048), nullable=True)
    # home | contact | about | products | wholesale | exhibitor-profile | directory | other
    source_page_type = Column(String(50), nullable=True)
    is_public_business = Column(Boolean, default=True, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    # scraped | verified | invalid
    verification_status = Column(String(20), default="scraped", nullable=False)
    # valid | invalid | unknown
    validity_status = Column(String(20), default="unknown", nullable=False)
    # active | merged | suppressed
    merge_status = Column(String(20), default="active", nullable=False)
    extracted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="contact_items")
