"""GoogleAccount model — the connected Gmail/Google identity (OAuth)."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    refresh_token = Column(Text, nullable=False)
    access_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    scopes = Column(Text, nullable=True)
    # Immediate-access verification (set on OAuth callback + test-send)
    last_verified_at = Column(DateTime, nullable=True)
    access_ok = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
