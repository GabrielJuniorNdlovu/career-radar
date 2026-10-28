"""Real MySQL checks; never substitute SQLite for this marker."""

import os
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from career_radar.db import source_lock
from career_radar.models import IngestionRun, Opportunity, utcnow
from tests.test_ingestion import execute


@pytest.fixture
def mysql_engine(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not configured; real MySQL unverified")
    engine = create_engine(url, hide_parameters=True)
    assert engine.dialect.name == "mysql"
    assert engine.url.database and engine.url.database.endswith("_test"), (
        "use a disposable _test DB"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.check(config)
    try:
        yield engine
    finally:
        command.downgrade(config, "base")
        engine.dispose()


@pytest.mark.mysql
def test_real_mysql_upsert_lock_and_rollback(mysql_engine, raw_job):
    engine = mysql_engine
    with source_lock(engine), pytest.raises(RuntimeError, match="already running"):
        with source_lock(engine):
            pass
    first = execute(engine, raw_job)
    assert first["inserted"] == 1
    with Session(engine) as session, session.begin():
        session.scalar(select(IngestionRun)).started_at = utcnow() - timedelta(hours=25)
    second = execute(engine, raw_job)
    assert second["unchanged"] == 1
    with Session(engine) as session:
        original = session.scalar(select(Opportunity))
        data = {
            column.name: getattr(original, column.name)
            for column in Opportunity.__table__.columns
            if column.name != "id"
        }
        session.add(Opportunity(**data))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert len(list(session.scalars(select(Opportunity)))) == 1
        assert session.scalar(select(Opportunity)).first_discovered_at.tzinfo is not None
