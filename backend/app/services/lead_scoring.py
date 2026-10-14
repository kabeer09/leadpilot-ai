"""Deterministic lead scoring — application logic owns the score, not AI."""
from dataclasses import dataclass
from app.models.company import Company
from app.models.contact import Contact


@dataclass
class ScoreResult:
    """Result of lead scoring."""
    score: int
    priority: str
    reasons: list[str]


def score_lead(company: Company, contact: Contact | None = None) -> ScoreResult:
    """
    Calculate deterministic lead score based on available data.

    Scoring rubric:
    - Business email available: +20
    - Website available: +10
    - Product information available: +20
    - Relevant product category: +20
    - Company description available: +10
    - Country/market available: +10
    - Public business contact: +10

    Maximum: 100
    """
    score = 0
    reasons = []

    # Business email available
    if contact and contact.business_email:
        score += 20
        reasons.append("Business email available (+20)")

    # Website available
    if company.website:
        score += 10
        reasons.append("Website available (+10)")

    # Product information available
    if company.products:
        score += 20
        reasons.append(f"Product information available ({len(company.products)} products) (+20)")

    # Relevant product category
    if company.products:
        categories = [p.category for p in company.products if p.category]
        if categories:
            score += 20
            reasons.append(f"Relevant product categories: {', '.join(categories[:3])} (+20)")

    # Company description available
    if company.description and len(company.description) > 20:
        score += 10
        reasons.append("Company description available (+10)")

    # Country/market available
    if company.country:
        score += 10
        reasons.append(f"Country/market available: {company.country} (+10)")

    # Public business contact
    if contact and (contact.business_email or contact.phone):
        score += 10
        reasons.append("Public business contact available (+10)")

    # Determine priority
    if score >= 80:
        priority = "HIGH"
    elif score >= 50:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    return ScoreResult(score=score, priority=priority, reasons=reasons)
