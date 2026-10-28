from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from career_radar.api import create_app
from career_radar.models import Opportunity, utcnow
from tests.test_ingestion import execute


def test_health_ready_and_empty(engine):
    client = TestClient(create_app(engine))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert client.get("/api/v1/jobs").json()["total"] == 0
    assert client.get("/api/v1/ingestion-runs/latest").status_code == 404
    assert client.get("/api/v1/jobs/filters").status_code == 200
    assert client.get("/api/v1/jobs/not-a-uuid").status_code == 422


def test_filtering_pagination_and_detail(engine, raw_job):
    execute(engine, raw_job)
    client = TestClient(create_app(engine))
    response = client.get("/api/v1/jobs", params={"company": "Example", "keyword": "pipelines"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert "Himalayas" in body["attribution"]
    job_id = body["items"][0]["id"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["posted_at"] is None
    assert client.get("/api/v1/jobs?offset=1").json()["items"] == []
    assert client.get("/api/v1/jobs?employment_type=Intern").json()["total"] == 0
    assert client.get("/api/v1/jobs?keyword=%25").json()["total"] == 0
    assert client.get("/api/v1/jobs?limit=101").status_code == 422
    assert client.get("/api/v1/jobs?status=garbage").status_code == 422
    assert client.get("/api/v1/jobs?date_from=2026-01-01T00:00:00").status_code == 422
    assert client.get("/api/v1/ingestion-runs/latest").json()["inserted"] == 1


def test_expired_and_stale_not_active(engine, raw_job):
    execute(engine, raw_job)
    client = TestClient(create_app(engine))
    with Session(engine) as session, session.begin():
        job = session.query(Opportunity).one()
        job_id = job.id
        job.last_verified_at = utcnow() - timedelta(hours=25)
    assert client.get("/api/v1/jobs").json()["total"] == 0
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "stale"
    with Session(engine) as session, session.begin():
        job = session.get(Opportunity, job_id)
        job.provider_expires_at = utcnow() - timedelta(hours=1)
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "expired"


def test_readiness_failure_is_sanitized(engine):
    from sqlalchemy import event

    def fail(*args):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("password=secret", {}, RuntimeError("secret"))

    event.listen(engine, "before_cursor_execute", fail)
    client = TestClient(create_app(engine))
    response = client.get("/ready")
    assert response.status_code == 503
    assert "secret" not in response.text


def test_aged_records_accessible_through_effective_status_filters(engine, raw_job):
    execute(engine, raw_job)
    client = TestClient(create_app(engine))
    with Session(engine) as session, session.begin():
        job = session.query(Opportunity).one()
        job.last_verified_at = utcnow() - timedelta(hours=25)
    assert client.get("/api/v1/jobs?status=stale").json()["total"] == 1
    with Session(engine) as session, session.begin():
        job = session.query(Opportunity).one()
        job.provider_expires_at = utcnow() - timedelta(hours=1)
    assert client.get("/api/v1/jobs?status=expired").json()["total"] == 1
