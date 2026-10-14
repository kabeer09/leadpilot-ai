"""Seller profile — your business identity used in generated outreach.

Single-row table (id=1). Seeded with defaults on first read; edited via
PUT /api/settings/seller (Settings page).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base


class SellerProfile(Base):
    __tablename__ = "seller_profiles"

    id = Column(Integer, primary_key=True)
    business_name = Column(String(255), nullable=False, default="New Look Impex")
    sender_name = Column(String(255), nullable=True)
    business_description = Column(Text, nullable=True)
    products = Column(Text, nullable=True)  # comma-separated
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    website = Column(String(2048), nullable=True)
    catalogue_url = Column(String(2048), nullable=True)
    meeting_url = Column(String(2048), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        products = [p.strip() for p in (self.products or "").split(",") if p.strip()]
        return {
            "business_name": self.business_name,
            "sender_name": self.sender_name or "",
            "business_description": self.business_description or "",
            "products": products,
            "country": self.country or "",
            "city": self.city or "",
            "website": self.website or "",
            "catalogue_url": self.catalogue_url or "",
            "meeting_url": self.meeting_url or "",
        }
