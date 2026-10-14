"""GoogleOAuthConfig model — OAuth client pasted in Settings UI (no .env needed)."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from app.database import Base


class GoogleOAuthConfig(Base):
    __tablename__ = "google_oauth_config"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(500), nullable=False, default="")
    client_secret = Column(Text, nullable=False, default="")
    redirect_uri = Column(String(500), nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
