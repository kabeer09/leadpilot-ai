"""Backfill Phase-A quality columns for existing rows (new columns only).

Never touches existing values — only fills the new nullable columns:
normalized identifiers, company_type, completeness. Then flags
cross-source duplicates (review queue, never merges).
"""
import logging
from app.database import SessionLocal
from app.models.company import Company
from app.models.contact import Contact
from app.models.product import Product
from app.services.dedup import (
    normalize_name, normalize_domain, normalize_email, normalize_phone,
    infer_company_type, completeness_score, flag_duplicates,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill")

BATCH = 200


def main():
    db = SessionLocal()
    try:
        ids = [r[0] for r in db.query(Company.id).order_by(Company.id).all()]
        logger.info(f"Backfilling {len(ids)} companies")
        dups = 0
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            for cid in chunk:
                company = db.query(Company).filter(Company.id == cid).first()
                if not company:
                    continue
                if not company.normalized_name:
                    company.normalized_name = normalize_name(company.company_name) or None
                if not company.normalized_domain:
                    company.normalized_domain = normalize_domain(company.website) or None
                if not company.company_type:
                    company.company_type = infer_company_type(
                        company.company_name, company.description)
                contact = db.query(Contact).filter(
                    Contact.company_id == cid).first()
                if contact:
                    if contact.business_email and not contact.normalized_email:
                        contact.normalized_email = normalize_email(
                            contact.business_email) or None
                    if contact.phone and not contact.normalized_phone:
                        contact.normalized_phone = normalize_phone(contact.phone) or None
                else:
                    contact = None
                products = db.query(Product).filter(
                    Product.company_id == cid).all()
                company.completeness = completeness_score(company, contact, products)
                try:
                    dups += flag_duplicates(db, company)
                except Exception as e:
                    logger.warning(f"dup check failed for {cid}: {e}")
            db.commit()
            logger.info(f"progress {min(i + BATCH, len(ids))}/{len(ids)}, "
                        f"dup candidates so far: {dups}")
        logger.info(f"DONE. Duplicate candidates flagged: {dups}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
