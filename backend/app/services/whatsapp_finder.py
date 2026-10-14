"""WhatsApp contact finder — extracts publicly listed WhatsApp business numbers."""
import re
import logging
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

WHATSAPP_LINK_PATTERNS = [
    r"whatsapp\.com/send\?phone=(\d+)",
    r"wa\.me/(\d+)",
    r"api\.whatsapp\.com/send\?phone=(\d+)",
    r"whatsapp\?phone=(\d+)",
]

WHATSAPP_TEXT_PATTERNS = [
    r"(?:whatsapp|wa)[\s:]*([\+]?\d[\d\s\-]{7,})",
    r"whatsapp\s*(?:number|contact|business)?[\s:]*([\+]?\d[\d\s\-]{7,})",
]


class WhatsAppFinder:
    """Finds publicly listed WhatsApp business numbers on exhibitor pages."""

    def __init__(self, timeout: int = 30000):
        self.timeout = timeout

    def find_from_url(self, url: str) -> list[dict]:
        """Find WhatsApp numbers from a single URL."""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = None
            try:
                page = context.new_page()
                page.goto(url, timeout=self.timeout, wait_until="networkidle")
                return self.find_from_page(page, url)
            except PlaywrightTimeout:
                logger.warning(f"Timeout finding WhatsApp on {url}")
                return []
            except Exception as e:
                logger.warning(f"Error finding WhatsApp on {url}: {e}")
                return []
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass
                browser.close()

    def find_from_page(self, page: Page, source_url: str) -> list[dict]:
        """Find WhatsApp numbers from a loaded page."""
        results = []

        try:
            links = page.query_selector_all("a[href*='whatsapp'], a[href*='wa.me']")
            for link in links:
                href = link.get_attribute("href")
                if href:
                    for pattern in WHATSAPP_LINK_PATTERNS:
                        match = re.search(pattern, href, re.IGNORECASE)
                        if match:
                            number = self._normalize_number(match.group(1))
                            if number:
                                results.append({
                                    "whatsapp_number": number,
                                    "whatsapp_source_url": source_url,
                                })
                            break
        except Exception as e:
            logger.warning(f"Error finding WhatsApp links: {e}")

        try:
            body_text = page.inner_text("body")
            for pattern in WHATSAPP_TEXT_PATTERNS:
                matches = re.findall(pattern, body_text, re.IGNORECASE)
                for match in matches:
                    number = self._normalize_number(match)
                    if number:
                        results.append({
                            "whatsapp_number": number,
                            "whatsapp_source_url": source_url,
                        })
        except Exception as e:
            logger.warning(f"Error searching page text for WhatsApp: {e}")

        seen = set()
        unique_results = []
        for r in results:
            if r["whatsapp_number"] not in seen:
                seen.add(r["whatsapp_number"])
                unique_results.append(r)

        return unique_results

    def _normalize_number(self, number: str) -> str | None:
        """Normalize phone number to international format."""
        cleaned = re.sub(r"[^\d+]", "", number)
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        if len(cleaned) < 8 or len(cleaned) > 15:
            return None
        return cleaned
