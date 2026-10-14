"""Multi-stage exhibitor crawler.

Stage 1: Crawl listing pages, discover exhibitor profile URLs
Stage 2: Visit each profile, extract company name / description / website / products
Stage 3: Visit each company website, find public contact page, extract emails / phones / WhatsApp
"""
import re
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


def is_cangift_listing_url(url: str) -> bool:
    """Detect CanGift exhibiting-companies directory URLs."""
    try:
        from app.services.cangift import is_cangift_listing_url as _detect
        return _detect(url)
    except Exception:
        return False


def is_lasvegas_listing_url(url: str) -> bool:
    """Detect Las Vegas Market exhibitor directory URLs."""
    try:
        from app.services.lasvegas import is_lasvegas_listing_url as _detect
        return _detect(url)
    except Exception:
        return False

# Exhibitor profile URL patterns (relative to domain)
EXHIBITOR_PROFILE_PATTERNS = [
    r"/exhibitors?/\d+",
    r"/exhibitors?/[^/]+$",
    r"/exhibitor-detail/",
    r"/brands?/",
    r"/participants?/",
    r"/compan(y|ies)/",
    r"/vendors?/",
    r"/showrooms?/",
]

# Path segments that indicate a listing/category/resource page, NOT an exhibitor profile
NON_PROFILE_SEGMENTS = {
    "categories", "category", "directory", "search", "listing", "list",
    "show-specials", "first-finds", "resources", "registration",
    "exhibitor-directory", "exhibitor-search", "new-exhibitors",
    "buyers", "buyer", "attend", "plan", "register", "login",
}

# Social / non-business domains to ignore when picking an official website
SOCIAL_DOMAINS = [
    "facebook", "twitter", "x.com", "linkedin", "instagram",
    "youtube", "pinterest", "tiktok", "snapchat", "whatsapp",
    "tumblr", "reddit", "flickr", "vimeo", "weibo", "vk.com",
]

# Email domains that are never business contacts
JUNK_EMAIL_DOMAINS = [
    "example.com", "sentry.wixpress.com", "wixpress.com", "sentry.io",
    "google.com", "facebook.com", "instagram.com", "twitter.com",
    "linkedin.com", "youtube.com", "pinterest.com", "tiktok.com",
    "snapchat.com", "whatsapp.com", "telegram.org", "discord.com",
    "reddit.com", "tumblr.com", "medium.com", "wordpress.com",
    "squarespace.com", "shopify.com", "bigcommerce.com", "wix.com",
    "godaddy.com", "cloudflare.com", "akamai.com", "amazonaws.com",
    "azure.com", "microsoft.com", "apple.com", "adobe.com",
    "salesforce.com", "mailchimp.com", "constantcontact.com",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}")
WHATSAPP_RE = re.compile(r"(?:whatsapp\.com/send\?phone=|wa\.me/)(\d+)")
PAGE_PARAM_RE = re.compile(r"([?&](pageindex|pagenumber|page|p|pg)=)(\d+)", re.IGNORECASE)


def _expand_page_sequences(urls: list[str], cap: int = 200) -> list[str]:
    """Expand windowed pagination bars into full page sequences.

    Listing pages often show only [1][2][3]…[176]. When a discovered link
    reveals the last page number (?pageindex=176), synthesize the whole
    1..N sequence (capped) so coverage doesn't stop at the visible window.
    """
    out = list(urls)
    seen = set(urls)
    best: dict[str, int] = {}
    for url in urls:
        m = PAGE_PARAM_RE.search(url)
        if not m:
            continue
        num = int(m.group(3))
        key = url[:m.start()] + "|PARAM|" + url[m.end():]
        if key not in best or num > best[key]:
            best[key] = num
    for key, last in best.items():
        template = next(u for u in urls if u.startswith(key.split("|PARAM|")[0])
                        and u.endswith(key.split("|PARAM|")[1]))
        for n in range(1, min(last, cap) + 1):
            canon = re.sub(PAGE_PARAM_RE,
                           lambda mm: mm.group(1) + str(n), template, count=1)
            if canon not in seen:
                seen.add(canon)
                out.append(canon)
    return out


def is_ambiente_search_url(url: str) -> bool:
    """Detect Messe Frankfurt exhibitor-search directory URLs."""
    try:
        host = (urlparse(url).netloc or "").lower()
        path = (urlparse(url).path or "").lower()
        return "messefrankfurt.com" in host and "exhibitor-search" in path
    except Exception:
        return False


class CrawlerStats:
    """Crawl statistics across all three stages."""

    def __init__(self):
        self.listing_pages_processed = 0
        self.exhibitor_profile_urls_found = 0
        self.exhibitor_profiles_processed = 0
        self.companies_extracted = 0
        self.websites_found = 0
        self.company_websites_crawled = 0
        self.contact_pages_found = 0
        self.emails_found = 0
        self.phones_found = 0
        self.whatsapp_found = 0
        self.errors = 0
        self.error_details: list[str] = []

    def to_dict(self):
        return {
            "listing_pages_processed": self.listing_pages_processed,
            "exhibitor_profile_urls_found": self.exhibitor_profile_urls_found,
            "exhibitor_profiles_processed": self.exhibitor_profiles_processed,
            "companies_extracted": self.companies_extracted,
            "websites_found": self.websites_found,
            "company_websites_crawled": self.company_websites_crawled,
            "contact_pages_found": self.contact_pages_found,
            "emails_found": self.emails_found,
            "phones_found": self.phones_found,
            "whatsapp_found": self.whatsapp_found,
            "errors": self.errors,
            "error_details": self.error_details,
        }


class ExhibitorCrawler:
    """Multi-stage crawler for exhibitor directories."""

    def __init__(
        self,
        start_url: str,
        max_pages: int = 200,
        max_depth: int = 3,
        request_delay: float = 1.0,
        timeout: int = 30000,
        max_profiles: int | None = None,
        skip_website_crawl: bool = False,
        progress_cb=None,
        profile_offset: int = 0,
        workers: int = 3,
    ):
        self.start_url = start_url
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.request_delay = request_delay
        self.delay = request_delay  # alias
        self.timeout = timeout
        self.max_profiles = max_profiles
        self.skip_website_crawl = skip_website_crawl
        self.profile_offset = max(0, profile_offset or 0)
        self.workers = max(1, workers or 1)
        # progress_cb(event, data): "company" after Stage 2 extraction,
        # "enriched" after Stage 3 website crawl. Lets callers (run_full_crawl)
        # persist rows incrementally so the dashboard fills during the crawl
        # instead of only at the very end.
        self.progress_cb = progress_cb
        self.stats = CrawlerStats()
        # Guards shared mutable state across worker threads (stats counters,
        # result lists). DB writes are serialized by the caller's callback.
        self._lock = threading.Lock()
        self.visited_urls: set[str] = set()
        # normalized profile URL -> anchor text from the listing page
        self.exhibitor_profile_urls: dict[str, str] = {}
        self.domain = urlparse(start_url).netloc
        self._exhibitor_data: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_exhibitor_data(self) -> list[dict]:
        """Return the exhibitor records extracted across all stages."""
        return self._exhibitor_data

    def crawl(self) -> CrawlerStats:
        """Run the full multi-stage crawl."""
        # Messe Frankfurt directories expose a public JSON search API used by
        # the site itself — use it for stages 1+2 (fast, structured, complete).
        if is_ambiente_search_url(self.start_url):
            return self._crawl_ambiente()
        # CanGift directories render via a Unity Events JSON API — same deal.
        if is_cangift_listing_url(self.start_url):
            return self._crawl_cangift()
        # Las Vegas Market: ANDMORE A-Z JSON API enumerates all exhibitors.
        if is_lasvegas_listing_url(self.start_url):
            return self._crawl_lasvegas()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)

            try:
                # Stage 1: Crawl listing pages, extract exhibitor profile URLs
                logger.info("Stage 1: Crawling exhibitor listing pages...")
                self._crawl_listing_pages(context)
                logger.info(
                    f"Stage 1 done: {len(self.exhibitor_profile_urls)} profile URLs found"
                )

                # Stage 2: Visit each exhibitor profile, extract company info
                # (parallel workers; each launches its own browser)
                logger.info("Stage 2: Processing exhibitor profiles...")
                exhibitor_data = self._process_exhibitor_profiles()
                self._exhibitor_data = exhibitor_data
                logger.info(f"Stage 2 done: {len(exhibitor_data)} companies extracted")
                self.drop_shared_website_domains(exhibitor_data)

                # Stage 3: Enrich with website contact details
                if self.skip_website_crawl:
                    logger.info("Stage 3 skipped (skip_website_crawl=True)")
                else:
                    logger.info("Stage 3: Crawling company websites for contacts...")
                    self._crawl_company_websites(context, exhibitor_data)
                    logger.info("Stage 3 done")

            finally:
                browser.close()

        return self.stats

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    def _is_same_domain(self, url: str) -> bool:
        return urlparse(url).netloc == self.domain

    def _should_exclude(self, url: str) -> bool:
        url_lower = url.lower()
        skip_patterns = [
            "/login", "/register", "/admin", "/api/", "/cart", "/checkout",
            "/privacy", "/terms", "/cookie", "/search", "/about", "/contact",
            "/news", "/blog", "/event", "/venue", "/travel", "/accommodation",
            "/imprint", "/javascript", "/css", "/wp-content", "/wp-includes",
            "/wp-admin", "/feed", "/rss", "/sitemap", "/robots", "/favicon",
            "/assets/", "/images/", "/img/", "/css/", "/js/", "/fonts/",
            "/media/", "/download", "/upload", "/file", "/pdf", "/doc", "/zip",
            "/identity/", "/support.", "/help", "/faq", "/careers",
        ]
        return any(pattern in url_lower for pattern in skip_patterns)

    def _is_exhibitor_profile_url(self, url: str) -> bool:
        """Check if URL matches exhibitor profile patterns."""
        url_lower = url.lower()
        parsed = urlparse(url)
        segments = [s for s in parsed.path.lower().split("/") if s]

        # Exclude listing / category / resource pages
        if any(seg in NON_PROFILE_SEGMENTS for seg in segments):
            return False

        # A profile URL must have a path segment after the keyword
        # (bare '/exhibitor', '/company' etc. are listing pages)
        if len(segments) < 2:
            return False

        # Single-letter trailing segments are A-Z index tabs, not profiles
        if len(segments[-1]) <= 1:
            return False

        for pattern in EXHIBITOR_PROFILE_PATTERNS:
            if re.search(pattern, url_lower):
                return True

        # Path-segment check (singular + plural, e.g. /company/abc, /brands/xyz)
        if any(seg in segments for seg in
               ["exhibitor", "exhibitors", "brand", "brands", "participant",
                "participants", "company", "companies", "vendor", "vendors",
                "showroom", "showrooms"]):
            return True

        return False

    def _slice_profiles(self, items: list):
        """Apply offset + max_profiles window (chunked crawling support).

        Chunk 1: offset=0, max=100 → items[0:100].
        Chunk 2: offset=100, max=100 → items[100:200]. Deterministic as
        long as the listing order is stable.
        """
        start = self.profile_offset
        if self.max_profiles is not None:
            window = items[start:start + self.max_profiles]
        else:
            window = items[start:]
        if not window and items:
            msg = (f"Profile window empty: offset {start} is beyond "
                   f"{len(items)} discovered URLs — lower the start offset.")
            logger.warning(msg)
            self.stats.errors += 1
            self.stats.error_details.append(msg)
        return window

    def _normalize_url(self, url: str) -> str:
        # Keep the query string (letter tabs like ?azletter=A are distinct
        # pages) but drop fragments and trailing slashes.
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            normalized += f"?{parsed.query}"
        return normalized.lower()

    def _is_social_media(self, url: str) -> bool:
        url_lower = url.lower()
        return any(domain in url_lower for domain in SOCIAL_DOMAINS)

    def _is_crawlable_website(self, url: str) -> bool:
        """Validate a company website URL is safe to crawl."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            if not parsed.netloc:
                return False
            host = (parsed.hostname or "").lower()
            if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                return False
            # Never re-crawl the directory domain or its subdomains
            base_domain = self.domain.lower().lstrip(".")
            if host == base_domain or host.endswith("." + base_domain):
                return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Progress callback
    # ------------------------------------------------------------------

    def _emit(self, event: str, data: dict):
        """Notify the progress callback (never lets callback errors kill the crawl)."""
        if self.progress_cb is None:
            return
        try:
            self.progress_cb(event, data)
        except Exception as e:
            logger.warning(f"Progress callback failed ({event}): {e}")

    @staticmethod
    def drop_shared_website_domains(exhibitor_data: list[dict], threshold: int = 8) -> int:
        """Null websites claimed by >=threshold different companies.

        A real company website belongs to one exhibitor. When many profiles
        point at the same domain it is a venue/organizer/travel page
        (e.g. thenec.co.uk) — crawling it wastes Stage 3 and pollutes data.
        Returns the number of records cleaned.
        """
        counts: dict[str, int] = {}
        for entry in exhibitor_data:
            website = entry.get("website")
            if not website:
                continue
            host = (urlparse(website).hostname or "").lower()
            if host:
                counts[host] = counts.get(host, 0) + 1
        shared = {h for h, c in counts.items() if c >= threshold}
        cleaned = 0
        for entry in exhibitor_data:
            website = entry.get("website")
            if website and (urlparse(website).hostname or "").lower() in shared:
                logger.info(f"Dropping shared website domain {website} "
                            f"for {entry.get('company_name')}")
                entry["website"] = None
                cleaned += 1
        return cleaned

    # ------------------------------------------------------------------
    # Messe Frankfurt (Ambiente) JSON API path
    # ------------------------------------------------------------------

    def _crawl_ambiente(self) -> CrawlerStats:
        """Stages 1+2 via the directory's public search API, then Stage 3."""
        from app.services.ambiente import fetch_all_exhibitors

        logger.info("Ambiente: fetching exhibitor records via directory search API...")
        exhibitor_data, api_stats = fetch_all_exhibitors(
            self.start_url,
            request_delay=self.request_delay,
        )
        logger.info(f"Ambiente: {len(exhibitor_data)} records from "
                    f"{api_stats['api_pages']} API pages")
        return self._finish_api_records(exhibitor_data, api_stats, "Ambiente")

    def _crawl_cangift(self) -> CrawlerStats:
        """Stages 1+2 via the CanGift widget JSON API, then Stage 3."""
        from app.services.cangift import fetch_all_companies

        logger.info("CanGift: fetching exhibitor records via directory JSON API...")
        exhibitor_data, api_stats = fetch_all_companies(self.start_url)
        logger.info(f"CanGift: {len(exhibitor_data)} records")
        return self._finish_api_records(exhibitor_data, api_stats, "CanGift")

    def _crawl_lasvegas(self) -> CrawlerStats:
        """Stages 1+2 via the ANDMORE A-Z JSON API, then Stage 3."""
        from app.services.lasvegas import fetch_all_exhibitors

        logger.info("Las Vegas: enumerating exhibitors via A-Z JSON API...")
        exhibitor_data, api_stats = fetch_all_exhibitors(
            self.start_url, request_delay=self.request_delay)
        logger.info(f"Las Vegas: {len(exhibitor_data)} records")
        return self._finish_api_records(exhibitor_data, api_stats, "LasVegas")

    def _finish_api_records(self, exhibitor_data: list[dict], api_stats: dict,
                            label: str) -> CrawlerStats:
        """Shared tail for JSON-API directory paths: stats + emit + Stage 3."""
        if self.max_profiles is not None:
            exhibitor_data = exhibitor_data[: self.max_profiles]

        exhibitor_data = self._slice_profiles(exhibitor_data)

        self.stats.listing_pages_processed = api_stats.get("api_pages", 0)
        self.stats.exhibitor_profile_urls_found = len(exhibitor_data)
        self.stats.exhibitor_profiles_processed = len(exhibitor_data)
        self.stats.companies_extracted = len(exhibitor_data)
        self.stats.errors += api_stats.get("errors", 0)
        self._exhibitor_data = exhibitor_data
        self.drop_shared_website_domains(exhibitor_data)
        for record in exhibitor_data:
            self._emit("company", record)

        # Stage 3: enrich via company websites (shared implementation).
        # Skipped for very large directories — use POST /companies/enrich-bulk
        # afterwards instead (it updates rows in place).
        if self.skip_website_crawl:
            logger.info("Stage 3 skipped (skip_website_crawl=True) — "
                        "use /companies/enrich-bulk for website enrichment")
            return self.stats

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)
            try:
                logger.info("Stage 3: Crawling company websites for contacts...")
                self._crawl_company_websites(context, exhibitor_data)
                logger.info("Stage 3 done")
            finally:
                browser.close()

        return self.stats

    # ------------------------------------------------------------------
    # Stage 1: listing pages
    # ------------------------------------------------------------------

    def _extract_links(self, page: Page) -> list[tuple[str, str]]:
        """Extract same-domain links with their anchor text."""
        links: list[tuple[str, str]] = []
        try:
            elements = page.query_selector_all("a[href]")
            for el in elements:
                href = el.get_attribute("href")
                if not href:
                    continue
                absolute_url = urljoin(self.start_url, href)
                if not self._is_same_domain(absolute_url):
                    continue
                if self._should_exclude(absolute_url):
                    continue
                try:
                    text = el.inner_text().strip()
                except Exception:
                    text = ""
                links.append((absolute_url, text))
        except Exception as e:
            logger.warning(f"Error extracting links: {e}")
        return links

    def _scroll_page(self, page: Page):
        try:
            page.evaluate("""
                async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 800;
                        const timer = setInterval(() => {
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if (totalHeight >= document.body.scrollHeight) {
                                clearInterval(timer);
                                resolve();
                            }
                        }, 150);
                    });
                }
            """)
        except Exception:
            pass

    def _find_pagination(self, page: Page) -> list[str]:
        """Find pagination links on the page.

        Strict same-listing rule: a pagination link must share the current
        page's PATH with a different query string (?page=2, ?pageindex=5,
        ?letter=B …). This stops the crawler wandering off into site nav
        that merely matches loose class selectors. /list/page/2 style
        continuations under the same section also pass.
        """
        pagination_urls: list[str] = []
        try:
            current_path = urlparse(page.url).path.lower().rstrip("/") or "/"

            def _is_continuation(abs_url: str) -> bool:
                try:
                    parsed = urlparse(abs_url)
                    if parsed.netloc.lower() != urlparse(self.start_url).netloc.lower():
                        return False
                    p = parsed.path.lower().rstrip("/") or "/"
                    if p == current_path and parsed.query:
                        return True
                    if p.startswith(current_path.rstrip("/") + "/"):
                        tail = p[len(current_path.rstrip("/")) + 1:]
                        if re.fullmatch(r"(page|p|pg|seite)/\d+", tail):
                            return True
                    return False
                except Exception:
                    return False

            selectors = [
                ".pagination a", ".pager a", "a[rel='next']",
                "a:has-text('Next')", "a:has-text('»')",
                "[class*='pagination'] a", "[class*='page'] a",
                "a[href*='letter']", "a[href*='page=']", "a[href*='start=']",
                "a[href*='azletter']", "a[href*='pageno']", "a[href*='pageNumber']",
                "a[href*='pageindex=']", "nav a[href*='exhibitors?']",
            ]
            for sel in selectors:
                try:
                    elements = page.query_selector_all(sel)
                except Exception:
                    continue
                for el in elements:
                    try:
                        href = el.get_attribute("href")
                    except Exception:
                        continue
                    if not href:
                        continue
                    absolute_url = urljoin(self.start_url, href)
                    if self._is_same_domain(absolute_url) \
                            and not self._should_exclude(absolute_url) \
                            and _is_continuation(absolute_url):
                        pagination_urls.append(absolute_url)
        except Exception:
            pass
        return list(dict.fromkeys(pagination_urls))

    def _load_listing_page(self, page: Page, url: str) -> bool:
        """Load a listing page and wait until exhibitor links render.

        Returns False when the page never yields profile links (bot wall,
        slow JS, consent overlay) so the caller can retry once.
        """
        try:
            page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
        except PlaywrightTimeout:
            logger.warning(f"Listing page goto timeout: {url}")
        except Exception as e:
            logger.warning(f"Listing page goto failed ({url}): {e}")
            return False

        # Wait for JS-rendered exhibitor links (not a fixed sleep — the
        # listing may take several seconds to hydrate).
        try:
            page.wait_for_selector(
                "a[href*='/exhibitor/'], a[href*='/brand/'], a[href*='/company/'], "
                "a[href*='/participant/']",
                timeout=20000,
            )
        except Exception:
            pass

        page.wait_for_timeout(3000)
        # Scroll until the link count stabilizes (lazy/infinite lists),
        # bounded so a huge directory can't stall Stage 1 here.
        last_count = -1
        stable_rounds = 0
        for _ in range(5):
            self._scroll_page(page)
            page.wait_for_timeout(2000)
            try:
                count = page.evaluate(
                    "document.querySelectorAll(\"a[href*='/exhibitor/'],"
                    "a[href*='/brand/'],a[href*='/company/'],"
                    "a[href*='/participant/']\").length")
            except Exception:
                break
            if count == last_count:
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
            last_count = count
        return True

    def _window_full(self) -> bool:
        """True when discovery already covers the requested profile window."""
        if self.max_profiles is None:
            return False
        return len(self.exhibitor_profile_urls) >= self.profile_offset + self.max_profiles

    def _crawl_listing_pages(self, context):
        """Stage 1: Crawl listing pages and extract exhibitor profile URLs."""
        page = context.new_page()
        try:
            self._load_listing_page(page, self.start_url)
            self.stats.listing_pages_processed += 1
            n_links, _ = self._collect_profile_links(page)

            # Empty render (bot flake / slow hydration): reload + retry once.
            # A rendered page always has dozens of same-domain links.
            if n_links < 10 and not self.exhibitor_profile_urls:
                logger.warning(
                    f"Stage 1: only {n_links} links rendered — reloading once")
                page.wait_for_timeout(5000)
                self._load_listing_page(page, self.start_url)
                self._collect_profile_links(page)

            # Flaky hydration guard: one more pass when still nothing found
            if not self.exhibitor_profile_urls:
                logger.warning("Stage 1: no profile links on first load — retrying once")
                page.wait_for_timeout(3000)
                self._load_listing_page(page, self.start_url)
                self._collect_profile_links(page)

            # Handle pagination (bounded by max_pages). Windowed bars
            # ([1][2][3]…[176]) are expanded to full sequences first.
            pagination_urls = _expand_page_sequences(
                self._find_pagination(page), cap=self.max_pages)
            for purl in pagination_urls:
                if len(self.visited_urls) >= self.max_pages:
                    break
                # Bounded runs stop discovering once the window is full —
                # no point crawling 176 pages for a 6-profile test.
                if self._window_full():
                    logger.info(f"Stage 1: window full "
                                f"({len(self.exhibitor_profile_urls)} URLs) — stopping discovery")
                    break
                pnormalized = self._normalize_url(purl)
                if pnormalized in self.visited_urls:
                    continue
                self.visited_urls.add(pnormalized)
                self._crawl_listing_page(context, purl)

        except PlaywrightTimeout:
            self.stats.errors += 1
            self.stats.error_details.append(f"Timeout: {self.start_url}")
        except Exception as e:
            self.stats.errors += 1
            self.stats.error_details.append(f"{type(e).__name__}: {self.start_url} - {str(e)}")
        finally:
            page.close()

    def _crawl_listing_page(self, context, url: str):
        """Crawl a single listing page."""
        page = context.new_page()
        try:
            self._load_listing_page(page, url)

            self.stats.listing_pages_processed += 1
            self._collect_profile_links(page)

        except PlaywrightTimeout:
            self.stats.errors += 1
            self.stats.error_details.append(f"Timeout: {url}")
        except Exception as e:
            self.stats.errors += 1
            self.stats.error_details.append(f"{type(e).__name__}: {url} - {str(e)}")
        finally:
            page.close()

    def _collect_profile_links(self, page: Page) -> tuple[int, int]:
        """Pull exhibitor profile URLs (with anchor text) from the page.

        Returns (same_domain_links_seen, new_profiles_added) so callers can
        tell an empty/bot-walled render (0 links) from a genuinely
        profile-free page.
        """
        start_normalized = self._normalize_url(self.start_url)
        links = self._extract_links(page)
        added = 0
        for url, text in links:
            if not self._is_exhibitor_profile_url(url):
                continue
            normalized = self._normalize_url(url)
            if normalized == start_normalized:
                continue
            if normalized not in self.exhibitor_profile_urls:
                self.exhibitor_profile_urls[normalized] = text
                added += 1
        self.stats.exhibitor_profile_urls_found = len(self.exhibitor_profile_urls)
        return len(links), added

    # ------------------------------------------------------------------
    # Stage 2: exhibitor profiles
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_shown_by(anchor_text: str) -> tuple[str, str]:
        """Parse 'Brand Name | Shown By Showroom' anchor text."""
        name = anchor_text
        showroom = ""
        for sep in ["Shown By", "shown by", "|", "│", "—"]:
            if sep in name:
                parts = name.split(sep, 1)
                name = parts[0].strip()
                if sep.lower() in ("shown by", "|", "│", "—"):
                    showroom = parts[1].strip()
                break
        # Collapse internal whitespace/newlines and strip leftover
        # separator fragments (e.g. 'Brand\n |' from multi-line anchors)
        name = " ".join(name.split())
        name = re.sub(r"[\s|│—-]+$", "", name).strip()
        showroom = " ".join(showroom.split())
        return name, showroom

    def _bump(self, attr: str, n: int = 1):
        """Thread-safe stats counter increment."""
        with self._lock:
            setattr(self.stats, attr, getattr(self.stats, attr) + n)

    def _note_error(self, msg: str):
        """Thread-safe error recording."""
        with self._lock:
            self.stats.errors += 1
            self.stats.error_details.append(msg)

    @staticmethod
    def _new_stealth_browser(p):
        """Launch a stealth Chromium browser + context (one per worker thread).

        Playwright objects are thread-local, so each worker thread launches
        its own browser instead of sharing one.
        """
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)
        return browser, context

    @staticmethod
    def _chunks(items: list, n: int) -> list[list]:
        """Round-robin split for balanced parallel workers."""
        n = max(1, min(n, len(items))) if items else 1
        return [items[i::n] for i in range(n)]

    def _process_exhibitor_profiles(self) -> list[dict]:
        """Stage 2: Visit each exhibitor profile and extract company info.

        Parallel across worker threads (one browser each); results stream
        back via the progress callback so the dashboard fills immediately.
        """
        exhibitor_data: list[dict] = []
        profile_items = self._slice_profiles(list(self.exhibitor_profile_urls.items()))
        total = len(profile_items)
        if not total:
            return exhibitor_data

        chunks = self._chunks(profile_items, self.workers)
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [pool.submit(self._process_profile_chunk, chunk, total)
                       for chunk in chunks]
            for future in as_completed(futures):
                try:
                    batch = future.result()
                except Exception as e:
                    self._note_error(f"{type(e).__name__} in profile worker: {e}")
                    continue
                with self._lock:
                    exhibitor_data.extend(batch)
        return exhibitor_data

    def _process_profile_chunk(self, chunk: list[tuple[str, str]], total: int) -> list[dict]:
        """Process a slice of profiles on a dedicated browser (one thread)."""
        batch: list[dict] = []
        with sync_playwright() as p:
            browser, context = self._new_stealth_browser(p)
            try:
                for profile_url, anchor_text in chunk:
                    try:
                        record = self._extract_one_profile(context, profile_url, anchor_text)
                    except PlaywrightTimeout:
                        self._note_error(f"Timeout: {profile_url}")
                        continue
                    except Exception as e:
                        self._note_error(f"{type(e).__name__}: {profile_url} - {str(e)}")
                        continue
                    if record is None:
                        continue
                    batch.append(record)
                    self._bump("companies_extracted")
                    self._emit("company", record)
                    done = 0
                    with self._lock:
                        done = self.stats.exhibitor_profiles_processed
                    if done % 25 == 0:
                        logger.info(f"Stage 2 progress: {done}/{total} profiles, "
                                    f"{self.stats.companies_extracted} companies extracted")
                    time.sleep(self.request_delay)
            finally:
                browser.close()
        return batch

    def _extract_one_profile(self, context, profile_url: str, anchor_text: str) -> dict | None:
        """Extract a single exhibitor profile. Returns the record or None."""
        page = context.new_page()
        try:
            page.goto(profile_url, timeout=self.timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            self._bump("exhibitor_profiles_processed")

            # Anchor-text fallback (listing pages embed brand + showroom)
            anchor_name, anchor_showroom = self._parse_shown_by(anchor_text)

            # Extract company name: listing anchor text is the most
            # reliable source (the directory's own A-Z brand name),
            # then profile h1, then the HTML <title> (Hyve directories
            # render empty anchors and a generic h1).
            company_name = self._extract_profile_name(page, profile_url, anchor_name or "")

            # Final validation: a company name must contain
            # at least one alphanumeric character
            if company_name and not re.search(r"[A-Za-z0-9]", company_name):
                company_name = None

            # Extract description
            description = self._extract_description(page)

            # Extract official website URL
            website = self._extract_website_url(page, profile_url)

            # Extract booth/hall
            booth = self._extract_booth(page, company_name or "")
            hall = ""
            for sel in [".hall", "[class*='hall']"]:
                el = page.query_selector(sel)
                if el:
                    hall = el.inner_text().strip()[:100]
                    break
            # Fallback: inline 'Hall: Hall 5 Stand: 5F34' text (Hyve).
            # Also re-parses when the card match returned a raw label
            # blob containing those keywords.
            try:
                _is_blob = bool(booth and re.search(r"hall|stand", booth, re.I))
                _blob = booth if _is_blob else ""
                _body = page.inner_text("body")
                _m = re.search(
                    r"Hall\s*:\s*([A-Za-z0-9 .\-/]+?)\s+Stand\s*:"
                    r"\s*([A-Za-z0-9\-/]+)", _blob + "\n" + _body)
                if _m:
                    if not hall:
                        hall = _m.group(1).strip()[:100]
                    if not booth or _is_blob:
                        booth = _m.group(2).strip()[:100]
                elif not booth:
                    _m2 = re.search(r"Stand\s*:\s*([A-Za-z0-9\-/]+)", _body)
                    if _m2:
                        booth = _m2.group(1).strip()[:100]
            except Exception:
                pass

            # Extract location
            country, city = self._extract_location(page)

            # Extract products
            products = self._extract_products(page, profile_url)

            # Extract showroom from profile page text
            showroom = anchor_showroom
            if not showroom:
                body_text = page.inner_text("body")
                m = re.search(r"shown by\s+(.+)", body_text, re.IGNORECASE)
                if m:
                    showroom = m.group(1).strip()[:200]

            if not company_name:
                return None
            return {
                "company_name": company_name,
                "website": website,
                "description": description,
                "industry": "",
                "country": country,
                "city": city,
                "showroom": showroom,
                "exhibition_name": "",
                "hall": hall,
                "booth": booth,
                "products": products,
                "profile_url": profile_url,
                "emails": [],
                "phones": [],
                "whatsapp": [],
                "contact_page_url": None,
            }
        finally:
            page.close()

    def _extract_website_url(self, page: Page, profile_url: str) -> str | None:
        """Extract the official website URL from a profile page."""
        page_domain = urlparse(profile_url).netloc

        # 1. The exhibitor CTA button (e.g. class 'imc-exhibitors--main-cta-button')
        cta_selectors = [
            "[class*='main-cta'] a[href^='http']",
            "a[class*='main-cta'][href^='http']",
            "[class*='cta-button'] a[href^='http']",
            "[class*='exhibitors--main'] a[href^='http']",
        ]
        for sel in cta_selectors:
            try:
                for el in page.query_selector_all(sel):
                    href = el.get_attribute("href")
                    if href and href.startswith("http") and self._is_valid_website_link(href, page_domain):
                        return href
            except Exception:
                pass

        # 2. Links whose anchor text says 'Visit <domain>'
        try:
            for el in page.query_selector_all("a[href^='http']"):
                href = el.get_attribute("href")
                if not href or not href.startswith("http"):
                    continue
                try:
                    text = el.inner_text().strip().lower()
                except Exception:
                    continue
                if text.startswith("visit ") or "website" in text:
                    if self._is_valid_website_link(href, page_domain):
                        return href
        except Exception:
            pass

        # 3. External links whose anchor text contains the link's own domain
        try:
            for el in page.query_selector_all("a[href^='http']"):
                href = el.get_attribute("href")
                if not href or not href.startswith("http"):
                    continue
                try:
                    text = el.inner_text().strip().lower()
                except Exception:
                    continue
                link_domain = urlparse(href).netloc.lower().replace("www.", "")
                if link_domain and link_domain in text:
                    if self._is_valid_website_link(href, page_domain):
                        return href
        except Exception:
            pass

        # 4. First plausible external link
        try:
            for el in page.query_selector_all("a[href^='http']"):
                href = el.get_attribute("href")
                if href and self._is_valid_website_link(href.strip(), page_domain):
                    return href.strip()
        except Exception:
            pass

        return None

    def _is_valid_website_link(self, href: str, page_domain: str) -> bool:
        """Check an external link is a plausible company website."""
        if self._is_social_media(href):
            return False
        link_domain = urlparse(href).netloc.lower()
        if link_domain == page_domain or link_domain == self.domain:
            return False
        # Exclude subdomains of the page/directory domain
        # (e.g. info.atlantamarket.com is still the directory operator)
        base_page_domain = page_domain.lower().replace("www.", "")
        if link_domain.replace("www.", "").endswith("." + base_page_domain):
            return False
        # Block well-known non-business / directory-operator domains
        blocked = ["google.", "goo.gl", "facebook.", "twitter.", "x.com",
                   "linkedin.", "instagram.", "youtube.", "pinterest.",
                   "tiktok.", "snapchat.", "whatsapp.", "amazon.",
                   "ebay.", "etsy.", "wikipedia.", "github.",
                   "support.andmore.com", "exhibitors.andmore.com",
                   "andmore.com", "americasmart.com", "imcmanager.com",
                   "imc.com", "casualmarketatlanta.com", "atlanta-apparel.com",
                   "lasvegas-apparel.com", "lasvegasmarket.com",
                   "andmorehighpointmarket.com", "atlconventioncenter.com",
                   "highpointmarket.com", "marthastewart.com",
                   "hyve.group", "springfair.com", "autumnfair.com",
                   "asp.events"]
        if any(link_domain.startswith(b) or link_domain.endswith(b) for b in blocked):
            return False
        return True

    @staticmethod
    def _is_junk_heading(text: str) -> bool:
        """Detect footer/nav headings that are not company names."""
        junk = [
            "let's connect", "lets connect", "search", "menu",
            "market plan", "sign in", "register", "contact us",
            "about us", "newsletter", "subscribe", "follow us",
            "connect with us", "our brands", "useful links",
            "exhibitor directory", "exhibitors", "exhibitor",
            "categories", "floor plans",
        ]
        return text.strip().lower() in junk

    @staticmethod
    def _extract_profile_name(page: Page, profile_url: str, anchor_name: str) -> str | None:
        """Best-effort company name: listing anchor → h1 → <title>.

        Directories like Spring Fair (Hyve) render empty anchor text and a
        generic h1 ('Exhibitors'); the HTML <title> ('3D Studio Gifts -
        Spring Fair 2027') is the reliable fallback there.
        """
        if anchor_name and 2 < len(anchor_name) < 100:
            return anchor_name
        # NOTE: h2 is deliberately excluded — directory footers reuse the
        # same h2s ('Venue & Show Times', …) on every profile page.
        for sel in ["h1", ".exhibitor-name", ".company-name",
                      "[itemprop='name']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text and 2 < len(text) < 200 and \
                            not ExhibitorCrawler._is_junk_heading(text):
                        return text
            except Exception:
                pass
        try:
            title = (page.title() or "").strip()
            # Strip site suffixes: '3D Studio Gifts - Spring Fair 2027',
            # 'A & B Home Group at Atlanta Market'
            for sep in [" - ", " – ", " | ", " at "]:
                if sep in title:
                    title = title.split(sep, 1)[0].strip()
                    break
            if title and 2 < len(title) < 200 and \
                    not ExhibitorCrawler._is_junk_heading(title):
                return title
        except Exception:
            pass
        _ = profile_url
        return None

    @staticmethod
    def _extract_description(page: Page) -> str:
        """Extract the company description from a profile page."""
        # Prefer explicit description containers
        for sel in [".description", ".exhibitor-description",
                      "[itemprop='description']", ".about p",
                      ".about-us p", ".overview p", ".company-description"]:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if 20 < len(text) <= 500:
                        return text[:500]
                    if len(text) > 500:
                        return text[:500]
            except Exception:
                pass

        # Fall back to the longest paragraph on the page
        best = ""
        try:
            for el in page.query_selector_all("p"):
                text = el.inner_text().strip()
                if 40 < len(text) <= 500 and len(text) > len(best):
                    # Skip footer/cookie boilerplate
                    lower = text.lower()
                    if any(kw in lower for kw in ["cookie", "privacy policy",
                                                     "terms & conditions",
                                                     "all rights reserved"]):
                        continue
                    best = text
        except Exception:
            pass
        return best[:500]

    # Stand codes look like 3W15, 4G83, 1G01-1J02, 5B14-C15, B1 11-B2
    STAND_CODE_RE = re.compile(r"\b\d[A-Z]{1,2}\d{2,}(?:-\d?[A-Z]?\d+)?")

    @staticmethod
    def _extract_booth(page: Page, company_name: str) -> str:
        """Extract booth number from a profile page."""
        # Explicit selectors first
        for sel in [".booth", ".stand", "[class*='booth']", "[class*='stand']"]:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text:
                        return ExhibitorCrawler._clean_booth_text(text)
            except Exception:
                pass

        # Fall back: exhibitor cards often show 'Company Name\nBooth'
        if company_name:
            try:
                for el in page.query_selector_all("[class*='exhibitor']"):
                    text = el.inner_text().strip()
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    for i, line in enumerate(lines):
                        if company_name.lower() in line.lower() and i + 1 < len(lines):
                            candidate = lines[i + 1]
                            if re.search(r"\d", candidate) and len(candidate) <= 15:
                                return candidate
            except Exception:
                pass
        return ""

    @staticmethod
    def _clean_booth_text(text: str) -> str:
        """Reduce verbose booth strings ('Hall: Halls 2-3 Stand: 3W15') to the code."""
        text = " ".join(text.split())
        if len(text) <= 25:
            return text[:100]
        m = ExhibitorCrawler.STAND_CODE_RE.search(text)
        if m:
            return m.group(0)
        return text[:100]

    @staticmethod
    def _extract_location(page: Page) -> tuple[str, str]:
        """Extract country and city from a profile page."""
        selectors = [
            ".location", ".address", ".country", ".city",
            "[itemprop='address']", ".company-location",
            ".exhibitor-location", ".address-text",
        ]
        country = ""
        city = ""
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if text:
                        parts = [p.strip() for p in text.split(",")]
                        if len(parts) >= 2:
                            city = parts[0]
                            country = parts[-1]
                        else:
                            country = text
                        break
            except Exception:
                pass
        return country, city

    @staticmethod
    def _extract_products(page: Page, profile_url: str) -> list[dict]:
        """Extract product/brand line information from a profile page."""
        products: list[dict] = []
        product_selectors = [
            ".product", ".product-item", ".exhibitor-product",
            ".offering", ".brand-line", "[class*='product']",
        ]
        for sel in product_selectors:
            try:
                elements = page.query_selector_all(sel)
                for el in elements[:20]:
                    text = el.inner_text().strip()
                    if text and len(text) > 3:
                        products.append({
                            "name": text[:200],
                            "category": "",
                            "description": "",
                            "source_url": profile_url,
                        })
                if products:
                    break
            except Exception:
                pass
        return products

    # ------------------------------------------------------------------
    # Stage 3: company websites
    # ------------------------------------------------------------------

    @staticmethod
    def needs_website_crawl(entry: dict) -> bool:
        """Adaptive Stage 3 rule — crawl a website only when it can add data.

        - Fair already gave email AND phone  → skip (contact complete).
        - Fair gave only one of them         → crawl (website may fill the gap).
        - No website / uncrawlable           → skip (nothing to visit).
        - Otherwise                          → crawl.
        """
        website = entry.get("website")
        if not website:
            return False
        has_email = bool(entry.get("emails"))
        has_phone = bool(entry.get("phones"))
        if has_email and has_phone:
            return False
        return True

    def _crawl_company_websites(self, context, exhibitor_data: list[dict]):
        """Stage 3: Visit company websites and extract public contact details.

        Parallel across worker threads (one browser each). The `context`
        argument is kept for API compatibility but no longer used.
        """
        total = len(exhibitor_data)
        if not total:
            return
        chunks = self._chunks(exhibitor_data, self.workers)
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [pool.submit(self._enrich_website_chunk, chunk, total)
                       for chunk in chunks]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    self._note_error(f"{type(e).__name__} in website worker: {e}")
        with self._lock:
            skipped_total = getattr(self, "_skipped_complete", 0)
        if skipped_total:
            logger.info(f"Stage 3: skipped {skipped_total} websites "
                        "(fair data already complete)")

    def _enrich_website_chunk(self, chunk: list[dict], total: int) -> int:
        """Enrich a slice of company websites on a dedicated browser."""
        skipped_complete = 0
        with sync_playwright() as p:
            browser, context = self._new_stealth_browser(p)
            try:
                for entry in chunk:
                    website = entry.get("website")
                    if not website or not self._is_crawlable_website(website):
                        continue
                    if not self.needs_website_crawl(entry):
                        skipped_complete += 1
                        continue

                    self._bump("websites_found")
                    page = context.new_page()
                    try:
                        emails, phones, whatsapp, contact_page_url = (
                            self._extract_contacts_from_website(page, website)
                        )
                        if contact_page_url:
                            self._bump("contact_pages_found")
                        entry["emails"] = emails
                        entry["phones"] = phones
                        entry["whatsapp"] = whatsapp
                        entry["contact_page_url"] = contact_page_url
                        self._bump("emails_found", len(emails))
                        self._bump("phones_found", len(phones))
                        self._bump("whatsapp_found", len(whatsapp))
                        self._bump("company_websites_crawled")
                        self._emit("enriched", entry)

                        with self._lock:
                            done = self.stats.company_websites_crawled
                            found = self.stats.emails_found
                        if done % 25 == 0:
                            logger.info(f"Stage 3 progress: {done}/{total} websites checked, "
                                        f"{found} emails found")

                    except PlaywrightTimeout:
                        self._note_error(f"Timeout: {website}")
                    except Exception as e:
                        self._note_error(f"{type(e).__name__}: {website} - {str(e)}")
                    finally:
                        page.close()

                    time.sleep(self.request_delay)
            finally:
                browser.close()
        with self._lock:
            self._skipped_complete = getattr(self, "_skipped_complete", 0) + skipped_complete
        return skipped_complete

    def _extract_contacts_from_website(self, page: Page, website: str):
        """Crawl a company website homepage + contact pages for public contacts."""
        emails: list[str] = []
        phones: list[str] = []
        whatsapp: list[str] = []
        contact_page_url: str | None = None

        # Candidate pages: homepage first, then obvious contact pages
        candidate_paths = ["/", "/contact", "/contact-us", "/about", "/about-us",
                           "/imprint", "/impressum", "/kontakt"]
        pages_to_visit: list[str] = []
        try:
            response = page.goto(website, timeout=self.timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if response is None or response.status < 400:
                pages_to_visit.append(website)
                # Discover real contact links from the homepage nav
                try:
                    for el in page.query_selector_all("a[href]"):
                        href = el.get_attribute("href")
                        if not href:
                            continue
                        abs_url = urljoin(website, href)
                        if not self._is_crawlable_website(abs_url):
                            continue
                        if urlparse(abs_url).netloc.lower() != urlparse(website).netloc.lower():
                            continue
                        path = urlparse(abs_url).path.lower()
                        if any(seg in path for seg in
                               ["contact", "about", "imprint", "impressum", "kontakt"]):
                            if abs_url not in pages_to_visit:
                                pages_to_visit.append(abs_url)
                except Exception:
                    pass
        except PlaywrightTimeout:
            self._note_error(f"Timeout: {website}")
            return emails, phones, whatsapp, contact_page_url
        except Exception as e:
            self._note_error(f"{type(e).__name__}: {website} - {str(e)}")
            return emails, phones, whatsapp, contact_page_url

        # Visit up to 3 pages (homepage + 2 contact-ish pages) looking for contacts
        for candidate in pages_to_visit[:3]:
            if candidate != website:
                try:
                    resp = page.goto(candidate, timeout=self.timeout, wait_until="domcontentloaded")
                    if resp is not None and resp.status >= 400:
                        continue
                    page.wait_for_timeout(1500)
                except Exception:
                    continue

            try:
                body_text = page.inner_text("body")
            except Exception:
                continue

            from app.services.contact_validation import filter_valid_emails
            page_emails = filter_valid_emails(EMAIL_RE.findall(body_text))
            page_phones = [
                ph for ph in PHONE_RE.findall(body_text)
                if self._is_valid_phone(ph)
            ]

            page_whatsapp: list[str] = []
            try:
                for el in page.query_selector_all("a[href*='whatsapp'], a[href*='wa.me']"):
                    href = el.get_attribute("href")
                    if href:
                        m = WHATSAPP_RE.search(href)
                        if m:
                            page_whatsapp.append(m.group(1))
            except Exception:
                pass

            if page_emails or page_phones or page_whatsapp:
                if not contact_page_url:
                    contact_page_url = candidate
                for e in page_emails:
                    if e not in emails:
                        emails.append(e)
                for ph in page_phones:
                    if ph not in phones:
                        phones.append(ph)
                for w in page_whatsapp:
                    if w not in whatsapp:
                        whatsapp.append(w)
                if len(emails) >= 2 and len(phones) >= 1:
                    break

        return emails[:5], phones[:3], whatsapp[:3], contact_page_url

    @staticmethod
    def _is_valid_phone(phone: str) -> bool:
        """Filter out junk phone matches (years, nav numbers, multi-line)."""
        if "\n" in phone or "\r" in phone:
            return False
        digits = re.sub(r"\D", "", phone)
        # Real phone numbers have 7-15 digits
        if len(digits) < 7 or len(digits) > 15:
            return False
        # Year ranges like 2002-2026 or 1998-2005 are not phones
        if re.fullmatch(r"(19|20)\d{2}\D+(19|20)\d{2}", phone.strip()):
            return False
        return True
