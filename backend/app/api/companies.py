"""Company endpoints."""
import csv
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.models.company import Company, EnrichmentStatus
from app.models.product import Product
from app.models.source import Source
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.activity import Activity
from app.schemas.company import CompanyResponse, CompanyDetailResponse, CompanyListResponse
from app.services.enrichment import ContactEnrichmentService, CSVImportService, WebsiteDiscoveryService
from app.services.lead_scoring import score_lead

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("", response_model=list[CompanyListResponse])
def list_companies(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    country: str | None = None,
    source_id: int | None = None,
    category: str | None = None,
    has_contact: bool | None = None,
    company_type: str | None = None,
    has_email: bool | None = None,
    has_phone: bool | None = None,
    has_whatsapp: bool | None = None,
    contactable: bool | None = None,
    lifecycle: str | None = Query("active", description="active|all|excluded|archived|merged"),
    has_website: bool | None = None,
    verified: bool | None = None,
    min_completeness: float | None = None,
    enrichment_status: str | None = None,
    unresolved_only: bool = False,
    db: Session = Depends(get_db),
):
    from app.models.contact_item import ContactItem
    base = db.query(Company)
    # Lifecycle: default view hides excluded/archived/merged (recoverable via filter)
    if lifecycle == "active":
        base = base.filter((Company.lifecycle_status.is_(None)) |
                           (Company.lifecycle_status == "active"))
    elif lifecycle == "excluded":
        base = base.filter(Company.lifecycle_status == "EXCLUDED_NO_CONTACT")
    elif lifecycle == "archived":
        base = base.filter(Company.lifecycle_status == "ARCHIVED")
    elif lifecycle == "merged":
        base = base.filter(Company.lifecycle_status == "MERGED")
    if search:
        base = base.filter(Company.company_name.ilike(f"%{search}%"))
    if country:
        base = base.filter(Company.country.ilike(f"%{country}%"))
    if source_id:
        base = base.filter(Company.source_id == source_id)
    if category:
        base = base.filter(Company.id.in_(
            db.query(Product.company_id).filter(Product.category.ilike(f"%{category}%"))))
    if company_type:
        base = base.filter(Company.company_type == company_type)
    if has_email is True:
        base = base.filter(Company.id.in_(
            db.query(Contact.company_id).filter(Contact.business_email.isnot(None))))
    elif has_email is False:
        base = base.filter(~Company.id.in_(
            db.query(Contact.company_id).filter(Contact.business_email.isnot(None))))
    if has_phone is True:
        base = base.filter(Company.id.in_(
            db.query(Contact.company_id).filter(Contact.phone.isnot(None))))
    elif has_phone is False:
        base = base.filter(~Company.id.in_(
            db.query(Contact.company_id).filter(Contact.phone.isnot(None))))
    if has_whatsapp is True:
        base = base.filter(Company.id.in_(
            db.query(Contact.company_id).filter(Contact.whatsapp_number.isnot(None))))
    elif has_whatsapp is False:
        base = base.filter(~Company.id.in_(
            db.query(Contact.company_id).filter(Contact.whatsapp_number.isnot(None))))
    if contactable is True:
        base = base.filter(Company.id.in_(
            db.query(Contact.company_id).filter(
                Contact.business_email.isnot(None) | Contact.phone.isnot(None) |
                Contact.whatsapp_number.isnot(None))))
    elif contactable is False:
        base = base.filter(
            ~Company.id.in_(db.query(ContactItem.company_id)),
            ~Company.id.in_(
                db.query(Contact.company_id).filter(
                    Contact.business_email.isnot(None) | Contact.phone.isnot(None) |
                    Contact.whatsapp_number.isnot(None))))
    if has_website is True:
        base = base.filter(Company.website.isnot(None), Company.website != "")
    elif has_website is False:
        base = base.filter((Company.website.is_(None)) | (Company.website == ""))
    if verified is True:
        base = base.filter(Company.verified.is_(True))
    elif verified is False:
        base = base.filter(Company.verified.isnot(True))
    if min_completeness is not None:
        base = base.filter(Company.completeness >= min_completeness)
    if enrichment_status:
        base = base.filter(Company.enrichment_status == enrichment_status)
    if unresolved_only:
        base = base.filter(Company.enrichment_status.in_([
            EnrichmentStatus.PENDING, EnrichmentStatus.FAILED, EnrichmentStatus.NO_PUBLIC_CONTACT
        ]))
    if has_contact:
        base = base.filter(Company.id.in_(
            db.query(Contact.company_id).filter(
                Contact.business_email.isnot(None) | Contact.phone.isnot(None))))
    total = base.count()
    response.headers["X-Total-Count"] = str(total)
    return base.options(
        selectinload(Company.contacts),
        selectinload(Company.products),
    ).order_by(Company.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/filters")
def company_filters(db: Session = Depends(get_db)):
    """Distinct filter values: fairs (sources), countries, product categories."""
    sources = db.query(Source).order_by(Source.name.asc()).all()
    countries = [r[0] for r in db.query(Company.country).filter(
        Company.country.isnot(None), Company.country != "").distinct().order_by(Company.country).all()]
    categories = [r[0] for r in db.query(Product.category).filter(
        Product.category.isnot(None), Product.category != "").distinct().order_by(Product.category).all()]
    company_types = [r[0] for r in db.query(Company.company_type).filter(
        Company.company_type.isnot(None), Company.company_type != "").distinct().order_by(Company.company_type).all()]
    return {
        "sources": [{"id": s.id, "name": s.name} for s in sources],
        "countries": countries,
        "categories": categories,
        "company_types": company_types,
    }


@router.get("/duplicates")
def list_duplicate_candidates(status: str = "pending",
                              limit: int = Query(100, ge=1, le=500),
                              db: Session = Depends(get_db)):
    """Possible duplicates awaiting human review (never auto-merged)."""
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


class DuplicateResolve(BaseModel):
    status: str  # reviewed|dismissed


@router.post("/duplicates/{candidate_id}/resolve")
def resolve_duplicate_candidate(candidate_id: int, payload: DuplicateResolve,
                                db: Session = Depends(get_db)):
    """Mark a duplicate candidate reviewed/dismissed (no auto-merge ever)."""
    from app.models.duplicate_candidate import DuplicateCandidate
    if payload.status not in ("reviewed", "dismissed"):
        raise HTTPException(status_code=422, detail="status must be reviewed|dismissed")
    cand = db.query(DuplicateCandidate).filter(
        DuplicateCandidate.id == candidate_id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    cand.status = payload.status
    db.commit()
    return {"message": f"Candidate {payload.status}", "id": candidate_id}


@router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company(company_id: int, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


class CompanyUpdate(BaseModel):
    notes: str | None = None
    verified: bool | None = None
    company_type: str | None = None
    lifecycle_status: str | None = None  # active|EXCLUDED_NO_CONTACT|ARCHIVED


@router.patch("/{company_id}", response_model=CompanyDetailResponse)
def update_company(company_id: int, payload: CompanyUpdate,
                   db: Session = Depends(get_db)):
    """Human curation: internal notes, verified flag, company type, lifecycle.

    Setting verified=True stamps last_verified. lifecycle_status archives /
    restores ("active" clears the flag). Every edit is audit-logged on the
    company's first lead timeline. Never touches crawled data.
    """
    from datetime import datetime as _dt
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    data = payload.model_dump(exclude_unset=True)
    changes: list[str] = []
    if "notes" in data:
        company.notes = data["notes"]
        changes.append("notes")
    if "company_type" in data and data["company_type"] is not None:
        allowed = {"manufacturer", "wholesaler", "distributor", "retailer",
                   "importer", "exporter", "brand", "unknown"}
        if data["company_type"] not in allowed:
            raise HTTPException(status_code=422,
                                detail=f"company_type must be one of {sorted(allowed)}")
        company.company_type = data["company_type"]
        changes.append(f"company_type={data['company_type']}")
    if "verified" in data and data["verified"] is not None:
        company.verified = data["verified"]
        company.last_verified = _dt.utcnow() if data["verified"] else None
        changes.append(f"verified={data['verified']}")
    if "lifecycle_status" in data and data["lifecycle_status"] is not None:
        allowed_lc = {"active", "EXCLUDED_NO_CONTACT", "ARCHIVED"}
        if data["lifecycle_status"] not in allowed_lc:
            raise HTTPException(status_code=422,
                                detail=f"lifecycle_status must be one of {sorted(allowed_lc)}")
        company.lifecycle_status = (None if data["lifecycle_status"] == "active"
                                    else data["lifecycle_status"])
        changes.append(f"lifecycle={data['lifecycle_status']}")
    if changes:
        lead = db.query(Lead).filter(Lead.company_id == company.id).first()
        if lead:
            db.add(Activity(
                lead_id=lead.id,
                activity_type="COMPANY_EDITED",
                description=f"Human edit: {', '.join(changes)}",
            ))
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}/contacts")
def company_contacts(company_id: int, db: Session = Depends(get_db)):
    """All contact methods for a company: rollup + every audited value.

    Returns the legacy primary contact, all ContactItem rows (each with its
    exact source URL + page type + statuses), and a coverage summary.
    """
    from app.models.contact_item import ContactItem
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    contact = db.query(Contact).filter(Contact.company_id == company_id).first()
    items = (db.query(ContactItem)
             .filter(ContactItem.company_id == company_id)
             .order_by(ContactItem.contact_type, ContactItem.id).all())
    emails = sorted({i.normalized_value for i in items if i.contact_type == "EMAIL"})
    phones = sorted({i.normalized_value for i in items if i.contact_type == "PHONE"})
    wa = sorted({i.normalized_value for i in items if i.contact_type == "WHATSAPP"})
    if contact:
        if contact.business_email:
            emails = sorted(set(emails) | {contact.business_email.strip().lower()})
        if contact.phone:
            phones = sorted(set(phones) | {contact.phone})
        if contact.whatsapp_number:
            wa = sorted(set(wa) | {contact.whatsapp_number})
    return {
        "company_id": company_id,
        "primary": ({
            "business_email": contact.business_email,
            "alternate_email": contact.alternate_email,
            "phone": contact.phone,
            "whatsapp_number": contact.whatsapp_number,
            "email_source": contact.email_source,
            "email_source_url": contact.email_source_url,
            "verified": contact.verified,
            "consent_status": contact.consent_status,
            "whatsapp_eligible": contact.whatsapp_eligible,
        } if contact else None),
        "items": [{
            "id": i.id, "contact_type": i.contact_type,
            "display_value": i.display_value, "normalized_value": i.normalized_value,
            "source_url": i.source_url, "source_page_type": i.source_page_type,
            "is_primary": i.is_primary, "verification_status": i.verification_status,
            "validity_status": i.validity_status, "merge_status": i.merge_status,
            "extracted_at": i.extracted_at,
        } for i in items],
        "coverage": {
            "emails": emails, "phones": phones, "whatsapp": wa,
            "has_email": bool(emails), "has_phone": bool(phones),
            "has_whatsapp": bool(wa), "contactable": bool(emails or phones or wa),
        },
    }


@router.delete("/{company_id}")
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    db.delete(company)
    db.commit()
    return {"message": "Company deleted", "id": company_id}


@router.delete("/all")
def delete_all_companies(db: Session = Depends(get_db)):
    """Delete all companies (use with caution)."""
    count = db.query(Company).count()
    db.query(Company).delete()
    db.commit()
    return {"message": f"Deleted {count} companies"}


@router.post("/{company_id}/enrich")
def enrich_company(company_id: int, db: Session = Depends(get_db)):
    """Enrich a single company with contact details from its website."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    service = ContactEnrichmentService()
    result = service.enrich_company(company)

    # Update company
    company.enrichment_status = result.status
    company.enrichment_checked_at = datetime.utcnow()
    company.enrichment_source_url = result.source_url
    company.enrichment_confidence = result.confidence
    company.enrichment_method = result.method
    company.enrichment_error = result.error

    if result.emails or result.phones or result.whatsapp:
        # Create or update contact — never silently drop the directory email:
        # the website-domain-matching address becomes primary, the other is
        # kept as alternate_email (see services/contact_validation.py).
        from app.services.contact_validation import pick_best_email
        contact = db.query(Contact).filter(Contact.company_id == company.id).first()
        if not contact:
            contact = Contact(
                company_id=company.id,
                contact_type=ContactType.EMAIL,
            )
            db.add(contact)
            db.flush()

        if result.emails:
            primary, alternate, source = pick_best_email(
                contact.business_email, result.emails[0], company.website)
            contact.business_email = primary
            contact.alternate_email = alternate
            contact.email_source = source
        if result.phones:
            contact.phone = result.phones[0]
        if result.whatsapp:
            contact.whatsapp_number = result.whatsapp[0]
        if result.source_url:
            contact.email_source_url = result.source_url

        # Create or update lead
        lead = db.query(Lead).filter(Lead.company_id == company.id).first()
        if not lead:
            lead = Lead(
                company_id=company.id,
                contact_id=contact.id,
                status=LeadStatus.NEW,
                lead_score=0,
                lead_priority=LeadPriority.LOW,
            )
            db.add(lead)
            db.flush()

        score_result = score_lead(company, contact)
        lead.lead_score = score_result.score
        lead.lead_priority = LeadPriority(score_result.priority)
        lead.status = LeadStatus.SCORED
        lead.ai_reason = "\n".join(score_result.reasons)

        # Add activity
        activity = Activity(
            lead_id=lead.id,
            activity_type="ENRICHMENT_COMPLETE",
            description=f"Contact found: {len(result.emails)} emails, {len(result.phones)} phones",
        )
        db.add(activity)
    else:
        # Add activity for no contact found
        activity = Activity(
            lead_id=company.leads[0].id if company.leads else None,
            activity_type="ENRICHMENT_NO_CONTACT",
            description=f"No public contact found: {result.error or 'None found'}",
        )
        if company.leads:
            db.add(activity)

    db.commit()
    return result.to_dict()


@router.post("/enrich-bulk")
def enrich_companies_bulk(
    company_ids: list[int] = None,
    unresolved_only: bool = True,
    db: Session = Depends(get_db),
):
    """Bulk enrich companies. If unresolved_only, only enrich PENDING/FAILED companies."""
    query = db.query(Company)
    if company_ids:
        query = query.filter(Company.id.in_(company_ids))
    if unresolved_only:
        query = query.filter(Company.enrichment_status.in_([
            EnrichmentStatus.PENDING, EnrichmentStatus.FAILED, EnrichmentStatus.NO_PUBLIC_CONTACT
        ]))

    companies = query.limit(50).all()  # Safe concurrency limit

    results = []
    service = ContactEnrichmentService()

    for company in companies:
        result = service.enrich_company(company)

        company.enrichment_status = result.status
        company.enrichment_checked_at = datetime.utcnow()
        company.enrichment_source_url = result.source_url
        company.enrichment_confidence = result.confidence
        company.enrichment_method = result.method
        company.enrichment_error = result.error

        if result.emails or result.phones or result.whatsapp:
            from app.services.contact_validation import pick_best_email as _pick_best
            contact = db.query(Contact).filter(Contact.company_id == company.id).first()
            if not contact:
                contact = Contact(company_id=company.id, contact_type=ContactType.EMAIL)
                db.add(contact)
                db.flush()

            if result.emails:
                primary, alternate, source = _pick_best(
                    contact.business_email, result.emails[0], company.website)
                contact.business_email = primary
                contact.alternate_email = alternate
                contact.email_source = source
            if result.phones:
                contact.phone = result.phones[0]
            if result.whatsapp:
                contact.whatsapp_number = result.whatsapp[0]
            if result.source_url:
                contact.email_source_url = result.source_url

            lead = db.query(Lead).filter(Lead.company_id == company.id).first()
            if not lead:
                lead = Lead(
                    company_id=company.id,
                    contact_id=contact.id,
                    status=LeadStatus.NEW,
                    lead_score=0,
                    lead_priority=LeadPriority.LOW,
                )
                db.add(lead)
                db.flush()

            score_result = score_lead(company, contact)
            lead.lead_score = score_result.score
            lead.lead_priority = LeadPriority(score_result.priority)
            lead.status = LeadStatus.SCORED
            lead.ai_reason = "\n".join(score_result.reasons)

        results.append({"company_id": company.id, "status": result.status.value})

    db.commit()
    return {"message": f"Enriched {len(results)} companies", "results": results}


@router.post("/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    create_new: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Import companies from CSV file. Match to existing companies or create new ones."""
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    csv_content = content.decode('utf-8')

    # Parse CSV
    csv_companies = CSVImportService.parse_csv(csv_content)

    if not csv_companies:
        raise HTTPException(status_code=400, detail="No valid companies found in CSV")

    # Get existing companies for matching
    existing_companies = db.query(Company).all()

    # Match companies
    matches, unmatched = CSVImportService.match_companies(csv_companies, existing_companies)

    created = 0
    updated = 0
    flagged = 0

    for match in matches:
        if match["match_type"] == "ambiguous":
            flagged += 1
            continue

        company = match["db_company"]
        csv_data = match["csv_data"]

        if csv_data.get("website"):
            # Validate URL
            service = ContactEnrichmentService()
            validation_error = service._validate_url(csv_data["website"])
            if not validation_error:
                company.website = csv_data["website"]
                company.enrichment_status = EnrichmentStatus.PENDING
                updated += 1

    # Create new companies if requested and no match found
    if create_new:
        for csv_company in unmatched:
            if not csv_company.get("website"):
                continue

            service = ContactEnrichmentService()
            validation_error = service._validate_url(csv_company["website"])
            if validation_error:
                continue

            new_company = Company(
                source_id=1,  # Default source
                company_name=csv_company["company_name"],
                website=csv_company["website"],
                enrichment_status=EnrichmentStatus.PENDING,
            )
            db.add(new_company)
            created += 1

    db.commit()

    return {
        "message": f"CSV import complete: {created} created, {updated} updated, {flagged} flagged for review",
        "total_processed": len(csv_companies),
        "created": created,
        "updated": updated,
        "flagged": flagged,
        "unmatched": len(unmatched),
    }
