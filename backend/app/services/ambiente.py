"""Ambiente (Messe Frankfurt) exhibitor adapter.

Uses the directory's own public search API (the same endpoint the site's
JavaScript calls) inside an established browser session, then maps each
record to the standard exhibitor_data dict consumed by run_full_crawl.

Stage 1+2 (listing + profiles) come from structured JSON — fast and
complete. Stage 3 (company website contact crawl) is handled by the
generic ExhibitorCrawler website stage.
"""
import html
import logging
import re
import time
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

API_BASE = ("https://api.messefrankfurt.com/service/esb_api/exhibitor-service"
            "/api/2.1/public/exhibitor/search")

# Public client key the Ambiente site itself sends with every search request
# (captured from the page's own JavaScript traffic) + matching headers.
API_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://ambiente.messefrankfurt.com/",
    "apikey": "LXnMWcYQhipLAS7rImEzmZ3CkrU033FMha9cwVSngG4vbufTsAOCQQ==",
}

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _normalize_website(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    host = (urlparse(raw).hostname or "").lower()
    if not host or "." not in host:
        return None
    if host in ("localhost",):
        return None
    return raw


def _valid_email(raw: str | None) -> str | None:
    """Canonical contact-email validation (syntax + junk filter)."""
    from app.services.contact_validation import validate_contact_email
    res = validate_contact_email(raw)
    return res["email"] if res["valid"] else None


def parse_exhibitor(ex: dict, listing_url: str, api_url: str) -> dict | None:
    """Map one API exhibitor record to the standard exhibitor_data dict."""
    name = html.unescape((ex.get("name") or "").strip())
    name = re.sub(r"<[^>]+>", "", name).strip()
    if not name or not re.search(r"[A-Za-z0-9]", name):
        return None

    addr = ex.get("address") or {}
    country = html.unescape((addr.get("country") or {}).get("label", "") or "")
    city = html.unescape(addr.get("city") or "")
    street = html.unescape(addr.get("street") or "")
    zipc = (addr.get("zip") or "").strip()
    address = ", ".join(p for p in [street, f"{zipc} {city}".strip(), country] if p)

    exhibition = ex.get("exhibition") or {}
    halls = exhibition.get("exhibitionHall") or []
    hall = ""
    booth = ""
    if halls:
        hall = halls[0].get("name") or ""
        stands = halls[0].get("stand") or []
        booth = ", ".join(s.get("name", "") for s in stands if s.get("name"))

    desc = ex.get("description") or {}
    description = html.unescape((desc.get("text") or "").strip())[:2000]

    products = []
    prods = (ex.get("products") or {}).get("products") or []
    for p in prods:
        pname = html.unescape((p.get("name") or "").strip())
        if not pname:
            continue
        pdesc = p.get("description") or {}
        ptext = pdesc.get("text") if isinstance(pdesc, dict) else pdesc
        products.append({
            "name": pname[:200],
            "category": "",
            "description": html.unescape((ptext or "")[:500]) if isinstance(ptext, str) else "",
            "source_url": listing_url,
        })

    categories = ex.get("categories") or []
    industry = ", ".join(
        c.get("name", "") for c in categories if isinstance(c, dict) and c.get("name")
    )[:255]

    email = _valid_email(addr.get("email"))
    tel = (addr.get("tel") or "").strip() or None

    return {
        "company_name": name,
        "website": _normalize_website(ex.get("homepage") or ex.get("href")),
        "description": description,
        "industry": industry,
        "country": country,
        "city": city,
        "address": address,
        "exhibition_name": exhibition.get("name") or "Ambiente",
        "hall": hall,
        "booth": booth,
        "products": products,
        "profile_url": listing_url,
        "api_url": api_url,
        "rewrite_id": ex.get("rewriteId"),
        "emails": [email] if email else [],
        "phones": [tel] if tel else [],
        "whatsapp": [],
        "contact_page_url": None,
    }


def fetch_all_exhibitors(listing_url: str, request_delay: float = 1.0,
                         page_size: int = 100,
                         max_pages: int = 200,
                         query: str = "") -> tuple[list[dict], dict]:
    """Fetch every exhibitor record via the directory search API.

    Returns (exhibitor_data, stats). Opens one browser to establish the
    session, then pages the JSON API with the session's cookies.
    """
    stats = {"api_pages": 0, "records": 0, "errors": 0, "total_hits": None}
    exhibitor_data: list[dict] = []

    # pageSize comes from the listing URL when present
    try:
        qs = parse_qs(urlparse(listing_url).query)
        if qs.get("pagesize"):
            page_size = max(1, min(100, int(qs["pagesize"][0])))
    except Exception:
        pass

    def api_url(page_number: int) -> str:
        return (f"{API_BASE}?language=en-GB&q={query}"
                f"&orderBy=name"
                f"&pageNumber={page_number}&pageSize={page_size}"
                f"&orSearchFallback=false&showJumpLabels=true"
                f"&findEventVariable=AMBIENTE")

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
            logger.info("Ambiente: establishing session via listing page...")
            try:
                page.goto(listing_url, timeout=60000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"Ambiente listing goto warning: {str(e)[:120]}")
            page.wait_for_timeout(12000)

            page_number = 1
            while page_number <= max_pages:
                url = api_url(page_number)
                try:
                    resp = context.request.get(
                        url, headers=API_HEADERS,
                        timeout=30000,
                    )
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"Ambiente API page {page_number} request failed: {e}")
                    break

                if resp.status == 401:
                    stats["errors"] += 1
                    logger.error("Ambiente API returned 401 (session rejected)")
                    break
                if resp.status != 200:
                    stats["errors"] += 1
                    logger.warning(f"Ambiente API page {page_number}: HTTP {resp.status}")
                    break

                try:
                    payload = resp.json()
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"Ambiente API page {page_number}: bad JSON ({e})")
                    break

                result = payload.get("result") or {}
                if stats["total_hits"] is None:
                    meta = result.get("metaData") or {}
                    stats["total_hits"] = meta.get("totalHits", meta.get("total"))
                    logger.info(f"Ambiente: totalHits={stats['total_hits']} "
                                f"meta={str(meta)[:200]}")

                hits = result.get("hits") or []
                if not hits:
                    logger.info(f"Ambiente: page {page_number} empty — done")
                    break

                for hit in hits:
                    ex = hit.get("exhibitor") or {}
                    parsed = parse_exhibitor(ex, listing_url, url)
                    if parsed:
                        exhibitor_data.append(parsed)

                stats["api_pages"] += 1
                stats["records"] = len(exhibitor_data)
                logger.info(f"Ambiente: page {page_number} → {len(hits)} hits "
                            f"({len(exhibitor_data)} total)")
                if len(hits) < page_size:
                    break
                page_number += 1
                time.sleep(request_delay)
        finally:
            browser.close()

    return exhibitor_data, stats
