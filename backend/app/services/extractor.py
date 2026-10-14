"""Company data extraction from exhibitor profile pages.

Extracts structured company data (name, website, description, industry,
location, booth, products) from a rendered exhibitor profile page.
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from playwright.sync_api import Page

# Industry classification keywords (checked in priority order)
INDUSTRY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Technology", ["software", "cloud", "saas", "tech", "digital", "it "]),
    ("Manufacturing", ["manufacturer", "manufacturing", "industrial"]),
    ("Food & Beverage", ["food", "beverage", "restaurant", "catering", "organic"]),
    ("Textiles", ["textile", "fabric", "apparel", "clothing", "garment"]),
    ("Furniture", ["furniture", "sofa", "mattress", "home decor"]),
    ("Cosmetics", ["cosmetic", "beauty", "skincare", "fragrance"]),
    ("Toys", ["toy", "toys", "games", "play"]),
    ("Lighting", ["lighting", "lamp", "lamps", "chandelier"]),
    ("Jewelry", ["jewelry", "jewellery", "watch", "gem"]),
]


@dataclass
class ExtractedCompany:
    """Structured exhibitor company data."""
    company_name: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    exhibition_name: Optional[str] = None
    hall: Optional[str] = None
    booth: Optional[str] = None
    products: list = field(default_factory=list)
    source_url: Optional[str] = None
    exhibitor_url: Optional[str] = None


class CompanyExtractor:
    """Extract structured company data from exhibitor profile pages."""

    def __init__(self, timeout: int = 15000):
        self.timeout = timeout

    def _infer_industry(self, text: Optional[str]) -> Optional[str]:
        """Infer industry from a text description."""
        if not text:
            return None
        text_lower = text.lower()
        for industry, keywords in INDUSTRY_KEYWORDS:
            if any(keyword in text_lower for keyword in keywords):
                return industry
        return None

    def extract_from_page(self, page: Page, source_url: str = "") -> ExtractedCompany:
        """Extract company data from a rendered profile page."""
        company = ExtractedCompany(source_url=source_url)

        company.company_name = self._extract_company_name(page)
        company.description = self._extract_description(page)
        company.industry = self._infer_industry(company.description)
        company.website = self._extract_website(page)
        company.country, company.city = self._extract_location(page)
        company.hall = self._extract_field(page, [".hall", "[class*='hall']"])
        company.booth = self._extract_field(page, [".booth", ".stand", "[class*='booth']"])
        company.products = self._extract_products(page)
        return company

    @staticmethod
    def _first_text(page: Page, selectors: list[str], min_len: int = 0, max_len: int = 500):
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el:
                    text = el.inner_text().strip()
                    if min_len <= len(text) <= max_len:
                        return text
            except Exception:
                pass
        return None

    def _extract_company_name(self, page: Page) -> Optional[str]:
        return self._first_text(
            page,
            ["h1", "h1.company-name", "h1.exhibitor-name", ".company-name",
             ".exhibitor-name", "[itemprop='name']"],
            min_len=2, max_len=200,
        )

    def _extract_description(self, page: Page) -> Optional[str]:
        return self._first_text(
            page,
            ["p", ".description", ".about", ".company-description",
             ".exhibitor-description", "[itemprop='description']",
             ".overview", ".about-us"],
            min_len=20, max_len=500,
        )

    def _extract_website(self, page: Page) -> Optional[str]:
        social_domains = ["facebook", "twitter", "linkedin", "instagram",
                          "youtube", "pinterest", "tiktok", "snapchat"]
        try:
            for el in page.query_selector_all("a[href^='http']"):
                href = el.get_attribute("href")
                if not href:
                    continue
                href_lower = href.lower()
                if any(d in href_lower for d in social_domains):
                    continue
                try:
                    text = el.inner_text().strip().lower()
                except Exception:
                    text = ""
                if any(kw in text for kw in ["website", "visit", "www", "official"]):
                    return href
        except Exception:
            pass
        return None

    @staticmethod
    def _extract_location(page: Page) -> tuple[Optional[str], Optional[str]]:
        text = CompanyExtractor._first_text(
            page,
            [".location", ".address", ".country", ".city",
             "[itemprop='address']", ".company-location"],
            min_len=2, max_len=200,
        )
        if not text:
            return None, None
        parts = [p.strip() for p in text.split(",")]
        if len(parts) >= 2:
            return parts[-1], parts[0]
        return text, None

    @staticmethod
    def _extract_field(page: Page, selectors: list[str]) -> Optional[str]:
        return CompanyExtractor._first_text(page, selectors, min_len=1, max_len=100)

    @staticmethod
    def _extract_products(page: Page) -> list[dict]:
        products: list[dict] = []
        for sel in [".product", ".product-item", ".exhibitor-product",
                    ".offering", "[class*='product']"]:
            try:
                elements = page.query_selector_all(sel)
                for el in elements[:20]:
                    text = el.inner_text().strip()
                    if text and len(text) > 3:
                        products.append({"name": text[:200], "category": "",
                                         "description": ""})
                if products:
                    break
            except Exception:
                pass
        return products
