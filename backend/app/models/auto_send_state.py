"""AutoSendState model — tracks the daily automated bulk send."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from app.database import Base


class AutoSendState(Base):
    __tablename__ = "auto_send_state"

    id = Column(Integer, primary_key=True, index=True)
    last_run_date = Column(String(10), nullable=True)  # YYYY-MM-DD (UTC)
    last_sent = Column(Integer, default=0, nullable=False)
    last_status = Column(String(50), default="idle", nullable=False)
    # User-controlled schedule (Settings UI). None = fall back to env defaults.
    enabled = Column(Boolean, nullable=True)
    daily_limit = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
