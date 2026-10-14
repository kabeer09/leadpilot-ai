"""Per-value contact storage (multi-contact model).

Every discovered email/phone/WhatsApp is stored as its own ContactItem row
with the exact source URL + page type. Idempotent: re-saves of the same
(company, type, normalized value) are skipped, never duplicated.
The legacy single-row Contact stays the primary-contact rollup.
"""
import logging
from app.models.contact_item import ContactItem
from app.services.dedup import normalize_email, normalize_phone

logger = logging.getLogger(__name__)

PAGE_DIRECTORY = "directory"
PAGE_PROFILE = "exhibitor-profile"
PAGE_WEBSITE = "website"


def _page_type(source_url: str | None, default: str) -> str:
    url = (source_url or "").lower()
    if any(k in url for k in ("/contact", "contact-us", "contactus", "kontakt")):
        return "contact"
    if any(k in url for k in ("/about", "/about-us", "company", "/who-we-are")):
        return "about"
    if any(k in url for k in ("/product", "/collection", "/catalog", "/shop")):
        return "products"
    if any(k in url for k in ("wholesale", "distribut", "trade", "b2b", "import", "export")):
        return "wholesale"
    return default


def store_contact_items(db, company, emails=None, phones=None, whatsapp=None,
                        source_url: str | None = None,
                        default_page: str = PAGE_WEBSITE) -> int:
    """Store each discovered value as a ContactItem (idempotent). Returns new rows."""
    created = 0

    def _add(ctype: str, raw: str | None, page: str):
        nonlocal created
        if not raw or not str(raw).strip():
            return
        display = str(raw).strip()
        norm = (normalize_email(display) if ctype == "EMAIL"
                else normalize_phone(display))
        if not norm:
            return
        exists = db.query(ContactItem).filter(
            ContactItem.company_id == company.id,
            ContactItem.contact_type == ctype,
            ContactItem.normalized_value == norm).first()
        if exists:
            return
        first_of_type = db.query(ContactItem).filter(
            ContactItem.company_id == company.id,
            ContactItem.contact_type == ctype).count() == 0
        db.add(ContactItem(
            company_id=company.id,
            contact_type=ctype,
            normalized_value=norm,
            display_value=display[:500],
            source_url=(source_url or "")[:2048] or None,
            source_page_type=page,
            is_public_business=True,
            is_primary=first_of_type,
        ))
        created += 1

    for e in emails or []:
        _add("EMAIL", e, _page_type(source_url, default_page))
    for p in phones or []:
        _add("PHONE", p, _page_type(source_url, default_page))
    for w in whatsapp or []:
        _add("WHATSAPP", w, _page_type(source_url, default_page))
    if created:
        try:
            db.flush()
        except Exception as e:
            db.rollback()
            logger.warning(f"ContactItem store failed for company {company.id}: {e}")
            return 0
    return created
