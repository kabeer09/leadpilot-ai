"""Company schemas."""
from datetime import datetime
from pydantic import BaseModel


class CompanyResponse(BaseModel):
    id: int
    source_id: int
    company_name: str
    website: str | None
    description: str | None
    industry: str | None
    country: str | None
    city: str | None
    address: str | None
    exhibition_name: str | None
    hall: str | None
    booth: str | None
    source_url: str | None
    exhibitor_url: str | None

    # Enrichment fields
    enrichment_status: str | None = None
    enrichment_source_url: str | None = None
    enrichment_checked_at: datetime | None = None
    enrichment_confidence: float | None = None
    enrichment_method: str | None = None
    enrichment_error: str | None = None

    # Data-quality fields (§4/§7)
    company_type: str | None = None
    completeness: float | None = None
    verified: bool | None = None
    last_verified: datetime | None = None
    normalized_name: str | None = None
    normalized_domain: str | None = None
    notes: str | None = None

    # Lifecycle (NULL = active prospect)
    lifecycle_status: str | None = None
    merged_into_id: int | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CompanyDetailResponse(CompanyResponse):
    products: list["ProductResponse"] = []
    contacts: list["ContactResponse"] = []


class ProductResponse(BaseModel):
    id: int
    company_id: int
    name: str
    category: str | None
    description: str | None
    source_url: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactResponse(BaseModel):
    id: int
    company_id: int
    business_email: str | None
    alternate_email: str | None = None
    email_source: str | None = None
    normalized_email: str | None = None
    normalized_phone: str | None = None
    phone: str | None
    whatsapp_number: str | None
    email_source_url: str | None
    whatsapp_source_url: str | None
    verified: bool
    contact_type: str
    consent_status: str | None = None
    whatsapp_eligible: bool | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyListResponse(CompanyResponse):
    """Company list item with nested contacts + products (table view)."""

    contacts: list[ContactResponse] = []
    products: list[ProductResponse] = []


class EnrichmentResult(BaseModel):
    status: str
    emails: list[str] = []
    phones: list[str] = []
    whatsapp: list[str] = []
    source_url: str | None = None
    confidence: float = 0.0
    method: str | None = None
    error: str | None = None
