from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


def identifier() -> str:
    return str(uuid4())


class UTCDateTime(TypeDecorator):
    """MySQL DATETIME has no offset; bind UTC and restore UTC on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timezone-aware datetime required")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "opportunity_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    url: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="disabled")
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_opportunity_source_external"),
        Index("ix_jobs_status_discovered", "status", "first_discovered_at", "id"),
        Index("ix_jobs_category_employment", "role_category", "employment_type"),
        Index("ix_jobs_location_status", "location_compatibility", "status"),
        Index("ix_jobs_company", "company_name"),
        Index("ix_jobs_seniority", "seniority"),
        Index("ix_jobs_verified", "last_verified_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    source_id: Mapped[str] = mapped_column(ForeignKey("opportunity_sources.id"))
    external_id: Mapped[str] = mapped_column(
        String(512, collation="utf8mb4_bin").with_variant(String(512), "sqlite")
    )
    title: Mapped[str] = mapped_column(String(512))
    company_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"))
    employment_type: Mapped[str] = mapped_column(String(30))
    seniority: Mapped[str | None] = mapped_column(String(30))
    provider_seniority: Mapped[list] = mapped_column(JSON)
    role_category: Mapped[str] = mapped_column(String(50))
    location_restrictions: Mapped[list | None] = mapped_column(JSON)
    timezone_restrictions: Mapped[list | None] = mapped_column(JSON)
    location_compatibility: Mapped[str] = mapped_column(String(20))
    timezone_compatibility: Mapped[str] = mapped_column(String(20))
    eligibility_reasons: Mapped[list] = mapped_column(JSON)
    needs_review: Mapped[bool] = mapped_column(default=False)
    min_salary: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    max_salary: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(20))
    application_url: Mapped[str] = mapped_column(Text)
    provider_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    provider_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    first_discovered_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_verified_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20))
    fingerprint: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[dict] = mapped_column(JSON)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (Index("ix_runs_started", "started_at", "id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    source_id: Mapped[str] = mapped_column(ForeignKey("opportunity_sources.id"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="running")
    fetched: Mapped[int] = mapped_column(default=0)
    accepted: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    inserted: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    unchanged: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
