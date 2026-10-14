"""Contact/email validation — answers 'does this email belong to this company?'.

Two sources feed business_email: the fair directory (address.email) and the
company website (contact page). They often disagree. This module:
- checks whether an email's domain matches the company website domain,
- validates that an address is worth storing at all (syntax + junk filter),
- picks the best primary email (website-domain match wins),
- keeps the loser as alternate_email instead of discarding it.
"""
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Free-mailbox providers can never prove company ownership
FREE_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "aol.com", "protonmail.com", "zoho.com",
    "yandex.com", "mail.com", "gmx.com", "rediffmail.com",
}

# Tracker/asset/template domains that are never business contacts
JUNK_EMAIL_DOMAINS = {
    "example.com", "sentry.io", "google.com", "facebook.com", "instagram.com",
    "twitter.com", "linkedin.com", "youtube.com", "pinterest.com", "tiktok.com",
    "whatsapp.com", "wix.com", "squarespace.com", "shopify.com", "godaddy.com",
    "cloudflare.com", "amazonaws.com", "microsoft.com", "apple.com", "adobe.com",
    "sentry.wixpress.com", "wixpress.com", "mailchimp.com", "constantcontact.com",
    "hubspot.com", "sendgrid.net", "mailgun.org", "mysite.com", "wixsite.com",
    "yoursite.com", "yourdomain.com", "test.com", "email.com",
    "andmore.com", "americasmart.com", "imcmanager.com", "imc.com",
    "highpointmarket.org", "atlantamarket.com", "lasvegasmarket.com",
    "maison-objet.com", "ambiente.messefrankfurt.com", "messefrankfurt.com",
    "springfair.com", "cangift.org",
}


def validate_contact_email(email: str | None) -> dict:
    """Evaluate whether an extracted address is worth storing.

    Returns {"valid": bool, "reason": str, "email": cleaned|None}.
    valid=True means: real syntax, not a tracker/template address.
    Ownership (domain match) is a separate check — see check_email_match.
    Free-mailbox addresses are valid contacts, just never 'verified'.
    """
    if not email or not str(email).strip():
        return {"valid": False, "reason": "no_email", "email": None}
    cleaned = str(email).strip().strip("<>\"'.,;:")
    if not EMAIL_RE.match(cleaned):
        return {"valid": False, "reason": "bad_syntax", "email": None}
    domain = cleaned.lower().split("@")[-1]
    if domain in JUNK_EMAIL_DOMAINS:
        return {"valid": False, "reason": "junk_domain", "email": None}
    return {"valid": True,
            "reason": "free_provider" if domain in FREE_PROVIDERS or
            base_domain(domain) in FREE_PROVIDERS else "ok",
            "email": cleaned}


def filter_valid_emails(emails: list) -> list[str]:
    """Keep only validated addresses, de-duplicated, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for e in emails or []:
        res = validate_contact_email(e)
        if res["valid"] and res["email"] and res["email"].lower() not in seen:
            seen.add(res["email"].lower())
            out.append(res["email"])
    return out


def domain_of(value: str | None) -> str:
    """Extract the registrable-ish domain from an email or URL."""
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


def base_domain(host: str) -> str:
    """Reduce to last two labels (co.uk-style TLDs collapse, acceptable)."""
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def sld(host: str) -> str:
    """Second-level label: 'abinayahome' for abinayahome.com/.in.

    Tolerates TLD variants of the same company name (e.g. .com vs .in).
    """
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return parts[0] if parts else ""
    # ccTLD-style suffix (acmold.com.tr) → label before it
    if len(parts[-2]) <= 3:
        return parts[-3]
    return parts[-2]


def check_email_match(email: str | None, website: str | None) -> dict:
    """Check an email against the company website.

    Returns {"match": bool, "reason": str}. Reasons: domain_match,
    domain_mismatch, free_provider, no_website, no_email.
    """
    if not email:
        return {"match": False, "reason": "no_email"}
    email_host = domain_of(email)
    if not email_host:
        return {"match": False, "reason": "no_email"}
    if email_host in FREE_PROVIDERS or base_domain(email_host) in FREE_PROVIDERS:
        return {"match": False, "reason": "free_provider"}
    if not website:
        return {"match": False, "reason": "no_website"}
    site_host = domain_of(website)
    if not site_host:
        return {"match": False, "reason": "no_website"}
    if base_domain(email_host) == base_domain(site_host):
        return {"match": True, "reason": "domain_match"}
    # Same company name, different TLD (.com vs .in) — very likely theirs
    if sld(email_host) and sld(email_host) == sld(site_host):
        return {"match": True, "reason": "domain_match_sld"}
    return {"match": False, "reason": "domain_mismatch"}


def pick_best_email(directory_email: str | None, website_email: str | None,
                    website: str | None) -> tuple[str | None, str | None, str]:
    """Choose (primary, alternate, source) from the two candidates.

    A website-domain-matching email always wins primary; otherwise the
    directory email stays primary and the website one is kept as alternate.
    """
    directory_email = (directory_email or "").strip() or None
    website_email = (website_email or "").strip() or None

    if website_email and check_email_match(website_email, website)["match"]:
        alternate = directory_email if directory_email != website_email else None
        return website_email, alternate, "website"
    if directory_email:
        alternate = website_email if website_email != directory_email else None
        source = "directory"
        # directory email matching the domain is still just 'directory'
        return directory_email, alternate, source
    if website_email:
        return website_email, None, "website"
    return None, None, "directory"
