"""Source model — a public exhibitor directory URL."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum as SAEnum
import enum
from sqlalchemy.orm import relationship
from app.database import Base


class SourceStatus(str, enum.Enum):
    PENDING = "PENDING"
    CRAWLING = "CRAWLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(2048), nullable=False)
    source_type = Column(String(100), default="exhibitor_directory")
    status = Column(SAEnum(SourceStatus), default=SourceStatus.PENDING, nullable=False)
    last_crawled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    companies = relationship("Company", back_populates="source", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="source", cascade="all, delete-orphan")
