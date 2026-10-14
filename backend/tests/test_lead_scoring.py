"""Phase 2 — Lead scoring tests."""
import pytest
from app.services.lead_scoring import score_lead, ScoreResult
from app.models.company import Company
from app.models.contact import Contact, ContactType


def test_score_lead_max_score():
    company = Company(
        company_name="Test Company",
        website="https://test.com",
        description="A test company with a long description that provides enough detail.",
        industry="Technology",
        country="USA",
        city="New York",
        products=[],
    )
    # Manually add products for scoring
    from app.models.product import Product
    company.products = [
        Product(name="Product A", category="Software"),
        Product(name="Product B", category="Hardware"),
    ]
    contact = Contact(
        business_email="info@test.com",
        phone="+1234567890",
        contact_type=ContactType.EMAIL,
    )
    result = score_lead(company, contact)
    assert result.score == 100
    assert result.priority == "HIGH"
    assert len(result.reasons) >= 7


def test_score_lead_medium_score():
    company = Company(
        company_name="Test Company",
        website="https://test.com",
        description="A test company.",
        country="USA",
    )
    contact = Contact(
        business_email="info@test.com",
        contact_type=ContactType.EMAIL,
    )
    result = score_lead(company, contact)
    assert 50 <= result.score < 80
    assert result.priority == "MEDIUM"


def test_score_lead_low_score():
    company = Company(
        company_name="Test Company",
    )
    result = score_lead(company, None)
    assert result.score < 50
    assert result.priority == "LOW"


def test_score_lead_no_email():
    company = Company(
        company_name="Test Company",
        website="https://test.com",
        description="A test company with enough description to score points.",
        country="USA",
    )
    from app.models.product import Product
    company.products = [Product(name="Product A", category="Software")]
    contact = Contact(
        phone="+1234567890",
        contact_type=ContactType.PHONE,
    )
    result = score_lead(company, contact)
    # No email = -20 from max
    assert result.score <= 80


def test_score_lead_no_contact():
    company = Company(
        company_name="Test Company",
        website="https://test.com",
        description="A test company with enough description.",
        country="USA",
    )
    from app.models.product import Product
    company.products = [Product(name="Product A", category="Software")]
    result = score_lead(company, None)
    # No contact = no email points, no contact points
    assert result.score <= 70


def test_score_lead_priority_boundaries():
    # Test HIGH boundary (80+)
    company = Company(
        company_name="Test",
        website="https://test.com",
        description="A test company with enough description to score points.",
        country="USA",
    )
    from app.models.product import Product
    company.products = [Product(name="Product A", category="Software")]
    contact = Contact(business_email="info@test.com", contact_type=ContactType.EMAIL)
    result = score_lead(company, contact)
    assert result.priority == "HIGH"
    assert result.score >= 80
