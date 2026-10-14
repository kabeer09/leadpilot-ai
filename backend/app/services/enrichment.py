"""Multi-source company website discovery and contact enrichment service."""
import re
import time
import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse, urlunparse
from ipaddress import ip_address, IPv4Address, IPv6Address
import socket
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from app.models.company import Company, EnrichmentStatus
from app.config import settings

logger = logging.getLogger(__name__)


# Email domains that are never business contacts (asset hosts, trackers, …)
_JUNK_EMAIL_DOMAINS = {
    "example.com", "sentry.io", "google.com", "facebook.com", "instagram.com",
    "twitter.com", "linkedin.com", "youtube.com", "pinterest.com", "tiktok.com",
    "whatsapp.com", "wix.com", "squarespace.com", "shopify.com", "godaddy.com",
    "cloudflare.com", "amazonaws.com", "microsoft.com", "apple.com", "adobe.com",
}


class EnrichmentResult:
    """Result of enrichment attempt."""
    def __init__(self, status, emails=None, phones=None, whatsapp=None,
                 source_url=None, confidence=0.0, method=None, error=None):
        self.status = status
        self.emails = emails or []
        self.phones = phones or []
        self.whatsapp = whatsapp or []
        self.source_url = source_url
        self.confidence = confidence
        self.method = method
        self.error = error

    def to_dict(self):
        return {
            "status": self.status.value if hasattr(self.status, 'value') else self.status,
            "emails": self.emails,
            "phones": self.phones,
            "whatsapp": self.whatsapp,
            "source_url": self.source_url,
            "confidence": self.confidence,
            "method": self.method,
            "error": self.error,
        }


class WebsiteDiscoveryService:
    """Discovers company websites using public exhibitor profile pages."""

    def __init__(self, crawl_delay=None):
        self.crawl_delay = crawl_delay or getattr(settings, 'CRAWL_DELAY_SECONDS', 2.0)

    def discover_from_profile(self, profile_url, company_name):
        """Discover website URL from exhibitor profile page."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = context.new_page()

                try:
                    page.goto(profile_url, timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)

                    # Look for external website links
                    links = page.query_selector_all("a[href^='http']")
                    for link in links:
                        href = link.get_attribute("href")
                        if href and self._is_external_website(href, profile_url):
                            browser.close()
                            return href

                    # Look for "More from us" or "Our website" sections
                    more_selectors = [
                        "a:has-text('More from')",
                        "a:has-text('Our website')",
                        "a:has-text('Visit website')",
                        "a:has-text('External link')",
                        "[class*='external'] a",
                        "[class*='website'] a",
                    ]
                    for sel in more_selectors:
                        el = page.query_selector(sel)
                        if el:
                            href = el.get_attribute("href")
                            if href and href.startswith("http"):
                                browser.close()
                                return href

                except PlaywrightTimeout:
                    pass
                finally:
                    browser.close()
        except Exception as e:
            logger.warning(f"Profile discovery error: {e}")

        return None

    def _is_external_website(self, url, base_url):
        """Check if URL is an external website (not social media)."""
        skip_domains = [
            "facebook", "linkedin", "instagram", "twitter", "youtube",
            "pinterest", "tiktok", "xing", "whatsapp",
        ]
        url_lower = url.lower()
        return not any(domain in url_lower for domain in skip_domains)


class ContactEnrichmentService:
    """Enriches company data by crawling public websites for contact details."""

    def __init__(self, crawl_delay=None, max_retries=2):
        self.crawl_delay = crawl_delay or getattr(settings, 'CRAWL_DELAY_SECONDS', 2.0)
        self.max_retries = max_retries

    def enrich_company(self, company):
        """Enrich a single company with contact details from its website."""
        if not company.website:
            return EnrichmentResult(
                status=EnrichmentStatus.PENDING,
                error="No website URL available"
            )

        # Validate URL
        validation_error = self._validate_url(company.website)
        if validation_error:
            return EnrichmentResult(
                status=EnrichmentStatus.FAILED,
                error=validation_error
            )

        # Crawl website for contacts
        result = self._crawl_website_for_contacts(company.website, company.company_name)
        return result

    def _validate_url(self, url):
        """Validate URL is safe to crawl."""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or parsed.scheme not in ["http", "https"]:
                return "Invalid URL scheme"
            if not parsed.netloc:
                return "No hostname in URL"

            # Check for localhost
            hostname = parsed.hostname
            if hostname in ["localhost", "127.0.0.1", "0.0.0.0", "::1"]:
                return "Localhost URLs are not allowed"

            # Check for private IPs
            try:
                ip = ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_reserved:
                    return "Private IP addresses are not allowed"
            except ValueError:
                # Not an IP, it's a domain name
                pass

            return None
        except Exception as e:
            return f"URL validation error: {e}"

    def _crawl_website_for_contacts(self, url, company_name):
        """Crawl company website to find contact details."""
        emails = []
        phones = []
        whatsapp_numbers = []
        source_url = None
        method = "website_crawl"

        # Try homepage first, then contact/about pages
        urls_to_try = [
            url,
            urljoin(url, "/contact"),
            urljoin(url, "/about"),
            urljoin(url, "/impressum"),
            urljoin(url, "/imprint"),
            urljoin(url, "/kontakt"),
            urljoin(url, "/about-us"),
            urljoin(url, "/contact-us"),
        ]

        for try_url in urls_to_try:
            result = self._crawl_single_page(try_url, company_name)
            if result["emails"] or result["phones"] or result["whatsapp"]:
                emails.extend(result["emails"])
                phones.extend(result["phones"])
                whatsapp_numbers.extend(result["whatsapp"])
                source_url = try_url
                break

        # Deduplicate
        emails = list(set(emails))[:5]
        phones = list(set(phones))[:3]
        whatsapp_numbers = list(set(whatsapp_numbers))[:3]

        if emails or phones or whatsapp_numbers:
            confidence = min(1.0, len(emails) * 0.3 + len(phones) * 0.2 + len(whatsapp_numbers) * 0.3)
            return EnrichmentResult(
                status=EnrichmentStatus.ENRICHED,
                emails=emails,
                phones=phones,
                whatsapp=whatsapp_numbers,
                source_url=source_url,
                confidence=confidence,
                method=method,
            )
        else:
            return EnrichmentResult(
                status=EnrichmentStatus.NO_PUBLIC_CONTACT,
                source_url=source_url,
                method=method,
            )

    def _crawl_single_page(self, url, company_name):
        """Crawl a single page for contact details."""
        result = {"emails": [], "phones": [], "whatsapp": []}

        for attempt in range(self.max_retries):
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    page = context.new_page()

                    try:
                        response = page.goto(url, timeout=15000, wait_until="domcontentloaded")

                        if response and response.status == 403:
                            browser.close()
                            result["error"] = "ACCESS_RESTRICTED"
                            return result
                        elif response and response.status == 429:
                            browser.close()
                            time.sleep(5 * (attempt + 1))
                            continue
                        elif response and response.status >= 400:
                            browser.close()
                            return result

                        page.wait_for_timeout(2000)

                        # Extract emails (validated: syntax + junk/tracker filter)
                        body_text = page.inner_text("body")
                        from app.services.contact_validation import filter_valid_emails
                        raw_emails = list(set(re.findall(
                            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", body_text
                        )))[:10]
                        result["emails"] = filter_valid_emails(raw_emails)[:5]

                        # Extract phones (require 7-15 digits: drops years,
                        # quantities, ratings and other numeric junk)
                        raw_phones = list(set(re.findall(
                            r"[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}",
                            body_text
                        )))[:10]
                        result["phones"] = [
                            ph for ph in raw_phones
                            if 7 <= len(re.sub(r"\D", "", ph)) <= 15
                            and "\n" not in ph
                            and not re.fullmatch(r"(19|20)\d{2}\D+(19|20)\d{2}",
                                                 ph.strip())
                        ][:3]

                        # Extract WhatsApp
                        whatsapp_links = page.query_selector_all("a[href*='whatsapp'], a[href*='wa.me']")
                        for link in whatsapp_links:
                            href = link.get_attribute("href")
                            if href:
                                match = re.search(r"(?:whatsapp\.com/send\?phone=|wa\.me/)(\d+)", href)
                                if match:
                                    result["whatsapp"].append(match.group(1))

                        browser.close()
                        return result

                    except PlaywrightTimeout:
                        browser.close()
                        time.sleep(self.crawl_delay)
                        continue
                    finally:
                        try:
                            browser.close()
                        except Exception:
                            pass

            except Exception as e:
                logger.warning(f"Crawl error for {url}: {e}")
                time.sleep(self.crawl_delay)
                continue

        return result


class CSVImportService:
    """Imports company data from CSV files."""

    @staticmethod
    def parse_csv(csv_content):
        """Parse CSV content and return list of company data."""
        import csv
        import io

        companies = []
        reader = csv.DictReader(io.StringIO(csv_content))

        for row in reader:
            company_name = row.get("company_name", "").strip()
            website = row.get("website", "").strip() or row.get("url", "").strip()

            if not company_name:
                continue

            # Validate website URL
            if website:
                service = ContactEnrichmentService()
                validation_error = service._validate_url(website)
                if validation_error:
                    companies.append({
                        "company_name": company_name,
                        "website": None,
                        "error": validation_error,
                    })
                    continue

            companies.append({
                "company_name": company_name,
                "website": website if website else None,
                "error": None,
            })

        return companies

    @staticmethod
    def match_companies(csv_companies, db_companies):
        """Match CSV companies to existing database companies."""
        matches = []
        unmatched = []

        for csv_company in csv_companies:
            csv_name = csv_company["company_name"].lower().strip()

            # Try exact match
            exact_matches = [c for c in db_companies if c.company_name.lower().strip() == csv_name]
            if len(exact_matches) == 1:
                matches.append({
                    "csv_data": csv_company,
                    "db_company": exact_matches[0],
                    "confidence": 1.0,
                    "match_type": "exact",
                })
                continue

            # Try fuzzy match using word-based similarity
            fuzzy_matches = []
            csv_words = csv_name.split()
            csv_first = csv_words[0] if csv_words else ""
            for c in db_companies:
                db_name = c.company_name.lower().strip()
                if not db_name:
                    continue
                db_words = db_name.split()
                db_first = db_words[0] if db_words else ""
                # Match if first words are the same and one name's remaining words
                # are a prefix/substring of the other's
                if csv_first == db_first:
                    csv_rest = " ".join(csv_words[1:])
                    db_rest = " ".join(db_words[1:])
                    if not csv_rest or not db_rest:
                        fuzzy_matches.append(c)
                    elif csv_rest in db_rest or db_rest in csv_rest:
                        fuzzy_matches.append(c)

            if len(fuzzy_matches) == 1:
                matches.append({
                    "csv_data": csv_company,
                    "db_company": fuzzy_matches[0],
                    "confidence": 0.8,
                    "match_type": "fuzzy",
                })
                continue

            # Multiple matches or no match
            if len(fuzzy_matches) > 1:
                matches.append({
                    "csv_data": csv_company,
                    "db_company": None,
                    "confidence": 0.0,
                    "match_type": "ambiguous",
                    "candidates": [c.id for c in fuzzy_matches],
                })
            else:
                unmatched.append(csv_company)

        return matches, unmatched
