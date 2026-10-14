"""CrawlJob model — persistent record of every crawl run (Phase A §9).

The crawler thread updates the row as it progresses (pages visited,
companies discovered/created/updated, duplicates flagged, errors), so a
restart never loses history and retries resume safely via idempotent saves.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    status = Column(String(20), default="PENDING", nullable=False, index=True)
    # PENDING|CRAWLING|COMPLETED|FAILED
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    pages_visited = Column(Integer, default=0, nullable=False)
    companies_discovered = Column(Integer, default=0, nullable=False)
    records_created = Column(Integer, default=0, nullable=False)
    records_updated = Column(Integer, default=0, nullable=False)
    duplicates_flagged = Column(Integer, default=0, nullable=False)
    errors = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    source = relationship("Source")
