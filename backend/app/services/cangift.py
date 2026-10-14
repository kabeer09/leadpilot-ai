"""CanGift (Canadian Gift Association) exhibitor adapter.

The directory's company list is rendered by a Unity Events widget backed
by a public JSON API (the same endpoint the page's own JavaScript calls):
  GetEventExhibitingCompanies2?eventId=<EVENT>&details=true
The event id is discovered from the listing page (never hard-coded).

Each record carries name, booth(s), phone, website, address and category
tags. No emails are published — those come from company websites in
Stage 3 (shared implementation).
"""
import html
import logging
import re
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
EVENT_RE = re.compile(r"GetEventExhibitingCompanies2\?eventId=([A-Za-z0-9]+)")
EVENT_ANY_RE = re.compile(r"eventId=([A-Z0-9]{6,12})")


def is_cangift_listing_url(url: str) -> bool:
    """Detect CanGift exhibiting-companies directory URLs."""
    try:
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        return "cangift.org" in host and "exhibiting-companies" in path
    except Exception:
        return False


def _normalize_website(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower()
    if not host or "." not in host:
        return None
    return raw


def _clean(text: str | None, limit: int = 0) -> str:
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", "", str(text)))
    text = " ".join(text.split()).strip()
    return text[:limit] if limit else text


def parse_company(c: dict, listing_url: str, api_url: str) -> dict | None:
    """Map one API company record to the standard exhibitor_data dict."""
    name = _clean(c.get("CompanyName"), 200)
    if not name or not re.search(r"[A-Za-z0-9]", name):
        return None

    booths = c.get("Booths") or []
    booth = ", ".join(b.get("BoothNumber", "") for b in booths if b.get("BoothNumber"))
    if not booth:
        booth = _clean(c.get("BoothNumber"), 50)

    phone = _clean(c.get("Phone"), 50)
    if phone:
        code = _clean(c.get("CountryPhoneCode"), 6)
        if code and not phone.startswith("+"):
            phone = f"+{code} {phone}"

    city = _clean(c.get("City"), 100)
    country = (_clean(c.get("CountryName")) or _clean(c.get("Country"))).title() or ""
    street = _clean(c.get("Address1"), 200)
    zipc = _clean(c.get("Address2") or c.get("Postal"), 30)
    province = _clean(c.get("ProvinceName") or c.get("Province"), 100)
    address = ", ".join(p for p in [street, f"{zipc} {city}".strip(), province, country] if p)

    tags = c.get("InterestTags") or []
    industry = ", ".join(_clean(t.get("Text")) for t in tags
                         if isinstance(t, dict) and t.get("Text"))[:255]

    products = []
    for p in (c.get("Products") or []):
        pname = _clean(p.get("name") or p.get("Name") if isinstance(p, dict) else p)
        if pname:
            products.append({"name": pname[:200], "category": "",
                             "description": "", "source_url": listing_url})

    # Bonus: some records embed an email in free-text fields
    emails = []
    for field in (c.get("Description"), c.get("AdditionalInfo"), c.get("Slogan")):
        if field:
            for e in EMAIL_RE.findall(str(field)):
                if e not in emails:
                    emails.append(e)
    emails = emails[:3]

    return {
        "company_name": name,
        "website": _normalize_website(c.get("Website")),
        "description": _clean(c.get("Description"), 2000) or _clean(c.get("Slogan"), 500),
        "industry": industry,
        "country": country,
        "city": city,
        "address": address,
        "exhibition_name": "CanGift Toronto Gift + Home Market",
        "hall": "",
        "booth": booth,
        "products": products,
        "profile_url": listing_url,
        "api_url": api_url,
        "emails": emails,
        "phones": [phone] if phone else [],
        "whatsapp": [],
        "contact_page_url": None,
    }


def _discover_api_url(page) -> str | None:
    """Find the exhibitor JSON API URL (with event id) from page content."""
    try:
        html_text = page.content()
    except Exception:
        return None
    m = EVENT_RE.search(html_text) or EVENT_ANY_RE.search(html_text)
    if not m:
        return None
    event_id = m.group(1)
    return ("https://admin.unityeventsolutions.com/api/mobilink/"
            f"GetEventExhibitingCompanies2?eventId={event_id}&details=true")


def fetch_all_companies(listing_url: str, request_delay: float = 1.0,
                        timeout: int = 45000) -> tuple[list[dict], dict]:
    """Fetch every exhibitor record via the directory JSON API.

    Returns (exhibitor_data, stats).
    """
    stats = {"api_pages": 0, "records": 0, "errors": 0, "total": None}
    exhibitor_data: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        try:
            page = context.new_page()
            logger.info("CanGift: loading listing page (its widget fires the JSON API)...")
            try:
                page.goto(listing_url, timeout=timeout, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                logger.warning("CanGift listing goto timeout — continuing")

            # The page's own widget fires the exhibitor JSON API. Capture that
            # exact response instead of reverse-engineering keys/headers.
            payload = None
            api_url = listing_url
            try:
                with page.expect_response(
                    "**GetEventExhibitingCompanies2**", timeout=30000
                ) as resp_info:
                    page.wait_for_timeout(2000)
                resp = resp_info.value
                api_url = resp.url
                if resp.status == 200:
                    payload = resp.json()
                else:
                    logger.error(f"CanGift widget API HTTP {resp.status}")
            except Exception as e:
                logger.warning(f"CanGift widget API capture failed: {e}")

            if payload is None:
                # Fallback: discover the API URL from page content and call it
                api_url = _discover_api_url(page) or api_url
                try:
                    resp = context.request.get(
                        api_url,
                        headers={"Accept": "application/json",
                                 "Referer": "https://cangift.org/"},
                        timeout=30000,
                    )
                    if resp.status == 200:
                        payload = resp.json()
                    else:
                        logger.error(f"CanGift API HTTP {resp.status}")
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"CanGift API request failed: {e}")

            if payload is None:
                stats["errors"] += 1
                return exhibitor_data, stats

            companies = payload.get("ExhibitingCompanies") or []
            stats["total"] = len(companies)
            stats["api_pages"] = 1
            logger.info(f"CanGift: {len(companies)} companies in API response")
            for c in companies:
                if not isinstance(c, dict):
                    continue
                parsed = parse_company(c, listing_url, api_url)
                if parsed:
                    exhibitor_data.append(parsed)
            stats["records"] = len(exhibitor_data)
        finally:
            browser.close()

    return exhibitor_data, stats
