"""Source endpoints with multi-stage crawl orchestration."""
import re
import logging
import threading
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.source import Source, SourceStatus
from app.models.company import Company, EnrichmentStatus
from app.models.product import Product
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.activity import Activity
from app.schemas.source import SourceCreate, SourceResponse
from app.services.crawler import ExhibitorCrawler
from app.services.lead_scoring import score_lead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.post("", response_model=SourceResponse, status_code=201)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    from app.utils.url_safety import validate_public_url
    blocked = validate_public_url(str(payload.url))
    if blocked:
        raise HTTPException(status_code=422, detail=f"URL rejected: {blocked}")
    source = Source(
        name=payload.name,
        url=str(payload.url),
        source_type=payload.source_type,
        status=SourceStatus.PENDING,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("", response_model=list[SourceResponse])
def list_sources(db: Session = Depends(get_db)):
    return db.query(Source).order_by(Source.created_at.desc()).all()


def _job_to_dict(job) -> dict:
    return {
        "id": job.id,
        "source_id": job.source_id,
        "url": job.url,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "pages_visited": job.pages_visited,
        "companies_discovered": job.companies_discovered,
        "records_created": job.records_created,
        "records_updated": job.records_updated if hasattr(job, "records_updated") else 0,
        "duplicates_flagged": job.duplicates_flagged,
        "errors": job.errors or [],
        "created_at": job.created_at,
    }


@router.get("/jobs")
def list_crawl_jobs(status: str | None = None, limit: int = Query(100, ge=1, le=500),
                    db: Session = Depends(get_db)):
    """List crawl jobs, newest first (Crawl Jobs page)."""
    from app.models.crawl_job import CrawlJob
    query = db.query(CrawlJob)
    if status:
        query = query.filter(CrawlJob.status == status.upper())
    return [_job_to_dict(j) for j in query.order_by(CrawlJob.created_at.desc()).limit(limit).all()]


@router.get("/jobs/{job_id}")
def get_crawl_job(job_id: int, db: Session = Depends(get_db)):
    """Crawl job detail: progress, counts, errors."""
    from app.models.crawl_job import CrawlJob
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return _job_to_dict(job)


@router.get("/{source_id}", response_model=SourceResponse)
def get_source(source_id: int, db: Session = Depends(get_db)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("/{source_id}/crawl")
def trigger_crawl(
    source_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    max_profiles: int | None = None,
    skip_website_crawl: bool = False,
    min_quality: float = 0.0,
    profile_offset: int = 0,
):
    """Trigger the full multi-stage crawl pipeline.

    Pass max_profiles to limit Stage 2 (testing); omit for full crawl.
    Pass skip_website_crawl=true for very large directories (website
    enrichment can run afterwards via POST /companies/enrich-bulk).
    Pass min_quality (e.g. 0.2) to save only companies with proper
    details (name + contact/product/website) and skip thin rows.
    Pass profile_offset with max_profiles to crawl in chunks
    (0-100, then 100-200, …). Re-runs never duplicate (idempotent saves).
    Refuses when this source already has a running job (no duplicates).
    """
    if max_profiles is not None and max_profiles < 1:
        raise HTTPException(status_code=422, detail="max_profiles must be >= 1")
    if profile_offset < 0:
        raise HTTPException(status_code=422, detail="profile_offset must be >= 0")
    from app.models.crawl_job import CrawlJob
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    running = db.query(CrawlJob).filter(
        CrawlJob.source_id == source_id,
        CrawlJob.status == "CRAWLING").first()
    if running or source.status == SourceStatus.CRAWLING:
        raise HTTPException(
            status_code=409,
            detail=f"Source {source_id} already has a running crawl "
                   f"(job #{running.id if running else '?'})")

    source.status = SourceStatus.CRAWLING
    job = CrawlJob(source_id=source_id, url=source.url, status="CRAWLING",
                   started_at=datetime.utcnow())
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(
        target=run_full_crawl,
        args=(source_id, source.url, max_profiles, skip_website_crawl, job.id,
              min_quality, profile_offset),
        daemon=True,
    )
    thread.start()

    return {"message": "Crawl started", "source_id": source_id,
            "status": "crawling", "job_id": job.id}


@router.post("/jobs/{job_id}/retry")
def retry_crawl_job(job_id: int, db: Session = Depends(get_db)):
    """Retry a failed (or re-run a completed) crawl job safely.

    Idempotent saves make retries safe: existing rows are skipped, gaps
    are filled, enrichment merges without duplicating.
    """
    from app.models.crawl_job import CrawlJob
    job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    if job.status == "CRAWLING":
        raise HTTPException(status_code=409, detail="Job is still running")
    source = db.query(Source).filter(Source.id == job.source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.status = SourceStatus.CRAWLING
    new_job = CrawlJob(source_id=source.id, url=job.url, status="CRAWLING",
                       started_at=datetime.utcnow())
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    thread = threading.Thread(
        target=run_full_crawl,
        args=(source.id, job.url, None, False, new_job.id),
        daemon=True,
    )
    thread.start()
    return {"message": "Crawl job retried", "job_id": new_job.id,
            "retried_from": job_id}


@router.get("/{source_id}/status")
def crawl_status(source_id: int, db: Session = Depends(get_db)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return {
        "source_id": source.id,
        "status": source.status.value,
        "last_crawled_at": source.last_crawled_at,
    }


def persist_company(db, source, url: str, data: dict, min_quality: float = 0.0):
    """Persist one Stage-2 company row immediately (dashboard fills live).

    Idempotent via (company_name, source_id): returns the existing row on
    re-runs instead of duplicating. Commits per company so a crash or
    restart never loses already-extracted data.
    min_quality: skip rows whose completeness score is below this
    (thin name-only rows). Skipped rows return None and are logged.
    """
    existing = db.query(Company).filter(
        Company.company_name == data["company_name"],
        Company.source_id == source.id
    ).first()
    if existing:
        return existing

    try:
        company = Company(
            source_id=source.id,
            company_name=data["company_name"],
            website=(data.get("website") or "").strip() or None,
            description=data.get("description", ""),
            industry=data.get("industry"),
            country=data.get("country"),
            city=data.get("city"),
            address=data.get("address"),
            exhibition_name=source.name or data.get("exhibition_name"),
            hall=data.get("hall"),
            booth=data.get("booth"),
            source_url=data.get("profile_url", url),
            exhibitor_url=data.get("profile_url", url),
            enrichment_status="PENDING",
        )
        db.add(company)
        db.flush()

        for prod in data.get("products", []):
            db.add(Product(
                company_id=company.id,
                name=prod["name"],
                category=prod.get("category"),
                description=prod.get("description"),
                source_url=prod.get("source_url"),
            ))

        # Directory contact details (fair API/listing), if any.
        # Only validated addresses are stored (syntax + junk filter).
        from app.services.contact_validation import filter_valid_emails
        from app.services.contact_items import store_contact_items
        contact = None
        emails = filter_valid_emails(data.get("emails", []))
        phones = data.get("phones", [])
        whatsapp = data.get("whatsapp", [])
        if emails or phones or whatsapp:
            contact = Contact(
                company_id=company.id,
                business_email=emails[0] if emails else None,
                phone=phones[0] if phones else None,
                whatsapp_number=whatsapp[0] if whatsapp else None,
                email_source_url=data.get("contact_page_url") or data.get("profile_url", url),
                email_source="directory",
                contact_type=ContactType.EMAIL,
            )
            db.add(contact)
            db.flush()
            # Multi-contact audit rows (every value + exact source URL)
            try:
                store_contact_items(
                    db, company, emails=emails, phones=phones, whatsapp=whatsapp,
                    source_url=data.get("contact_page_url") or data.get("profile_url", url),
                    default_page="exhibitor-profile")
            except Exception as e:
                logger.warning(f"ContactItem store failed for {company.company_name}: {e}")
        if not (emails or phones or whatsapp):
            # Preserved, but hidden from default prospecting (recoverable)
            company.lifecycle_status = "EXCLUDED_NO_CONTACT"

        lead = Lead(
            company_id=company.id,
            contact_id=contact.id if contact else None,
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

        db.add(Activity(
            lead_id=lead.id,
            activity_type="COMPANY_DISCOVERED",
            description=f"Company discovered from {url}",
        ))

        # Data-quality fields (§4/§7): normalized identifiers, type,
        # completeness. Non-destructive — computed, never overwrites input.
        from app.services.dedup import (
            normalize_name, normalize_domain, normalize_email,
            normalize_phone, infer_company_type, completeness_score,
            flag_duplicates,
        )
        company.normalized_name = normalize_name(company.company_name) or None
        company.normalized_domain = normalize_domain(company.website) or None
        if not company.company_type:
            company.company_type = infer_company_type(
                company.company_name, company.description)
        if contact:
            contact.normalized_email = normalize_email(contact.business_email) or None
            contact.normalized_phone = normalize_phone(contact.phone) or None
        db.flush()
        products = db.query(Product).filter(Product.company_id == company.id).all()
        company.completeness = completeness_score(company, contact, products)
        if min_quality > 0 and (company.completeness or 0) < min_quality:
            db.rollback()
            logger.info(f"Skipped thin row {data.get('company_name')} "
                        f"(completeness {company.completeness} < {min_quality})")
            return None
        db.commit()
        try:
            flag_duplicates(db, company)
        except Exception as e:
            logger.warning(f"Duplicate flagging failed for {company.company_name}: {e}")
        return company
    except Exception as e:
        db.rollback()
        logger.warning(f"persist_company failed for {data.get('company_name')}: {e}")
        return None


def persist_enrichment(db, source, url: str, data: dict):
    """Merge Stage-3 website contacts into the saved row (keeps both emails).

    The website-domain-matching address becomes primary; the directory one
    is preserved as alternate_email. Commits per company.
    """
    from app.services.contact_validation import pick_best_email

    company = db.query(Company).filter(
        Company.company_name == data["company_name"],
        Company.source_id == source.id
    ).first()
    if not company:
        return persist_company(db, source, url, data)

    try:
        emails = data.get("emails", [])
        phones = data.get("phones", [])
        whatsapp = data.get("whatsapp", [])
        if not (emails or phones or whatsapp):
            return company

        contact = db.query(Contact).filter(Contact.company_id == company.id).first()
        if not contact:
            contact = Contact(company_id=company.id, contact_type=ContactType.EMAIL)
            db.add(contact)
            db.flush()

        from app.services.contact_validation import filter_valid_emails as _fve
        if emails:
            emails = _fve(emails)
        if emails:
            primary, alternate, email_source = pick_best_email(
                contact.business_email, emails[0], company.website)
            contact.business_email = primary
            contact.alternate_email = alternate
            contact.email_source = email_source
        if phones and not contact.phone:
            contact.phone = phones[0]
        if whatsapp and not contact.whatsapp_number:
            contact.whatsapp_number = whatsapp[0]
        if data.get("contact_page_url"):
            contact.email_source_url = data["contact_page_url"]

        lead = db.query(Lead).filter(Lead.company_id == company.id).first()
        if lead:
            if lead.contact_id is None:
                lead.contact_id = contact.id
            score_result = score_lead(company, contact)
            lead.lead_score = score_result.score
            lead.lead_priority = LeadPriority(score_result.priority)
            if lead.status == LeadStatus.NEW:
                lead.status = LeadStatus.SCORED
            lead.ai_reason = "\n".join(score_result.reasons)
            db.add(Activity(
                lead_id=lead.id,
                activity_type="WEBSITE_ENRICHED",
                description=f"Website contacts merged for {company.company_name}",
            ))

        # Multi-contact audit rows for every website value found.
        from app.services.contact_items import store_contact_items
        try:
            store_contact_items(
                db, company, emails=emails, phones=phones, whatsapp=whatsapp,
                source_url=data.get("contact_page_url") or company.website,
                default_page="website")
        except Exception as e:
            logger.warning(f"ContactItem store failed for {company.company_name}: {e}")
        # A company that gained its first usable contact re-enters prospecting.
        if (emails or phones or whatsapp) and company.lifecycle_status == "EXCLUDED_NO_CONTACT":
            company.lifecycle_status = None

        # Refresh normalized identifiers + completeness (merge-only).
        from app.services.dedup import (
            normalize_domain, normalize_email, normalize_phone,
            completeness_score, flag_duplicates,
        )
        if company.website and not company.normalized_domain:
            company.normalized_domain = normalize_domain(company.website) or None
        if emails:
            contact.normalized_email = normalize_email(contact.business_email) or None
        if phones or contact.phone:
            contact.normalized_phone = normalize_phone(contact.phone) or None
        db.flush()
        products = db.query(Product).filter(Product.company_id == company.id).all()
        company.completeness = completeness_score(company, contact, products)
        db.commit()
        try:
            flag_duplicates(db, company)
        except Exception as e:
            logger.warning(f"Duplicate flagging failed for {company.company_name}: {e}")
        return company
    except Exception as e:
        db.rollback()
        logger.warning(f"persist_enrichment failed for {data.get('company_name')}: {e}")
        return company


def run_full_crawl(source_id: int, url: str, max_profiles: int | None = None,
                   skip_website_crawl: bool = False, job_id: int | None = None,
                   min_quality: float = 0.0, profile_offset: int = 0):
    """Run the full multi-stage crawl pipeline in a background thread."""
    from app.database import SessionLocal
    from app.models.crawl_job import CrawlJob
    db = SessionLocal()
    start_time = time.time()

    def _finish_job(status: str, stats=None, saved: int = 0):
        if not job_id:
            return
        try:
            job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
            if not job:
                return
            job.status = status
            job.finished_at = datetime.utcnow()
            if stats is not None:
                d = stats.to_dict() if hasattr(stats, "to_dict") else {}
                job.pages_visited = d.get("listing_pages_processed", 0)
                job.companies_discovered = d.get("companies_extracted", 0)
                job.records_created = saved
                job.errors = (d.get("error_details") or [])[:20]
            db.commit()
        except Exception as e:
            logger.warning(f"Could not finalize crawl job {job_id}: {e}")

    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            _finish_job("FAILED")
            return

        logger.info(f"Starting full crawl for source {source_id}: {url}")

        # Run the multi-stage crawler with incremental persistence:
        # each extracted company is saved immediately ("company" event),
        # website contacts are merged as found ("enriched" event). The
        # dashboard therefore fills DURING the crawl, and a crash/restart
        # never loses already-extracted data (re-runs skip existing rows).
        # Worker threads share this session: DB writes stay serialized
        # behind a lock (network crawling stays parallel).
        write_lock = threading.Lock()

        def _on_progress(event: str, data: dict):
            with write_lock:
                if event == "company":
                    persist_company(db, source, url, data, min_quality=min_quality)
                elif event == "enriched":
                    persist_enrichment(db, source, url, data)

        from app.config import settings as _settings
        crawler = ExhibitorCrawler(
            start_url=url,
            max_pages=200,
            max_depth=3,
            request_delay=1.0,
            timeout=30000,
            max_profiles=max_profiles,
            skip_website_crawl=skip_website_crawl,
            progress_cb=_on_progress,
            profile_offset=profile_offset,
            workers=_settings.CRAWL_WORKERS,
        )
        stats = crawler.crawl()
        logger.info(f"Crawl stats for source {source_id}: {stats.to_dict()}")

        # Final reconcile: persist anything the callbacks missed
        # (both functions are idempotent, so this is always safe).
        saved = 0
        for data in crawler.get_exhibitor_data():
            company = persist_company(db, source, url, data, min_quality=min_quality)
            if company:
                saved += 1
                if data.get("emails") or data.get("phones") or data.get("whatsapp"):
                    persist_enrichment(db, source, url, data)

        total_saved = db.query(Company).filter(
            Company.source_id == source_id).count()
        if saved == 0 and total_saved == 0:
            # Nothing extracted at all: surface FAILED instead of a false
            # COMPLETED so the dashboard shows the error honestly.
            source.status = SourceStatus.FAILED
            db.commit()
            _finish_job("FAILED", stats, saved)
            logger.error(
                f"Crawl for source {source_id} extracted 0 companies "
                f"(errors={stats.errors}). Site may be blocking automated "
                f"access or its structure changed.")
            return

        # Update source status
        source.status = SourceStatus.COMPLETED
        source.last_crawled_at = datetime.utcnow()
        db.commit()
        _finish_job("COMPLETED", stats, saved)
        elapsed = time.time() - start_time
        logger.info(f"Crawl completed for source {source_id} in {elapsed:.1f}s. Companies saved: {saved}")

    except Exception as e:
        logger.error(f"Crawl failed for source {source_id}: {e}")
        source = db.query(Source).filter(Source.id == source_id).first()
        if source:
            source.status = SourceStatus.FAILED
            db.commit()
        _finish_job("FAILED")
    finally:
        db.close()
