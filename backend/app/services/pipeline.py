"""End-to-end lead generation pipeline service."""
import re
import logging
from datetime import datetime
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from app.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.company import Company
from app.models.product import Product
from app.models.contact import Contact, ContactType
from app.models.lead import Lead, LeadStatus, LeadPriority
from app.models.activity import Activity
from app.models.outreach import Outreach
from app.services.crawler import ExhibitorCrawler
from app.services.lead_scoring import score_lead
from app.services.ai_generator import generate_email, generate_company_summary
from app.services.ai_validator import validate_email, get_fallback_email

logger = logging.getLogger(__name__)


class LeadPipeline:
    """Orchestrates the full lead generation and enrichment pipeline."""

    def __init__(self):
        self.db = SessionLocal()

    def process_source(self, source_id: int):
        """Process a source through the full pipeline."""
        source = self.db.query(Source).filter(Source.id == source_id).first()
        if not source:
            logger.error(f"Source {source_id} not found")
            return

        logger.info(f"Processing source {source_id}: {source.url}")

        # Stage 1: Crawl
        companies = self._crawl_source(source)

        # Stage 2: Enrich each company
        for company_data in companies:
            self._process_company(company_data, source)

        # Update source status
        source.status = SourceStatus.COMPLETED
        source.last_crawled_at = datetime.utcnow()
        self.db.commit()
        logger.info(f"Pipeline completed for source {source_id}")

    def _crawl_source(self, source: Source) -> list[dict]:
        """Crawl source and extract company data."""
        crawler = ExhibitorCrawler(
            start_url=source.url,
            max_pages=200,
            max_depth=3,
            request_delay=1.0,
        )
        crawler.crawl()
        return crawler.get_exhibitor_data()

    def _process_company(self, data: dict, source: Source):
        """Process a single company through the pipeline."""
        # Check for duplicate
        existing = self.db.query(Company).filter(
            Company.company_name == data["name"],
            Company.source_id == source.id
        ).first()
        if existing:
            return

        # Save company
        company = Company(
            source_id=source.id,
            company_name=data["name"],
            website=data.get("website"),
            description=data.get("description", ""),
            industry=data.get("industry"),
            country=data.get("country"),
            city=data.get("city"),
            exhibition_name=data.get("exhibition_name"),
            source_url=data.get("profile_url", source.url),
            exhibitor_url=data.get("profile_url", source.url),
        )
        self.db.add(company)
        self.db.flush()

        # Save products
        for prod in data.get("products", []):
            product = Product(
                company_id=company.id,
                name=prod["name"],
                category=prod.get("category"),
                description=prod.get("description"),
                source_url=prod.get("source_url"),
            )
            self.db.add(product)

        # Save contact
        emails = data.get("emails", [])
        phones = data.get("phones", [])
        whatsapp = data.get("whatsapp")

        contact = None
        if emails or phones or whatsapp:
            contact = Contact(
                company_id=company.id,
                business_email=emails[0] if emails else None,
                phone=phones[0] if phones else None,
                whatsapp_number=whatsapp[0] if whatsapp else None,
                email_source_url=data.get("contact_page_url", data.get("profile_url", source.url)),
                contact_type=ContactType.EMAIL,
            )
            self.db.add(contact)
            self.db.flush()

        # Create and score lead
        lead = Lead(
            company_id=company.id,
            contact_id=contact.id if contact else None,
            status=LeadStatus.NEW,
            lead_score=0,
            lead_priority=LeadPriority.LOW,
        )
        self.db.add(lead)
        self.db.flush()

        # Score lead
        score_result = score_lead(company, contact)
        lead.lead_score = score_result.score
        lead.lead_priority = LeadPriority(score_result.priority)
        lead.status = LeadStatus.SCORED
        lead.ai_reason = "\n".join(score_result.reasons)

        # Add activity
        activity = Activity(
            lead_id=lead.id,
            activity_type="COMPANY_DISCOVERED",
            description=f"Company discovered from {source.url}",
        )
        self.db.add(activity)

        # Try to generate email if we have a contact
        if contact and contact.business_email:
            self._generate_and_validate_email(lead, company, contact)

        self.db.commit()

    def _generate_and_validate_email(self, lead: Lead, company: Company, contact: Contact):
        """Generate and validate an email for a lead."""
        company_data = {
            "company_name": company.company_name,
            "description": company.description,
            "products": [p.name for p in company.products],
            "industry": company.industry,
            "country": company.country,
        }

        email = generate_email(company_data)
        if email:
            result = validate_email(email["subject"], email["body"], company_data)
            if result.is_valid:
                lead.status = LeadStatus.EMAIL_VALIDATED
                lead.ai_summary = f"Email ready: {email['subject']}"
            else:
                # Use fallback
                fallback = get_fallback_email(company_data)
                lead.status = LeadStatus.EMAIL_VALIDATED
                lead.ai_summary = f"Fallback email: {fallback['subject']}"
        else:
            # Fallback
            fallback = get_fallback_email(company_data)
            lead.status = LeadStatus.EMAIL_VALIDATED
            lead.ai_summary = f"Fallback email: {fallback['subject']}"

        # Add activity
        activity = Activity(
            lead_id=lead.id,
            activity_type="EMAIL_GENERATED",
            description=f"Email generated for {company.company_name}",
        )
        self.db.add(activity)

    def classify_reply(self, lead_id: int, reply_text: str) -> str:
        """Classify a reply and route the lead (AI + rules fallback)."""
        from app.services.reply_processing import route_reply

        lead = self.db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return "UNKNOWN"

        latest = (
            self.db.query(Outreach)
            .filter(Outreach.lead_id == lead_id)
            .order_by(Outreach.created_at.desc())
            .first()
        )
        if not latest:
            return "UNKNOWN"

        return route_reply(self.db, lead, latest, reply_text, None, "(manual)")

    def close(self):
        self.db.close()
