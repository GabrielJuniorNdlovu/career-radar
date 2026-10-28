import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from career_radar.models import Base


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def raw_job():
    return {
        "guid": "https://himalayas.app/companies/example/jobs/data-engineer",
        "applicationLink": "https://himalayas.app/companies/example/jobs/data-engineer",
        "title": "Junior Data Engineer",
        "companyName": "Example",
        "description": "Build data pipelines",
        "employmentType": "Full Time",
        "seniority": ["Entry-level"],
        "locationRestrictions": [],
        "timezoneRestrictions": [],
        "pubDate": 1780000000,
        "expiryDate": 2000000000,
    }
