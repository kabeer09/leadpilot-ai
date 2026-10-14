"""Data-quality endpoints: duplicates, safe merges, exclusions, suppressions.

Safety rules (enforced, not just documented):
- Nothing is ever auto-merged; preview is read-only, apply needs explicit IDs.
- Merges repoint relationships and flag the duplicate MERGED — never delete.
- Exclusions only set lifecycle flags (recoverable via PATCH).
- Applying a merge or exclusion never sends any email/WhatsApp.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models.company import Company
from app.models.contact import Contact
from app.models.contact_item import ContactItem

router = APIRouter(prefix="/api/data-quality", tags=["data-quality"])


@router.get("/duplicates")
def data_quality_duplicates(status: str = "pending",
                            limit: int = Query(100, ge=1, le=500),
                            db: Session = Depends(get_db)):
    """Duplicate candidates (same shape as /api/companies/duplicates)."""
    from app.models.duplicate_candidate import DuplicateCandidate
    rows = (
        db.query(DuplicateCandidate, Company)
        .join(Company, Company.id == DuplicateCandidate.company_a_id)
        .filter(DuplicateCandidate.status == status)
        .order_by(DuplicateCandidate.confidence.desc())
        .limit(limit)
        .all()
    )
    out = []
    for cand, comp_a in rows:
        comp_b = db.query(Company).filter(Company.id == cand.company_b_id).first()
        out.append({
            "id": cand.id,
            "match_type": cand.match_type,
            "confidence": cand.confidence,
            "status": cand.status,
            "created_at": cand.created_at,
            "company_a": {"id": comp_a.id, "name": comp_a.company_name,
                          "source_id": comp_a.source_id, "website": comp_a.website},
            "company_b": ({"id": comp_b.id, "name": comp_b.company_name,
                           "source_id": comp_b.source_id, "website": comp_b.website}
                          if comp_b else None),
        })
    return out


class MergeRequest(BaseModel):
    canonical_id: int
    duplicate_id: int
    note: str | None = None


@router.post("/deduplicate/preview")
def deduplicate_preview(payload: MergeRequest, db: Session = Depends(get_db)):
    """Dry-run merge report. Read-only: nothing is written."""
    from app.services.dedup import preview_merge
    report = preview_merge(db, payload.canonical_id, payload.duplicate_id)
    if not report.get("ok"):
        raise HTTPException(status_code=422, detail=report.get("error"))
    return report


@router.post("/deduplicate/apply")
def deduplicate_apply(payload: MergeRequest, db: Session = Depends(get_db)):
    """Merge duplicate -> canonical (transactional, audited, recoverable).

    Preserves all lead/outreach/message history by repointing. Merged row
    stays in the DB flagged MERGED. Sends nothing.
    """
    from app.services.dedup import apply_merge
    result = apply_merge(db, payload.canonical_id, payload.duplicate_id,
                         actor="api", note=payload.note)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.get("/merges")
def list_merges(limit: int = Query(100, ge=1, le=500),
                db: Session = Depends(get_db)):
    """Merge audit log (newest first)."""
    from app.models.suppression import MergeAudit
    rows = (db.query(MergeAudit).order_by(MergeAudit.id.desc()).limit(limit).all())
    return [{
        "id": m.id, "canonical_company_id": m.canonical_company_id,
        "merged_company_id": m.merged_company_id, "match_type": m.match_type,
        "confidence": m.confidence, "leads_repointed": m.leads_repointed,
        "contacts_repointed": m.contacts_repointed,
        "items_repointed": m.items_repointed,
        "outreach_preserved": m.outreach_preserved, "actor": m.actor,
        "note": m.note, "created_at": m.created_at,
    } for m in rows]


def _no_contact_query(db: Session):
    """Companies with no usable email/phone/WhatsApp anywhere."""
    with_values = (
        db.query(Contact.company_id).filter(
            Contact.business_email.isnot(None) | Contact.phone.isnot(None) |
            Contact.whatsapp_number.isnot(None)).distinct()
    )
    with_items = db.query(ContactItem.company_id).distinct()
    return db.query(Company).filter(
        Company.lifecycle_status.is_(None),
        ~Company.id.in_(with_values),
        ~Company.id.in_(with_items))


@router.post("/exclusions/preview")
def exclusions_preview(db: Session = Depends(get_db)):
    """Dry-run: which active companies would be excluded (read-only)."""
    q = _no_contact_query(db)
    total = q.count()
    sample = [{"id": c.id, "name": c.company_name, "source_id": c.source_id}
              for c in q.order_by(Company.id).limit(20).all()]
    return {"would_exclude": total, "sample": sample, "dry_run": True,
            "note": "Rows stay in the DB flagged EXCLUDED_NO_CONTACT; nothing is deleted."}


@router.post("/exclusions/apply")
def exclusions_apply(db: Session = Depends(get_db)):
    """Flag no-contact companies EXCLUDED_NO_CONTACT (recoverable, no deletes)."""
    rows = _no_contact_query(db).all()
    for company in rows:
        company.lifecycle_status = "EXCLUDED_NO_CONTACT"
    db.commit()
    return {"excluded": len(rows),
            "note": "Restore any row via PATCH /api/companies/{id} {\"lifecycle_status\": \"active\"}."}


@router.get("/suppressions")
def list_suppressions(limit: int = Query(200, ge=1, le=1000),
                      db: Session = Depends(get_db)):
    """Suppression list (unsubscribe/bounce/opt-out)."""
    from app.models.suppression import Suppression
    rows = (db.query(Suppression).order_by(Suppression.id.desc()).limit(limit).all())
    return [{
        "id": s.id, "value": s.value, "value_type": s.value_type,
        "reason": s.reason, "source": s.source, "company_id": s.company_id,
        "lead_id": s.lead_id, "created_at": s.created_at,
    } for s in rows]


class SuppressionAdd(BaseModel):
    value: str
    value_type: str = "email"  # email|phone
    reason: str = "manual"
    company_id: int | None = None
    lead_id: int | None = None


@router.post("/suppressions")
def add_suppression_endpoint(payload: SuppressionAdd, db: Session = Depends(get_db)):
    """Manually suppress an address/number (checked before every send)."""
    from app.services.outreach import add_suppression
    if payload.value_type not in ("email", "phone"):
        raise HTTPException(status_code=422, detail="value_type must be email|phone")
    created = add_suppression(db, payload.value, payload.value_type,
                              payload.reason, source="manual",
                              company_id=payload.company_id, lead_id=payload.lead_id)
    db.commit()
    return {"added": created}


class WhatsAppApprove(BaseModel):
    evidence: str | None = None  # e.g. "confirmed via website chat widget 2026-10-14"


@router.post("/whatsapp/approve/{contact_id}")
def approve_whatsapp(contact_id: int, payload: WhatsAppApprove,
                     db: Session = Depends(get_db)):
    """Human approval: mark a scraped number eligible for WhatsApp.

    Required before any automated WhatsApp message. Records the evidence.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if not (contact.whatsapp_number or "").strip():
        raise HTTPException(status_code=422, detail="Contact has no WhatsApp number")
    contact.whatsapp_eligible = True
    contact.consent_status = "eligible"
    if payload.evidence:
        from app.models.lead import Lead
        from app.models.activity import Activity
        lead = db.query(Lead).filter(Lead.contact_id == contact.id).first()
        if lead:
            db.add(Activity(
                lead_id=lead.id,
                activity_type="WHATSAPP_APPROVED",
                description=f"WhatsApp approved for {contact.whatsapp_number}: {payload.evidence[:200]}",
            ))
    db.commit()
    return {"message": "WhatsApp approved", "contact_id": contact_id}
