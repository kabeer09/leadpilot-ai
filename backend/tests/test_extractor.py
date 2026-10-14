"""Phase 2 — Extractor tests."""
import pytest
from app.services.extractor import CompanyExtractor, ExtractedCompany


def test_extracted_company_defaults():
    company = ExtractedCompany()
    assert company.company_name is None
    assert company.website is None
    assert company.description is None
    assert company.industry is None
    assert company.country is None
    assert company.city is None
    assert company.address is None
    assert company.exhibition_name is None
    assert company.hall is None
    assert company.booth is None
    assert company.products == []
    assert company.source_url is None
    assert company.exhibitor_url is None


def test_extracted_company_with_data():
    company = ExtractedCompany(
        company_name="Test Company",
        website="https://test.com",
        description="A test company",
        industry="Technology",
        country="USA",
        city="New York",
        products=[{"name": "Product A", "category": "Software"}],
        source_url="https://example.com/exhibitors",
        exhibitor_url="https://example.com/exhibitor/test-company",
    )
    assert company.company_name == "Test Company"
    assert company.website == "https://test.com"
    assert len(company.products) == 1
    assert company.products[0]["name"] == "Product A"


def test_company_extractor_initialization():
    extractor = CompanyExtractor(timeout=15000)
    assert extractor.timeout == 15000


def test_infer_industry_technology():
    extractor = CompanyExtractor()
    result = extractor._infer_industry("We provide software and cloud solutions")
    assert result == "Technology"


def test_infer_industry_manufacturing():
    extractor = CompanyExtractor()
    result = extractor._infer_industry("Leading manufacturer of industrial equipment")
    assert result == "Manufacturing"


def test_infer_industry_none():
    extractor = CompanyExtractor()
    result = extractor._infer_industry(None)
    assert result is None


def test_infer_industry_unknown():
    extractor = CompanyExtractor()
    result = extractor._infer_industry("We do various business activities")
    assert result is None
