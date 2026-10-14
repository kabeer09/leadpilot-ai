"""Source schemas."""
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field


class SourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: HttpUrl
    source_type: str = "exhibitor_directory"


class SourceResponse(BaseModel):
    id: int
    name: str
    url: str
    source_type: str
    status: str
    last_crawled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
