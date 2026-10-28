from datetime import datetime, timedelta
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from career_radar.config import Settings
from career_radar.db import make_engine
from career_radar.models import IngestionRun, Opportunity, utcnow
from career_radar.rules import COMPATIBILITIES, EMPLOYMENT_TYPES, SENIORITIES, STATUSES, Criteria
from career_radar.schemas import JobOut, JobPage, RunOut


def create_app(engine: Engine | None = None, settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    db = engine or make_engine(config)
    app = FastAPI(
        title="CareerRadar",
        version="0.1.0",
        description=(
            "Jobs sourced from [Himalayas](https://himalayas.app). "
            "Application actions must use the original application_url. "
            "Descriptions are plain text."
        ),
    )

    def session_dependency():
        with Session(db) as session:
            yield session

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.status_code, "message": exc.detail}},
        )

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": 422, "message": "Invalid request parameters"}},
        )

    @app.exception_handler(SQLAlchemyError)
    def database_error(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            status_code=503, content={"error": {"code": 503, "message": "Database unavailable"}}
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    def effective_status():
        now = utcnow()
        return case(
            (
                and_(
                    Opportunity.status.in_(["open", "stale"]),
                    Opportunity.provider_expires_at <= now,
                ),
                "expired",
            ),
            (
                and_(
                    Opportunity.status == "open",
                    Opportunity.last_verified_at
                    <= now - timedelta(hours=config.verification_max_age_hours),
                ),
                "stale",
            ),
            else_=Opportunity.status,
        )

    @app.get("/api/v1/jobs/filters")
    def filters():
        criteria = Criteria()
        if config.criteria_path:
            import json

            with open(config.criteria_path) as stream:
                criteria = Criteria.model_validate(json.load(stream))
        return {
            "role_categories": list(criteria.roles),
            "employment_types": EMPLOYMENT_TYPES,
            "seniorities": SENIORITIES,
            "location_compatibilities": COMPATIBILITIES,
            "statuses": STATUSES,
        }

    @app.get("/api/v1/jobs", response_model=JobPage)
    def jobs(
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
        role_category: str | None = Query(None, max_length=50),
        employment_type: str | None = Query(None, max_length=30),
        seniority: str | None = Query(None, max_length=30),
        company: str | None = Query(None, min_length=1, max_length=255),
        location_compatibility: str | None = Query(None, max_length=20),
        status: str = Query("open", max_length=20),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        keyword: str | None = Query(None, min_length=1, max_length=200),
        session: Session = Depends(session_dependency),
    ):
        for value, allowed in [
            (employment_type, EMPLOYMENT_TYPES),
            (seniority, SENIORITIES),
            (location_compatibility, COMPATIBILITIES),
            (status, STATUSES),
        ]:
            if value is not None and value not in allowed:
                raise HTTPException(422, "Unsupported filter value")
        if any(date is not None and date.tzinfo is None for date in (date_from, date_to)):
            raise HTTPException(422, "Date bounds must include a timezone")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "Invalid date range")
        lifecycle = effective_status()
        stored_statuses = {"expired": ["expired", "open", "stale"], "stale": ["stale", "open"]}
        predicates = [
            Opportunity.status.in_(stored_statuses.get(status, [status])),
            lifecycle == status,
        ]
        for column, value in [
            (Opportunity.role_category, role_category),
            (Opportunity.employment_type, employment_type),
            (Opportunity.seniority, seniority),
            (Opportunity.company_name, company),
            (Opportunity.location_compatibility, location_compatibility),
        ]:
            if value is not None:
                predicates.append(column == value)
        if date_from:
            predicates.append(Opportunity.first_discovered_at >= date_from)
        if date_to:
            predicates.append(Opportunity.first_discovered_at <= date_to)
        if keyword:
            predicates.append(
                or_(
                    Opportunity.title.contains(keyword, autoescape=True),
                    Opportunity.description.contains(keyword, autoescape=True),
                )
            )
        total = session.scalar(select(func.count()).select_from(Opportunity).where(*predicates))
        rows = session.execute(
            select(Opportunity, lifecycle)
            .where(*predicates)
            .order_by(Opportunity.first_discovered_at.desc(), Opportunity.id)
            .offset(offset)
            .limit(limit)
        )
        return JobPage(
            items=[
                JobOut.model_validate(row).model_copy(update={"status": state})
                for row, state in rows
            ],
            total=total or 0,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/v1/jobs/{job_id}", response_model=JobOut)
    def job_detail(job_id: UUID, session: Session = Depends(session_dependency)):
        row = session.execute(
            select(Opportunity, effective_status()).where(Opportunity.id == str(job_id))
        ).first()
        if row is None:
            raise HTTPException(404, "Job not found")
        job, state = row
        return JobOut.model_validate(job).model_copy(update={"status": state})

    @app.get("/api/v1/ingestion-runs/latest", response_model=RunOut)
    def latest_run(session: Session = Depends(session_dependency)):
        run = session.scalar(
            select(IngestionRun).order_by(IngestionRun.started_at.desc(), IngestionRun.id).limit(1)
        )
        if run is None:
            raise HTTPException(404, "No ingestion runs recorded")
        return run

    return app


app = create_app()
