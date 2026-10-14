"""Phase 2 — AI validator tests."""
import pytest
from app.services.ai_validator import validate_email, get_fallback_email, ValidationResult


def test_validate_email_valid():
    company_data = {
        "company_name": "Test Company",
        "products": ["Product A", "Product B"],
    }
    result = validate_email(
        subject="Exploring Product A — New Look Impex",
        body="Dear Test Company Team, we are New Look Impex. If relevant to your sourcing or product range, we would be happy to share our catalogue. Would you be open to a short 1-to-1 Google Meet?",
        company_data=company_data,
    )
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_validate_email_missing_subject():
    company_data = {"company_name": "Test Company", "products": ["Product A"]}
    result = validate_email(
        subject=None,
        body="Dear Test Company Team, we are New Look Impex.",
        company_data=company_data,
    )
    assert result.is_valid is False
    assert any("subject" in e.lower() for e in result.errors)


def test_validate_email_missing_body():
    company_data = {"company_name": "Test Company", "products": ["Product A"]}
    result = validate_email(
        subject="Test Subject",
        body=None,
        company_data=company_data,
    )
    assert result.is_valid is False
    assert any("body" in e.lower() for e in result.errors)


def test_validate_email_placeholder_detection():
    company_data = {"company_name": "Test Company", "products": ["Product A"]}
    result = validate_email(
        subject="Test [Company Name]",
        body="Dear Test Company Team, we are New Look Impex.",
        company_data=company_data,
    )
    assert result.is_valid is False
    assert any("placeholder" in e.lower() or "prohibited" in e.lower() for e in result.errors)


def test_validate_email_unsupported_claim():
    company_data = {"company_name": "Test Company", "products": ["Product A"]}
    result = validate_email(
        subject="Test Subject",
        body="Dear Test Company Team, we noticed you need our products. We have been following your company.",
        company_data=company_data,
    )
    assert result.is_valid is False
    assert any("unsupported claim" in e.lower() for e in result.errors)


def test_validate_email_no_cta():
    company_data = {"company_name": "Test Company", "products": ["Product A"]}
    result = validate_email(
        subject="Test Subject",
        body="Dear Test Company Team, we are New Look Impex. We manufacture metal urlis and diyas.",
        company_data=company_data,
    )
    assert result.is_valid is True  # Warnings don't make it invalid
    assert any("call-to-action" in w.lower() for w in result.warnings)


def test_fallback_email_structure():
    company_data = {
        "company_name": "Test Company",
        "products": ["Metal urlis", "Metal diyas"],
    }
    result = get_fallback_email(company_data)
    assert "subject" in result
    assert "body" in result
    assert "Test Company" in result["body"]
    assert "New Look Impex" in result["body"]
    # Fallback email uses seller products from settings, not company products
    assert "metal urlis" in result["body"].lower()


def test_fallback_email_no_products():
    company_data = {"company_name": "Test Company", "products": []}
    result = get_fallback_email(company_data)
    assert "subject" in result
    assert "body" in result
    assert "Test Company" in result["body"]
