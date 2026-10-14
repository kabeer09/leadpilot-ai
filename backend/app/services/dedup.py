"""Deduplication + data-quality service (§7, §4).

- Normalized identifiers: domain, name, email, phone.
- Exact matches across DIFFERENT sources create DuplicateCandidate rows
  (never auto-merge). Fuzzy matches only flag for review.
- Completeness score + company-type inference computed on save.
- Merge rule: fill NULL/empty fields only; never erase known values.
"""
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

COMPANY_TYPES = (
    "manufacturer", "wholesaler", "distributor", "retailer",
    "importer", "exporter", "brand",
)

_TYPE_KEYWORDS = {
    "manufacturer": ["manufacturer", "manufactures", "manufacturing", "factory", "producer", "maker"],
    "wholesaler": ["wholesale", "wholesaler", "bulk supply", "cash & carry", "cash and carry"],
    "distributor": ["distributor", "distribution", "distributes"],
    "retailer": ["retail", "retailer", "shop", "store", "boutique"],
    "importer": ["import", "importer", "imports"],
    "exporter": ["export", "exporter", "exports", "worldwide shipping"],
    "brand": ["brand", "label", "designer", "collection"],
}


def normalize_name(name: str | None) -> str:
    """Lowercase, strip legal suffixes + punctuation for comparison."""
    if not name:
        return ""
    text = name.lower().strip()
    text = re.sub(r"\b(ltd|limited|inc|incorporated|corp|corporation|co|company|gmbh|ag|sa|srl|bv|pty|pvt|llc|s\.a\.s|sas|ab|oy|aps|kg)\b\.?", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_domain(value: str | None) -> str:
    """Registrable-ish domain from a URL or email (lowercased, no www)."""
    if not value:
        return ""
    value = value.strip().lower()
    if "@" in value and "://" not in value:
        host = value.split("@")[-1]
    else:
        if "://" not in value:
            value = "https://" + value
        try:
            host = urlparse(value).hostname or ""
        except Exception:
            return ""
    host = host.strip().lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_email(value: str | None) -> str:
    """Lowercased, trimmed email (drops +tags for comparison)."""
    if not value:
        return ""
    email = value.strip().lower()
    if "@" not in email:
        return ""
    local, _, domain = email.partition("@")
    local = local.split("+")[0]
    return f"{local}@{domain}" if local and domain else ""


def normalize_phone(value: str | None, default_country: str = "") -> str:
    """Digits-only phone with best-effort country prefix.

    Keeps a leading + when present; otherwise prefixes the digits with the
    given default country code digits (e.g. fair-country calling code).
    Never invents a number — empty in, empty out.
    """
    if not value:
        return ""
    text = value.strip()
    has_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    # Drop trunk zero when adding an explicit country code
    if not has_plus and default_country:
        code = re.sub(r"\D", "", default_country)
        if code and not digits.startswith(code):
            digits = digits.lstrip("0")
            digits = code + digits
        return f"+{digits}" if digits else ""
    if has_plus:
        return f"+{digits}" if digits else ""
    return digits


def infer_company_type(name: str | None, description: str | None) -> str:
    """Infer company type from name+description keywords; 'unknown' fallback."""
    text = f"{name or ''} {description or ''}".lower()
    for ctype, keywords in _TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return ctype
    return "unknown"


COMPLETENESS_FIELDS = (
    "description", "industry", "country", "city", "website",
)


def completeness_score(company, contact=None, products: list | None = None) -> float:
    """Fraction (0.0-1.0) of key data points present."""
    points = [
        bool((company.description or "").strip()),
        bool(company.industry),
        bool(company.country),
        bool(company.city),
        bool(company.website),
        bool(contact and contact.business_email),
        bool(contact and contact.phone),
        bool(products),
    ]
    return round(sum(1 for p in points if p) / len(points), 2)


def fill_missing(target, source) -> list[str]:
    """Copy non-empty source attrs onto target only where target is empty.

    Returns the list of field names filled. Never erases known values.
    """
    filled = []
    for field in ("description", "industry", "country", "city", "address",
                  "website", "hall", "booth", "company_type"):
        new_value = getattr(source, field, None)
        old_value = getattr(target, field, None)
        if new_value and not old_value:
            setattr(target, field, new_value)
            filled.append(field)
    return filled


def preview_merge(db, canonical_id: int, duplicate_id: int) -> dict:
    """Dry-run merge report: what WOULD move, nothing written.

    Merge direction: duplicate -> canonical. Outreach/message rows are
    never touched (they hang off leads, which are repointed intact —
    history, statuses and timestamps preserved).
    """
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.contact_item import ContactItem
    from app.models.lead import Lead
    from app.models.outreach import Outreach

    canonical = db.query(Company).filter(Company.id == canonical_id).first()
    duplicate = db.query(Company).filter(Company.id == duplicate_id).first()
    if not canonical or not duplicate:
        return {"ok": False, "error": "company not found"}
    if canonical_id == duplicate_id:
        return {"ok": False, "error": "cannot merge a company into itself"}
    if duplicate.lifecycle_status == "MERGED":
        return {"ok": False, "error": "duplicate is already merged"}

    dup_leads = db.query(Lead).filter(Lead.company_id == duplicate_id).all()
    outreach_ids = []
    for lead in dup_leads:
        outreach_ids += [o.id for o in
                         db.query(Outreach).filter(Outreach.lead_id == lead.id).all()]
    dup_contacts = db.query(Contact).filter(Contact.company_id == duplicate_id).all()
    dup_items = db.query(ContactItem).filter(ContactItem.company_id == duplicate_id).all()
    would_fill = [f for f in ("description", "industry", "country", "city",
                              "address", "website", "hall", "booth", "company_type")
                  if getattr(duplicate, f, None) and not getattr(canonical, f, None)]
    return {
        "ok": True,
        "canonical": {"id": canonical.id, "name": canonical.company_name,
                      "source_id": canonical.source_id},
        "duplicate": {"id": duplicate.id, "name": duplicate.company_name,
                      "source_id": duplicate.source_id,
                      "exhibitor_url": duplicate.exhibitor_url},
        "leads_repointed": len(dup_leads),
        "outreach_preserved": len(outreach_ids),
        "contacts_repointed": len(dup_contacts),
        "items_repointed": len(dup_items),
        "fields_would_fill": would_fill,
        "duplicate_urls_preserved": bool(duplicate.source_url or duplicate.exhibitor_url),
    }


def apply_merge(db, canonical_id: int, duplicate_id: int,
                actor: str = "api", note: str | None = None) -> dict:
    """Merge duplicate -> canonical inside one transaction.

    - Leads/contacts/items repointed (IDs preserved, history intact).
    - Empty canonical fields filled from duplicate (never erased).
    - Duplicate flagged MERGED + merged_into_id (recoverable, inspectable).
    - MergeAudit row written. No email/WhatsApp is ever (re)sent here.
    """
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.contact_item import ContactItem
    from app.models.lead import Lead
    from app.models.suppression import MergeAudit

    preview = preview_merge(db, canonical_id, duplicate_id)
    if not preview.get("ok"):
        return preview
    try:
        canonical = db.query(Company).filter(Company.id == canonical_id).first()
        duplicate = db.query(Company).filter(Company.id == duplicate_id).first()
        filled = fill_missing(canonical, duplicate)
        leads = db.query(Lead).filter(Lead.company_id == duplicate_id).all()
        for lead in leads:
            lead.company_id = canonical_id
        contacts = db.query(Contact).filter(Contact.company_id == duplicate_id).all()
        for contact in contacts:
            contact.company_id = canonical_id
        items = db.query(ContactItem).filter(ContactItem.company_id == duplicate_id).all()
        for item in items:
            item.company_id = canonical_id
            if item.merge_status == "active":
                item.merge_status = "merged"
        # Preserve the duplicate's source URLs on the canonical record's notes
        urls = [u for u in (duplicate.source_url, duplicate.exhibitor_url) if u]
        if urls:
            keep = (canonical.notes or "")
            for u in urls:
                if u not in keep:
                    keep = (keep + f"\nMerged source: {u}").strip()
            canonical.notes = keep or None
        duplicate.lifecycle_status = "MERGED"
        duplicate.merged_into_id = canonical_id
        db.add(MergeAudit(
            canonical_company_id=canonical_id, merged_company_id=duplicate_id,
            match_type="manual", confidence=100,
            leads_repointed=len(leads), contacts_repointed=len(contacts),
            items_repointed=len(items),
            outreach_preserved=preview["outreach_preserved"],
            actor=actor, note=note))
        db.commit()
        logger.info(f"Merged company {duplicate_id} -> {canonical_id} "
                    f"({len(leads)} leads, {preview['outreach_preserved']} outreach kept)")
        return {"ok": True, "merged": duplicate_id, "canonical": canonical_id,
                "leads_repointed": len(leads),
                "contacts_repointed": len(contacts),
                "items_repointed": len(items),
                "outreach_preserved": preview["outreach_preserved"],
                "fields_filled": filled}
    except Exception as e:
        db.rollback()
        logger.error(f"Merge {duplicate_id}->{canonical_id} failed: {e}")
        return {"ok": False, "error": str(e)[:300]}


def flag_duplicates(db, company) -> int:
    """Flag cross-source duplicates of a company (idempotent).

    Exact normalized domain/email/phone/name matches create 'pending'
    DuplicateCandidate rows (unique constraint prevents repeats).
    Returns the number of NEW candidates created.
    """
    from app.models.company import Company
    from app.models.contact import Contact
    from app.models.duplicate_candidate import DuplicateCandidate

    created = 0
    contact = db.query(Contact).filter(Contact.company_id == company.id).first()

    def _add(other_id: int, match_type: str, confidence: float):
        nonlocal created
        if other_id == company.id:
            return
        a, b = sorted((company.id, other_id))
        exists = db.query(DuplicateCandidate).filter(
            DuplicateCandidate.company_a_id == a,
            DuplicateCandidate.company_b_id == b,
            DuplicateCandidate.match_type == match_type).first()
        if exists:
            return
        db.add(DuplicateCandidate(company_a_id=a, company_b_id=b,
                                  match_type=match_type, confidence=confidence,
                                  status="pending"))
        created += 1

    if company.normalized_domain:
        for (oid,) in db.query(Company.id).filter(
                Company.normalized_domain == company.normalized_domain,
                Company.source_id != company.source_id).all():
            _add(oid, "domain", 0.95)
    if contact and contact.normalized_email:
        for (oid,) in db.query(Company.id).join(
                Contact, Contact.company_id == Company.id).filter(
                Contact.normalized_email == contact.normalized_email,
                Company.source_id != company.source_id).all():
            _add(oid, "email", 0.9)
    if contact and contact.normalized_phone:
        for (oid,) in db.query(Company.id).join(
                Contact, Contact.company_id == Company.id).filter(
                Contact.normalized_phone == contact.normalized_phone,
                Company.source_id != company.source_id).all():
            _add(oid, "phone", 0.85)
    if company.normalized_name:
        for oid, oname in db.query(Company.id, Company.company_name).filter(
                Company.normalized_name == company.normalized_name,
                Company.source_id != company.source_id).all():
            _add(oid, "name_exact", 0.8)
    try:
        db.commit()
    except Exception:
        db.rollback()
    return created
