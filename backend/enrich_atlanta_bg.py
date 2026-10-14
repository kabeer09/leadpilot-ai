"""Parallel website enrichment for saved fair companies (background).

Merges public website emails/phones into saved rows in place.
Idempotent: re-running or overlapping with a crawl's Stage 3
only re-merges the same values (pick_best_email dedupes).

Usage: python enrich_fair_bg.py <source_id> [chunk_index] [num_chunks]
  chunking splits the work round-robin across parallel workers, e.g.:
    worker 1: enrich_fair_bg.py 1613 0 3
    worker 2: enrich_fair_bg.py 1613 1 3
    worker 3: enrich_fair_bg.py 1613 2 3
Each worker re-checks the row right before crawling, so overlaps
(set restarts, sibling workers) only ever skip — never duplicate.
"""
import logging
import sys
import time
from app.database import SessionLocal
from app.models.company import Company
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.activity import Activity
from app.services.enrichment import ContactEnrichmentService
from app.services.contact_validation import pick_best_email
from app.services.lead_scoring import score_lead

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fair-enrich")

SOURCE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 500
CHUNK_INDEX = int(sys.argv[2]) if len(sys.argv) > 2 else 0
NUM_CHUNKS = int(sys.argv[3]) if len(sys.argv) > 3 else 1


def main():
    db = SessionLocal()
    try:
        companies = (
            db.query(Company)
            .filter(Company.source_id == SOURCE_ID, Company.website.isnot(None))
            .order_by(Company.id.asc())
            .all()
        )
        # Only those still missing an email; round-robin chunk for parallelism
        todo = []
        for pos, c in enumerate(companies):
            if pos % NUM_CHUNKS != CHUNK_INDEX:
                continue
            ct = db.query(Contact).filter(Contact.company_id == c.id).first()
            if not ct or not ct.business_email:
                todo.append(c.id)
        logger.info(f"Worker {CHUNK_INDEX}/{NUM_CHUNKS}: enriching {len(todo)} "
                    f"source-{SOURCE_ID} companies")

        service = ContactEnrichmentService()
        done = emails = skipped = 0
        for i, cid in enumerate(todo, start=1):
            company = db.query(Company).filter(Company.id == cid).first()
            if not company:
                continue
            # Re-check: a sibling worker (or earlier pass) may have filled it
            already = db.query(Contact).filter(Contact.company_id == cid).first()
            if already and already.business_email:
                skipped += 1
                continue
            try:
                result = service.enrich_company(company)
                contact = db.query(Contact).filter(Contact.company_id == cid).first()
                if not contact:
                    contact = Contact(company_id=cid, contact_type=ContactType.EMAIL)
                    db.add(contact)
                    db.flush()
                if result.emails:
                    primary, alternate, src = pick_best_email(
                        contact.business_email, result.emails[0], company.website)
                    contact.business_email = primary
                    contact.alternate_email = alternate
                    contact.email_source = src
                    emails += 1
                if result.phones and not contact.phone:
                    contact.phone = result.phones[0]
                if result.whatsapp and not contact.whatsapp_number:
                    contact.whatsapp_number = result.whatsapp[0]
                if result.source_url:
                    contact.email_source_url = result.source_url
                lead = db.query(Lead).filter(Lead.company_id == cid).first()
                if lead:
                    if lead.contact_id is None:
                        lead.contact_id = contact.id
                    sr = score_lead(company, contact)
                    lead.lead_score = sr.score
                    lead.lead_priority = LeadPriority(sr.priority)
                    if lead.status == LeadStatus.NEW:
                        lead.status = LeadStatus.SCORED
                    lead.ai_reason = "\n".join(sr.reasons)
                    db.add(Activity(lead_id=lead.id, activity_type="WEBSITE_ENRICHED",
                                    description=f"Website contacts merged for {company.company_name}"))
                db.commit()
                done += 1
                if i % 10 == 0:
                    logger.info(f"progress {i}/{len(todo)}: {emails} with email")
            except Exception as e:
                db.rollback()
                logger.warning(f"company {cid} failed: {e}")
            time.sleep(1.0)
        logger.info(f"DONE: {done} processed, {emails} with email")
    finally:
        db.close()


if __name__ == "__main__":
    main()
