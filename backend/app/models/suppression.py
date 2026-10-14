"""Suppression + merge-audit models (additive, append-only).

Suppression: normalized email/phone + reason. Checked before ANY send.
MergeAudit: every company merge recorded with canonical + merged IDs,
repointed relationship counts, actor and timestamp. Merged rows are kept
(lifecycle_status=MERGED), never deleted — fully recoverable.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from app.database import Base


class Suppression(Base):
    __tablename__ = "suppressions"

    id = Column(Integer, primary_key=True, index=True)
    # normalized email (lowercased) or normalized phone digits
    value = Column(String(255), nullable=False, index=True)
    # email | phone
    value_type = Column(String(20), nullable=False, index=True)
    # unsubscribe | bounce | not_interested | manual | abuse
    reason = Column(String(50), nullable=False)
    source = Column(String(100), nullable=True)  # reply | webhook | manual | migration
    company_id = Column(Integer, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MergeAudit(Base):
    __tablename__ = "merge_audit"

    id = Column(Integer, primary_key=True, index=True)
    canonical_company_id = Column(Integer, nullable=False, index=True)
    merged_company_id = Column(Integer, nullable=False, index=True)
    match_type = Column(String(50), nullable=True)
    confidence = Column(Integer, nullable=True)
    leads_repointed = Column(Integer, default=0, nullable=False)
    contacts_repointed = Column(Integer, default=0, nullable=False)
    items_repointed = Column(Integer, default=0, nullable=False)
    outreach_preserved = Column(Integer, default=0, nullable=False)
    actor = Column(String(100), default="api", nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
