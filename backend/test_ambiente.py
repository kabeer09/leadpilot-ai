"""Test extraction from Ambiente exhibitor directory."""
import re
import sys
import io
import json
import time
from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

URL = "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html?page=1&pagesize=30"


def main():
    print("=" * 70)
    print("  LeadPilot AI - Ambiente Exhibitor Extraction Test")
    print(f"  URL: {URL}")
    print("=" * 70)
    print()

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
        page = context.new_page()

        # Stage 1: Load the exhibitor search page
        print("STAGE 1: Loading exhibitor search page...")
        try:
            page.goto(URL, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(3000)
            print(f"  Page title: {page.title()}")
            print(f"  Page URL: {page.url}")
        except Exception as e:
            print(f"  Error loading page: {e}")
            browser.close()
            return

        # Extract all links
        links = page.query_selector_all("a[href]")
        print(f"  Total links found: {len(links)}")

        # Look for exhibitor profile links
        exhibitor_links = []
        for link in links:
            href = link.get_attribute("href")
            text = link.inner_text().strip()
            if href and ("exhibitor" in href.lower() or "aussteller" in href.lower()):
                if href not in exhibitor_links:
                    exhibitor_links.append(href)

        print(f"  Exhibitor-related links: {len(exhibitor_links)}")
        for link in exhibitor_links[:10]:
            print(f"    - {link}")

        # Look for company names in the page
        body_text = page.inner_text("body")
        print(f"  Page text length: {len(body_text)}")

        # Try to find exhibitor cards/entries
        card_selectors = [
            ".exhibitor-item",
            ".exhibitor-card",
            ".search-result-item",
            ".list-item",
            "article",
            "[class*='exhibitor']",
            "[class*='result']",
        ]

        cards = []
        for sel in card_selectors:
            elements = page.query_selector_all(sel)
            if elements:
                print(f"  Found {len(elements)} elements with selector: {sel}")
                cards = elements
                break

        if not cards:
            # Try to find any structured content
            print("  No standard cards found. Looking for alternative structures...")
            all_elements = page.query_selector_all("div, li, article, section")
            print(f"  Total structural elements: {len(all_elements)}")

        # Stage 2: Extract company information
        print()
        print("STAGE 2: Extracting company information...")

        companies = []

        # Try to extract from cards
        for card in cards[:30]:
            try:
                # Try to find name
                name = None
                for name_sel in ["h2", "h3", "h4", ".name", ".title", "a"]:
                    name_el = card.query_selector(name_sel)
                    if name_el:
                        name = name_el.inner_text().strip()
                        if name and len(name) > 2:
                            break

                # Try to find description
                description = ""
                for desc_sel in ["p", ".description", ".desc", ".text"]:
                    desc_el = card.query_selector(desc_sel)
                    if desc_el:
                        description = desc_el.inner_text().strip()
                        if description:
                            break

                # Try to find website
                website = None
                website_el = card.query_selector("a[href^='http']")
                if website_el:
                    website = website_el.get_attribute("href")

                if name:
                    companies.append({
                        "name": name,
                        "description": description,
                        "website": website,
                    })
            except Exception:
                pass

        # If no cards found, try to extract from page text
        if not companies:
            print("  No cards found. Trying text extraction...")
            # Look for company names in the text
            lines = body_text.split("\n")
            for line in lines:
                line = line.strip()
                if line and len(line) > 3 and len(line) < 100:
                    # Skip common non-company lines
                    skip_words = ["search", "filter", "page", "home", "contact", "about", "login", "register"]
                    if not any(word in line.lower() for word in skip_words):
                        companies.append({
                            "name": line,
                            "description": "",
                            "website": None,
                        })

        print(f"  Companies extracted: {len(companies)}")
        for i, company in enumerate(companies[:10], 1):
            print(f"    {i}. {company['name']}")
            if company['description']:
                print(f"       Description: {company['description'][:100]}...")
            if company['website']:
                print(f"       Website: {company['website']}")

        # Stage 3: Visit each company website to find contact details
        print()
        print("STAGE 3: Visiting company websites for contact details...")

        enriched_companies = []
        for company in companies[:10]:  # Limit to first 10 for testing
            website = company.get("website")
            if not website:
                continue

            print(f"  Visiting: {website}")
            try:
                page.goto(website, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                body_text = page.inner_text("body")

                # Extract emails
                emails = list(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", body_text)))[:5]

                # Extract phones
                phones = list(set(re.findall(r"[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}[-\s\.]?[0-9]{1,4}", body_text)))[:3]

                # Look for WhatsApp
                whatsapp_links = page.query_selector_all("a[href*='whatsapp'], a[href*='wa.me']")
                whatsapp_numbers = []
                for link in whatsapp_links:
                    href = link.get_attribute("href")
                    if href:
                        match = re.search(r"(?:whatsapp\.com/send\?phone=|wa\.me/)(\d+)", href)
                        if match:
                            whatsapp_numbers.append(match.group(1))

                company["emails"] = emails
                company["phones"] = phones
                company["whatsapp"] = whatsapp_numbers

                print(f"    Emails: {emails}")
                print(f"    Phones: {phones}")
                print(f"    WhatsApp: {whatsapp_numbers}")

                enriched_companies.append(company)

            except Exception as e:
                print(f"    Error: {e}")

        # Summary
        print()
        print("=" * 70)
        print("  EXTRACTION SUMMARY")
        print("=" * 70)
        print(f"  Total companies found: {len(companies)}")
        print(f"  Companies with contact info: {len(enriched_companies)}")
        print(f"  Companies with emails: {sum(1 for c in enriched_companies if c.get('emails'))}")
        print(f"  Companies with phones: {sum(1 for c in enriched_companies if c.get('phones'))}")
        print(f"  Companies with WhatsApp: {sum(1 for c in enriched_companies if c.get('whatsapp'))}")

        # Save results
        with open("extraction_results.json", "w", encoding="utf-8") as f:
            json.dump({
                "companies": companies,
                "enriched_companies": enriched_companies,
                "stats": {
                    "total_companies": len(companies),
                    "with_contacts": len(enriched_companies),
                    "with_emails": sum(1 for c in enriched_companies if c.get('emails')),
                    "with_phones": sum(1 for c in enriched_companies if c.get('phones')),
                    "with_whatsapp": sum(1 for c in enriched_companies if c.get('whatsapp')),
                }
            }, f, indent=2, ensure_ascii=False)
        print()
        print("  Results saved to extraction_results.json")

        browser.close()


if __name__ == "__main__":
    main()
