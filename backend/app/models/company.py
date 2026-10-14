"""Company model — an exhibitor / business discovered by the crawler."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SAEnum, Float, Boolean
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class EnrichmentStatus(str, enum.Enum):
    PENDING = "PENDING"
    WEBSITE_FOUND = "WEBSITE_FOUND"
    ENRICHED = "ENRICHED"
    NO_PUBLIC_CONTACT = "NO_PUBLIC_CONTACT"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    RATE_LIMITED = "RATE_LIMITED"
    FAILED = "FAILED"


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    company_name = Column(String(500), nullable=False, index=True)
    website = Column(String(2048), nullable=True)
    description = Column(Text, nullable=True)
    industry = Column(String(255), nullable=True)
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    address = Column(Text, nullable=True)
    exhibition_name = Column(String(500), nullable=True)
    hall = Column(String(100), nullable=True)
    booth = Column(String(100), nullable=True)
    source_url = Column(String(2048), nullable=True)
    exhibitor_url = Column(String(2048), nullable=True)

    # Enrichment fields
    enrichment_status = Column(String(50), default="PENDING", nullable=False)
    enrichment_source_url = Column(String(2048), nullable=True)
    enrichment_checked_at = Column(DateTime, nullable=True)
    enrichment_confidence = Column(Float, nullable=True)
    enrichment_method = Column(String(100), nullable=True)
    enrichment_error = Column(Text, nullable=True)

    # Data-quality fields (§4/§7 — all nullable/additive, never backfilled
    # destructively; computed on save and by backfill scripts)
    company_type = Column(String(50), nullable=True)  # manufacturer/wholesaler/...
    completeness = Column(Float, nullable=True)  # 0.0-1.0 fraction of key fields present
    verified = Column(Boolean, nullable=True)  # human-confirmed (NULL = unreviewed)
    last_verified = Column(DateTime, nullable=True)
    # Normalized dedup identifiers (exact-match first, never auto-merge)
    normalized_name = Column(String(500), nullable=True, index=True)
    normalized_domain = Column(String(255), nullable=True, index=True)
    notes = Column(Text, nullable=True)  # internal notes (human/editable)

    # Lifecycle (additive, NULL = active prospect; never deleted, only flagged)
    # active | EXCLUDED_NO_CONTACT | ARCHIVED | MERGED
    lifecycle_status = Column(String(30), nullable=True, index=True)
    merged_into_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    source = relationship("Source", back_populates="companies")
    products = relationship("Product", back_populates="company", cascade="all, delete-orphan")
    contacts = relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    contact_items = relationship("ContactItem", back_populates="company",
                                 cascade="all, delete-orphan")
    leads = relationship("Lead", back_populates="company", cascade="all, delete-orphan")


# Bottom import: registers ContactItem for the relationship above without
# a circular import (contact_item references Company only by string).
from app.models.contact_item import ContactItem  # noqa: F401,E402
