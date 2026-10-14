"""Lead schemas."""
from datetime import datetime
from pydantic import BaseModel


class LeadResponse(BaseModel):
    id: int
    company_id: int
    contact_id: int | None
    campaign_id: int | None
    lead_score: int
    lead_priority: str
    ai_summary: str | None
    ai_reason: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactResponse(BaseModel):
    id: int
    company_id: int
    business_email: str | None
    alternate_email: str | None = None
    email_source: str | None = None
    phone: str | None
    whatsapp_number: str | None
    email_source_url: str | None
    whatsapp_source_url: str | None
    verified: bool
    contact_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


class OutreachResponse(BaseModel):
    id: int
    lead_id: int
    channel: str
    status: str
    subject: str | None
    message: str | None
    sent_at: datetime | None
    scheduled_at: datetime | None
    response_at: datetime | None
    error: str | None
    provider_message_id: str | None = None
    provider_thread_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MeetingResponse(BaseModel):
    id: int
    lead_id: int
    calendar_event_id: str | None
    meet_url: str | None
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ActivityResponse(BaseModel):
    id: int
    lead_id: int
    activity_type: str
    description: str | None
    metadata_: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadDetailResponse(LeadResponse):
    company: CompanyResponse | None = None
    contact: ContactResponse | None = None
    outreach: list[OutreachResponse] = []
    meetings: list[MeetingResponse] = []
    activities: list[ActivityResponse] = []


class ProductBrief(BaseModel):
    id: int
    name: str
    category: str | None = None

    model_config = {"from_attributes": True}


class CompanyWithProducts(CompanyResponse):
    products: list[ProductBrief] = []


class OutreachBrief(BaseModel):
    id: int
    channel: str
    status: str
    subject: str | None = None
    sent_at: datetime | None = None
    response_at: datetime | None = None
    follow_up_count: int | None = None
    follow_up_sent_at: datetime | None = None
    provider_thread_id: str | None = None

    model_config = {"from_attributes": True}


class LeadListResponse(LeadResponse):
    """Lead list item with nested company (+products) and contact."""

    company: CompanyWithProducts | None = None
    contact: ContactResponse | None = None
    last_outreach: OutreachBrief | None = None
