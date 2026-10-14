"""Las Vegas Market (ANDMORE) exhibitor adapter.

The full directory (2,110 exhibitors) is enumerated through the site's own
public A-Z JSON API (same Sitecore API + public key the page JavaScript
uses), one quick call per letter:
  /imc-api/v2/exhibitors/az?sc_apikey=<KEY>&az=<LETTER>   (header: Channel)
Each entry carries exhibitorId + brand/showroom names; profiles live at
/exhibitor/<id> and company websites yield contacts in Stage 3 (shared).
"""
import logging
import re
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

API_BASE = "https://www.lasvegasmarket.com/imc-api/v2/exhibitors/az"
API_KEY = "391D75C6-01EE-463C-8B51-47B2748F8ACD"
CHANNEL = "las-vegas-market"
LISTING_URL = "https://www.lasvegasmarket.com/exhibitor/exhibitor-directory"


def is_lasvegas_listing_url(url: str) -> bool:
    """Detect Las Vegas Market exhibitor directory URLs."""
    try:
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        return "lasvegasmarket.com" in host and "exhibitor" in path
    except Exception:
        return False


def parse_entry(item: dict, listing_url: str) -> dict | None:
    """Map one A-Z record to the standard exhibitor_data dict."""
    exhibitor_id = str(item.get("exhibitorId") or "").strip()
    name = str(item.get("name") or "").strip()
    if not exhibitor_id or not name or not re.search(r"[A-Za-z0-9]", name):
        return None
    showroom = ""
    if item.get("type") == "line":
        showroom = str(item.get("exhibitorName") or "").strip()
    return {
        "company_name": name[:200],
        "website": None,
        "description": "",
        "industry": "",
        "country": "",
        "city": "",
        "showroom": showroom[:200],
        "exhibition_name": "Las Vegas Market",
        "hall": "",
        "booth": "",
        "products": [],
        "profile_url": f"https://www.lasvegasmarket.com/exhibitor/{exhibitor_id}",
        "emails": [],
        "phones": [],
        "whatsapp": [],
        "contact_page_url": None,
    }


def _letters(context) -> list[str]:
    """A-Z + 0-9 minus the API's own invalid-char list."""
    letters = [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)]
    try:
        resp = context.request.get(
            "https://www.lasvegasmarket.com/imc-api/v2/exhibitors/invalidaz"
            f"?sc_apikey={API_KEY}",
            headers={"Accept": "application/json", "Referer": LISTING_URL,
                     "Channel": CHANNEL},
            timeout=15000,
        )
        if resp.status == 200:
            data = resp.json()
            invalid = set()
            if isinstance(data, list):
                invalid = {str(x) for x in data}
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        invalid.update(str(x) for x in v)
            letters = [ch for ch in letters if ch not in invalid]
    except Exception as e:
        logger.warning(f"LVM invalidaz lookup failed, using full alphabet: {e}")
    return letters


def fetch_all_exhibitors(listing_url: str, request_delay: float = 0.4,
                         timeout: int = 45000) -> tuple[list[dict], dict]:
    """Enumerate every exhibitor via the A-Z JSON API (one call per letter).

    Returns (exhibitor_data, stats).
    """
    stats = {"api_pages": 0, "records": 0, "errors": 0, "total": None}
    exhibitor_data: list[dict] = []
    seen_ids: set[str] = set()

    headers = {"Accept": "application/json", "Referer": LISTING_URL,
               "Channel": CHANNEL}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
            locale="en-US",
        )
        try:
            page = context.new_page()
            try:
                page.goto(LISTING_URL, timeout=timeout, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                logger.warning("LVM listing goto timeout — continuing")
            page.wait_for_timeout(5000)

            letters = _letters(context)
            logger.info(f"LVM: querying {len(letters)} A-Z buckets")
            for letter in letters:
                url = f"{API_BASE}?sc_apikey={API_KEY}&az={letter}"
                try:
                    resp = context.request.get(url, headers=headers, timeout=20000)
                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"LVM az={letter} request failed: {e}")
                    continue
                if resp.status != 200:
                    stats["errors"] += 1
                    logger.warning(f"LVM az={letter}: HTTP {resp.status}")
                    continue
                try:
                    payload = resp.json()
                except Exception:
                    stats["errors"] += 1
                    continue
                items = payload.get("items") or []
                stats["api_pages"] += 1
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    eid = str(item.get("exhibitorId") or "")
                    if not eid or eid in seen_ids:
                        continue
                    seen_ids.add(eid)
                    parsed = parse_entry(item, listing_url)
                    if parsed:
                        exhibitor_data.append(parsed)
                time.sleep(request_delay)
            stats["records"] = len(exhibitor_data)
            stats["total"] = len(seen_ids)
            logger.info(f"LVM: {len(exhibitor_data)} unique exhibitors")
        finally:
            browser.close()

    return exhibitor_data, stats
