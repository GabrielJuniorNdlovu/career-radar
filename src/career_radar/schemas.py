from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    external_id: str
    title: str
    company_name: str
    description: str
    employment_type: str
    seniority: str | None
    provider_seniority: list[str]
    role_category: str
    location_restrictions: list[dict | str] | None
    timezone_restrictions: list[str | int | float] | None
    location_compatibility: str
    timezone_compatibility: str
    eligibility_reasons: list[str]
    needs_review: bool
    min_salary: Decimal | None
    max_salary: Decimal | None
    currency: str | None
    salary_period: str | None
    application_url: str
    provider_updated_at: datetime | None
    provider_expires_at: datetime | None
    posted_at: datetime | None
    first_discovered_at: datetime
    last_seen_at: datetime
    last_verified_at: datetime
    status: str
    provenance: dict


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    limit: int
    offset: int
    attribution: str = "Jobs sourced from Himalayas · https://himalayas.app"


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    fetched: int
    accepted: int
    rejected: int
    inserted: int
    updated: int
    unchanged: int
    failed: int
    diagnostics: dict
