import json
import logging
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from career_radar.config import Settings
from career_radar.db import source_lock
from career_radar.models import IngestionRun, Opportunity, Source, utcnow
from career_radar.provider import BudgetExceeded, HimalayasClient, ProviderError
from career_radar.rules import Criteria, ProviderJob, normalize, search_plan

logger = logging.getLogger(__name__)
POLICY = {
    "reviewed_at": "2026-10-28",
    "reference": "https://himalayas.app/docs/remote-jobs-api",
    "attribution": "Jobs sourced from Himalayas · https://himalayas.app",
    "application_link": "Preserve applicationLink exactly",
    "storage": "Private job browsing; no redistribution feeds or JobPosting syndication",
    "polling_interval_hours": 24,
    "closure": "Exclude expiry, 410 closure, and unverified stale jobs from active results",
}


def configure_source(engine: Engine, enabled: bool = False) -> Source:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        source = session.scalar(select(Source).where(Source.name == "himalayas"))
        if source is None:
            source = Source(
                name="himalayas",
                url="https://himalayas.app",
                policy=POLICY,
                configuration={"adapter": "himalayas-v1"},
                status="disabled",
            )
            session.add(source)
        if enabled:
            source.policy = POLICY.copy()
            source.status = "enabled"
    return source


def run_ingestion(
    engine: Engine, settings: Settings, provider: HimalayasClient | None = None
) -> dict:
    criteria = Criteria(country=settings.user_country, utc_offset=settings.user_utc_offset)
    if settings.criteria_path:
        with open(settings.criteria_path) as stream:
            criteria = Criteria.model_validate({**criteria.model_dump(), **json.load(stream)})
    with source_lock(engine):
        return _run_locked(engine, settings, criteria, provider)


def _run_locked(
    engine: Engine, settings: Settings, criteria: Criteria, provider: HimalayasClient | None
) -> dict:
    now = utcnow()
    with Session(engine) as session, session.begin():
        source = session.scalar(select(Source).where(Source.name == "himalayas"))
        if (
            not settings.source_sync_enabled
            or source is None
            or source.status != "enabled"
            or any(source.policy.get(k) != v for k, v in POLICY.items())
        ):
            raise RuntimeError("source disabled or policy review missing; use source-init --enable")
        source_id = source.id
        prior = session.scalar(
            select(IngestionRun)
            .where(IngestionRun.source_id == source_id)
            .order_by(IngestionRun.started_at.desc())
            .limit(1)
        )
        if prior and prior.started_at > now - timedelta(hours=24):
            raise RuntimeError("Himalayas was requested within the 24-hour polling interval")
        # Holding the source lock proves any older running entry was abandoned.
        abandoned = session.scalars(
            select(IngestionRun).where(
                IngestionRun.source_id == source_id, IngestionRun.status == "running"
            )
        )
        for old in abandoned:
            old.status, old.completed_at = "failed", now
            old.diagnostics = {**old.diagnostics, "interrupted": True}
        started_run = IngestionRun(source_id=source_id, started_at=now)
        session.add(started_run)
        session.flush()
        run_id = started_run.id

    client = provider or HimalayasClient(settings)
    counts = dict(fetched=0, accepted=0, rejected=0, failed=0, inserted=0, updated=0, unchanged=0)
    diagnostics: dict = {
        "errors": [],
        "queries_completed": 0,
        "duplicates": 0,
        "verified": 0,
        "closed": 0,
        "unknown": 0,
    }
    records: dict[str, dict] = {}
    seen: set[str] = set()
    checks: dict[str, str] = {}
    status = "success"
    try:
        plan = search_plan(criteria)
        diagnostics["queries_planned"] = len(plan)
        if len(plan) > settings.max_queries:
            status = "partial"
        for query in plan[: settings.max_queries]:
            try:
                for page in client.search(query):
                    counts["fetched"] += len(page)
                    for raw in page:
                        try:
                            job = ProviderJob.model_validate(raw)
                        except (ValidationError, ValueError, OverflowError):
                            counts["failed"] += 1
                            continue
                        if job.guid in seen:
                            diagnostics["duplicates"] += 1
                            continue
                        seen.add(job.guid)
                        record = normalize(job, criteria, now)
                        if record is None:
                            counts["rejected"] += 1
                        else:
                            counts["accepted"] += 1
                            records[job.guid] = record
                diagnostics["queries_completed"] += 1
            except ProviderError as exc:
                diagnostics["errors"].append(str(exc))
                status = "partial"
                if isinstance(exc, BudgetExceeded):
                    if client.requests >= settings.max_requests:
                        break
        with Session(engine) as session:
            due = list(
                session.scalars(
                    select(Opportunity)
                    .where(
                        Opportunity.source_id == source_id,
                        Opportunity.status.in_(["open", "stale"]),
                        Opportunity.last_verified_at
                        <= now - timedelta(hours=settings.verification_max_age_hours),
                    )
                    .order_by(Opportunity.last_verified_at, Opportunity.id)
                )
            )
        due = [job for job in due if job.external_id not in records]
        if len(due) > settings.verification_budget:
            status = "partial"
        for candidate in due[: settings.verification_budget]:
            try:
                state, raw = client.verify(candidate.external_id)
                diagnostics["verified"] += 1
                if state in ("closed", "unknown"):
                    diagnostics[state] += 1
                if raw is not None:
                    job = ProviderJob.model_validate(raw)
                    record = normalize(job, criteria, now)
                    if record is not None:
                        records[job.guid] = record
                    else:
                        checks[candidate.external_id] = "stale"
                else:
                    checks[candidate.external_id] = state
            except (ProviderError, ValueError, OverflowError):
                diagnostics["errors"].append("single-job verification failed")
                status = "partial"
        if counts["failed"]:
            status = "partial"
        with Session(engine) as session, session.begin():
            for external_id, data in records.items():
                stored = session.scalar(
                    select(Opportunity).where(
                        Opportunity.source_id == source_id, Opportunity.external_id == external_id
                    )
                )
                if stored is None:
                    session.add(
                        Opportunity(
                            source_id=source_id,
                            **data,
                            first_discovered_at=now,
                            last_seen_at=now,
                            last_verified_at=now,
                        )
                    )
                    counts["inserted"] += 1
                else:
                    changed = (
                        stored.fingerprint != data["fingerprint"] or stored.status != data["status"]
                    )
                    for key, value in data.items():
                        setattr(stored, key, value)
                    stored.last_seen_at = stored.last_verified_at = now
                    counts["updated" if changed else "unchanged"] += 1
            for external_id, state in checks.items():
                stored = session.scalar(
                    select(Opportunity).where(
                        Opportunity.source_id == source_id, Opportunity.external_id == external_id
                    )
                )
                if stored:
                    stored.status, stored.last_verified_at = state, now
            expired = session.scalars(
                select(Opportunity).where(
                    Opportunity.source_id == source_id,
                    Opportunity.status.in_(["open", "stale"]),
                    Opportunity.provider_expires_at <= now,
                )
            )
            for stored in expired:
                stored.status = "expired"
            run = session.get(IngestionRun, run_id)
            assert run is not None
            for key, value in counts.items():
                setattr(run, key, value)
            diagnostics.update(requests=client.requests, pages=client.pages)
            run.status, run.completed_at, run.diagnostics = status, utcnow(), diagnostics
    except Exception:
        # Never claim writes committed when the atomic batch rolled back.
        counts.update(inserted=0, updated=0, unchanged=0)
        counts["failed"] += 1
        status = "failed"
        diagnostics["errors"].append("ingestion aborted; batch rolled back")
        with Session(engine) as session, session.begin():
            run = session.get(IngestionRun, run_id)
            assert run is not None
            for key, value in counts.items():
                setattr(run, key, value)
            run.status, run.completed_at, run.diagnostics = status, utcnow(), diagnostics
    finally:
        if provider is None:
            client.close()
    summary = {"id": run_id, "status": status, **counts, "diagnostics": diagnostics}
    logger.info(json.dumps({"event": "ingestion_completed", **summary}))
    return summary
