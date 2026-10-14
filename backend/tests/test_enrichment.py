"""Tests for the enrichment service."""
import pytest
from app.services.enrichment import ContactEnrichmentService, WebsiteDiscoveryService, CSVImportService, EnrichmentResult
from app.models.company import Company, EnrichmentStatus


class TestContactEnrichmentService:
    """Tests for ContactEnrichmentService."""

    def test_validate_url_valid(self):
        """Test that valid URLs pass validation."""
        service = ContactEnrichmentService()
        assert service._validate_url("https://www.example.com") is None
        assert service._validate_url("http://example.com/contact") is None

    def test_validate_url_invalid_scheme(self):
        """Test that invalid schemes are rejected."""
        service = ContactEnrichmentService()
        assert "scheme" in service._validate_url("ftp://example.com").lower()

    def test_validate_url_localhost(self):
        """Test that localhost URLs are rejected."""
        service = ContactEnrichmentService()
        result = service._validate_url("http://localhost:8080")
        assert result is not None
        assert "localhost" in result.lower()

    def test_validate_url_private_ip(self):
        """Test that private IPs are rejected."""
        service = ContactEnrichmentService()
        result = service._validate_url("http://192.168.1.1")
        assert result is not None
        assert "private" in result.lower()

    def test_validate_url_loopback(self):
        """Test that loopback addresses are rejected."""
        service = ContactEnrichmentService()
        result = service._validate_url("http://127.0.0.1")
        assert result is not None

    def test_validate_url_no_hostname(self):
        """Test that URLs without hostname are rejected."""
        service = ContactEnrichmentService()
        result = service._validate_url("https://")
        assert result is not None

    def test_enrich_company_no_website(self):
        """Test enrichment of company without website."""
        service = ContactEnrichmentService()
        company = Company(company_name="Test Company", website=None)
        result = service.enrich_company(company)
        assert result.status == EnrichmentStatus.PENDING
        assert "No website" in result.error

    def test_enrich_company_invalid_website(self):
        """Test enrichment with invalid website URL."""
        service = ContactEnrichmentService()
        company = Company(company_name="Test Company", website="http://localhost:8080")
        result = service.enrich_company(company)
        assert result.status == EnrichmentStatus.FAILED
        assert result.error is not None


class TestWebsiteDiscoveryService:
    """Tests for WebsiteDiscoveryService."""

    def test_is_external_website_valid(self):
        """Test that external websites are correctly identified."""
        service = WebsiteDiscoveryService()
        assert service._is_external_website("https://www.example.com", "https://ambiente.messefrankfurt.com") is True

    def test_is_external_website_social_media(self):
        """Test that social media links are rejected."""
        service = WebsiteDiscoveryService()
        assert service._is_external_website("https://www.facebook.com/example", "https://ambiente.messefrankfurt.com") is False
        assert service._is_external_website("https://www.linkedin.com/company/example", "https://ambiente.messefrankfurt.com") is False


class TestCSVImportService:
    """Tests for CSVImportService."""

    def test_parse_csv_valid(self):
        """Test parsing valid CSV content."""
        csv_content = """company_name,website
Example Corp,https://example.com
Another Inc,https://another.com
"""
        companies = CSVImportService.parse_csv(csv_content)
        assert len(companies) == 2
        assert companies[0]["company_name"] == "Example Corp"
        assert companies[0]["website"] == "https://example.com"

    def test_parse_csv_invalid_url(self):
        """Test that invalid URLs are flagged."""
        csv_content = """company_name,website
Test Corp,http://localhost:8080
"""
        companies = CSVImportService.parse_csv(csv_content)
        assert len(companies) == 1
        assert companies[0]["error"] is not None

    def test_parse_csv_missing_name(self):
        """Test that rows without company name are skipped."""
        csv_content = """company_name,website
,https://example.com
Valid Corp,https://valid.com
"""
        companies = CSVImportService.parse_csv(csv_content)
        assert len(companies) == 1
        assert companies[0]["company_name"] == "Valid Corp"

    def test_match_companies_exact(self):
        """Test exact company matching."""
        csv_companies = [{"company_name": "Exact Corp", "website": None, "error": None}]
        db_companies = [Company(id=1, company_name="Exact Corp")]
        matches, unmatched = CSVImportService.match_companies(csv_companies, db_companies)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "exact"
        assert matches[0]["confidence"] == 1.0

    def test_match_companies_fuzzy(self):
        """Test fuzzy company matching."""
        csv_companies = [{"company_name": "Exact Corp", "website": None, "error": None}]
        db_companies = [Company(id=1, company_name="Exact Corporation Ltd")]
        matches, unmatched = CSVImportService.match_companies(csv_companies, db_companies)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "fuzzy"

    def test_match_companies_ambiguous(self):
        """Test that ambiguous matches are flagged."""
        csv_companies = [{"company_name": "Corp", "website": None, "error": None}]
        db_companies = [
            Company(id=1, company_name="Corp A"),
            Company(id=2, company_name="Corp B"),
        ]
        matches, unmatched = CSVImportService.match_companies(csv_companies, db_companies)
        assert len(matches) == 1
        assert matches[0]["match_type"] == "ambiguous"

    def test_match_companies_no_match(self):
        """Test that unmatched companies are returned."""
        csv_companies = [{"company_name": "Unknown Corp", "website": None, "error": None}]
        db_companies = [Company(id=1, company_name="Known Corp")]
        matches, unmatched = CSVImportService.match_companies(csv_companies, db_companies)
        assert len(matches) == 0
        assert len(unmatched) == 1
