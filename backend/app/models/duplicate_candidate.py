"""DuplicateCandidate model — possible cross-source duplicates for human review.

Never auto-merged: exact identifier matches create a candidate row, fuzzy
matches only flag for review. Resolution (confirm/reject) is a future
Phase B action; this table only records candidates idempotently.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"

    id = Column(Integer, primary_key=True, index=True)
    company_a_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    company_b_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    match_type = Column(String(50), nullable=False)  # domain|email|phone|name_exact|name_fuzzy
    confidence = Column(Float, default=0.0, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending|reviewed|dismissed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("company_a_id", "company_b_id", "match_type",
                         name="uq_dup_candidate_pair"),
    )
