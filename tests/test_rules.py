from datetime import UTC, datetime

import pytest

from career_radar.rules import Criteria, ProviderJob, evaluate, normalize, search_plan


@pytest.fixture
def job():
    return {
        "guid": "https://himalayas.app/companies/example/jobs/data-engineer",
        "applicationLink": "https://himalayas.app/companies/example/jobs/data-engineer",
        "title": "Junior Data Engineer",
        "companyName": "Example",
        "description": "Build Python data pipelines",
        "employmentType": "Full Time",
        "seniority": ["Entry-level"],
        "locationRestrictions": [],
        "timezoneRestrictions": [],
        "pubDate": 1780000000,
        "expiryDate": 2000000000,
    }


def test_search_plan():
    plan = search_plan(Criteria())
    assert any(p["employment_type"] == "Intern" and "seniority" not in p for p in plan)
    assert all("q" in p and p["sort"] == "recent" for p in plan)
    assert any(p.get("seniority") == "Entry-level,Mid-level" for p in plan)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Junior Data Engineer", True),
        ("Graduate Python Developer", True),
        ("Senior Data Engineering Manager", False),
        ("Director of AI", False),
        ("Staff Software Engineer", False),
        ("Sales Engineer", False),
        ("Lead Generation Analyst", False),
        ("Frontend Developer", True),
    ],
)
def test_titles(job, title, expected):
    job["title"] = title
    assert (evaluate(ProviderJob.model_validate(job), Criteria()) is not None) == expected


def test_intern_missing_seniority(job):
    job.pop("seniority")
    job["employmentType"] = "Intern"
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is not None


@pytest.mark.parametrize("employment", ["Temporary", "Volunteer", "Other"])
def test_employment(job, employment):
    job["employmentType"] = employment
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is None


@pytest.mark.parametrize(
    "locations,timezones,location,tz",
    [
        ([], [], "compatible", "compatible"),
        ([{"alpha2": "ZW", "name": "Zimbabwe"}], ["UTC+2"], "compatible", "compatible"),
        ([{"alpha2": "US", "name": "United States"}], ["UTC-5"], "incompatible", "incompatible"),
        (None, None, "unknown", "unknown"),
    ],
)
def test_compatibility(job, locations, timezones, location, tz):
    job.update(locationRestrictions=locations, timezoneRestrictions=timezones)
    result = normalize(ProviderJob.model_validate(job), Criteria(), datetime.now(UTC))
    assert result["location_compatibility"] == location
    assert result["timezone_compatibility"] == tz
    assert result["posted_at"] is None


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://himalayas.app/a",
        "https://evil.test/a",
        "https://himalayas.app@evil.test/a",
    ],
)
def test_unsafe_url(job, url):
    job["applicationLink"] = url
    with pytest.raises(ValueError):
        ProviderJob.model_validate(job)


def test_required_fields(job):
    job.pop("guid")
    with pytest.raises(ValueError):
        ProviderJob.model_validate(job)


def test_category_description_evidence_for_generic_intern_title(job):
    job.update(
        title="Engineering Intern",
        employmentType="Intern",
        seniority=[],
        categories=["Data Engineering"],
        description="Join our Data Engineer internship",
    )
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is not None
    job["description"] = "Join our marketing team"
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is None


def test_invalid_offset_and_category_configuration():
    with pytest.raises(ValueError):
        Criteria(utc_offset="UTC+99:99")
    with pytest.raises(ValueError):
        Criteria(roles={"x" * 51: ["Data Engineer"]})


@pytest.mark.parametrize("title", ["Data Engineer", "Mid-level AI Engineer", "MLOps Engineer"])
def test_mid_seniority(job, title):
    job.update(title=title, seniority=["Mid-level"])
    assert evaluate(ProviderJob.model_validate(job), Criteria())[1] == "mid"


def test_mixed_seniority_flagged(job):
    job.update(title="Data Engineer", seniority=["Mid-level", "Senior"])
    assert evaluate(ProviderJob.model_validate(job), Criteria())[2] is True


def test_unknown_timezone_remains_unknown(job):
    job["timezoneRestrictions"] = ["US working hours"]
    result = normalize(ProviderJob.model_validate(job), Criteria(), datetime.now(UTC))
    assert result["timezone_compatibility"] == "unknown"


def test_non_finite_salary_rejected(job):
    job["minSalary"] = "NaN"
    with pytest.raises(ValueError):
        ProviderJob.model_validate(job)


@pytest.mark.parametrize(
    "title,category,description",
    [
        ("Software Engineering Intern", "Software Engineering", "Work as a Software Engineer"),
        ("Data Science Intern", "Data Science", "Work with a Data Scientist"),
        ("Machine Learning Intern", "Machine Learning", "Become a Machine Learning Engineer"),
    ],
)
def test_discipline_interns(job, title, category, description):
    job.update(
        title=title,
        employmentType="Intern",
        seniority=[],
        categories=[category],
        description=description,
    )
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is not None


def test_live_wire_restriction_types(job):
    job.update(locationRestrictions=["Zimbabwe"], timezoneRestrictions=[2, 5.5, 5.75])
    result = normalize(ProviderJob.model_validate(job), Criteria(), datetime.now(UTC))
    assert result["location_compatibility"] == "compatible"
    assert result["timezone_compatibility"] == "compatible"
    assert result["location_restrictions"] == ["Zimbabwe"]
    assert result["timezone_restrictions"] == [2, 5.5, 5.75]


def test_intern_null_seniority(job):
    job.update(employmentType="Intern", seniority=None)
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is not None


def test_sre_title_alias(job):
    job.update(title="Junior SRE", seniority=["Entry-level"])
    assert evaluate(ProviderJob.model_validate(job), Criteria())[0] == "infrastructure"


def test_iso_named_country_incompatible(job):
    job.update(locationRestrictions=["United States"], timezoneRestrictions=[-5])
    result = normalize(ProviderJob.model_validate(job), Criteria(), datetime.now(UTC))
    assert result["location_compatibility"] == "incompatible"
    assert result["timezone_compatibility"] == "incompatible"


def test_discipline_inflection_in_intern_description(job):
    job.update(
        title="Summer IT Data Engineering Intern",
        employmentType="Intern",
        seniority=[],
        categories=["Data Engineering"],
        description="Seeking students in Data Engineering",
    )
    assert evaluate(ProviderJob.model_validate(job), Criteria()) is not None
