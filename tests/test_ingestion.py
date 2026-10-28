from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from career_radar.config import Settings
from career_radar.ingestion import _run_locked, configure_source, run_ingestion
from career_radar.models import IngestionRun, Opportunity, utcnow
from career_radar.provider import HimalayasClient
from career_radar.rules import Criteria


def execute(engine, raw_job, malformed=False):
    configure_source(engine, True)
    settings = Settings(
        _env_file=None,
        source_sync_enabled=True,
        max_queries=1,
        max_pages=3,
        max_requests=10,
        request_interval=0,
    )

    def handler(request):
        page = int(request.url.params.get("page", "1"))
        jobs = [raw_job, raw_job, {}] if malformed else [raw_job, raw_job]
        return httpx.Response(200, json={"jobs": jobs if page == 1 else []})

    client = HimalayasClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    # SQLite exercises orchestration only. MySQL integration separately proves advisory locking.
    return _run_locked(engine, settings, Criteria(), client)


def age_runs(engine):
    with Session(engine) as session, session.begin():
        for run in session.scalars(select(IngestionRun)):
            run.started_at = utcnow() - timedelta(hours=25)


def test_duplicate_idempotency(engine, raw_job):
    first = execute(engine, raw_job)
    assert first["inserted"] == 1
    assert first["diagnostics"]["duplicates"] == 1
    age_runs(engine)
    second = execute(engine, raw_job)
    assert second["inserted"] == 0
    assert second["unchanged"] == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Opportunity)) == 1


def test_malformed_record_preserves_good_records(engine, raw_job):
    result = execute(engine, raw_job, malformed=True)
    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert result["inserted"] == 1


def test_update_preserves_discovery(engine, raw_job):
    execute(engine, raw_job)
    with Session(engine) as session:
        first_seen = session.scalar(select(Opportunity)).first_discovered_at
    age_runs(engine)
    raw_job["description"] = "A changed description"
    assert execute(engine, raw_job)["updated"] == 1
    with Session(engine) as session:
        assert session.scalar(select(Opportunity)).first_discovered_at == first_seen


def test_disabled_policy(engine, raw_job):
    configure_source(engine)
    with pytest.raises(RuntimeError, match="disabled"):
        _run_locked(engine, Settings(_env_file=None), Criteria(), None)


def test_sqlite_ingestion_refuses_fake_lock(engine):
    with pytest.raises(RuntimeError, match="MySQL"):
        run_ingestion(engine, Settings(_env_file=None))


def test_failed_batch_rolls_back(engine, raw_job, monkeypatch):
    from sqlalchemy import event

    execute(engine, raw_job)
    age_runs(engine)

    def fail(*args):
        raise RuntimeError("forced persistence failure")

    event.listen(Opportunity, "before_update", fail)
    raw_job["description"] = "new description"
    try:
        result = execute(engine, raw_job)
    finally:
        event.remove(Opportunity, "before_update", fail)
    assert result["status"] == "failed"
    assert result["updated"] == 0
    with Session(engine) as session:
        assert session.scalar(select(Opportunity)).description == "Build data pipelines"
    age_runs(engine)
    assert execute(engine, raw_job)["updated"] == 1


def test_failed_search_never_closes_existing(engine, raw_job):
    execute(engine, raw_job)
    age_runs(engine)
    settings = Settings(
        _env_file=None,
        source_sync_enabled=True,
        max_queries=1,
        max_retries=0,
        verification_budget=0,
        request_interval=0,
    )
    client = HimalayasClient(
        settings, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    )
    result = _run_locked(engine, settings, Criteria(), client)
    assert result["status"] == "partial"
    with Session(engine) as session:
        assert session.scalar(select(Opportunity)).status == "open"


@pytest.mark.parametrize("code,expected", [(410, "closed"), (404, "unknown"), (503, "open")])
def test_verification_lifecycle(engine, raw_job, code, expected):
    execute(engine, raw_job)
    age_runs(engine)
    with Session(engine) as session, session.begin():
        session.scalar(select(Opportunity)).last_verified_at = utcnow() - timedelta(hours=25)
    settings = Settings(
        _env_file=None, source_sync_enabled=True, max_queries=1, max_retries=0, request_interval=0
    )

    def handler(request):
        if request.url.path.endswith("search"):
            return httpx.Response(200, json={"jobs": []})
        return httpx.Response(code)

    client = HimalayasClient(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    _run_locked(engine, settings, Criteria(), client)
    with Session(engine) as session:
        assert session.scalar(select(Opportunity)).status == expected


def test_expired_job_not_open(engine, raw_job):
    raw_job["expiryDate"] = 1
    execute(engine, raw_job)
    with Session(engine) as session:
        assert session.scalar(select(Opportunity)).status == "expired"


def test_polling_gate(engine, raw_job):
    execute(engine, raw_job)
    with pytest.raises(RuntimeError, match="24-hour"):
        execute(engine, raw_job)


def test_complete_search_reports_success(engine, raw_job):
    configure_source(engine, True)
    settings = Settings(_env_file=None, source_sync_enabled=True, request_interval=0)
    criteria = Criteria(roles={"data_analytics": ["Data Engineer"]}, employment_types=["Full Time"])
    client = HimalayasClient(
        settings,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"jobs": [raw_job] if request.url.params.get("page") == "1" else []}
                )
            )
        ),
    )
    result = _run_locked(engine, settings, criteria, client)
    assert result["status"] == "success"
    assert result["inserted"] == 1
    assert result["diagnostics"]["queries_completed"] == 1
