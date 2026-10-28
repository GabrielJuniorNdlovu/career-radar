"""Provider validation and deterministic selection. No network or database access."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from html import unescape
from urllib.parse import urlsplit

import pycountry
from pydantic import BaseModel, ConfigDict, Field, field_validator

EMPLOYMENT_TYPES = ["Intern", "Part Time", "Contractor", "Full Time"]
SENIORITIES = ["entry", "junior", "mid"]
COMPATIBILITIES = ["compatible", "incompatible", "unknown"]
STATUSES = ["open", "closed", "expired", "stale", "unknown"]
DEFAULT_ROLES = {
    "data_analytics": ["Data Engineer", "Data Scientist", "Data Analyst", "Analytics Engineer"],
    "ai_ml": ["Machine Learning Engineer", "AI Engineer", "ML Engineer", "MLOps Engineer"],
    "software_web": [
        "Software Engineer",
        "Software Developer",
        "Web Developer",
        "Frontend Developer",
        "Backend Developer",
        "Full Stack Developer",
        "Python Developer",
    ],
    "infrastructure": [
        "DevOps Engineer",
        "Cloud Engineer",
        "Platform Engineer",
        "AIOps Engineer",
        "Site Reliability Engineer",
        "Infrastructure Engineer",
    ],
}


class Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[str, list[str]] = Field(default_factory=lambda: DEFAULT_ROLES.copy())
    employment_types: list[str] = Field(default_factory=lambda: EMPLOYMENT_TYPES.copy())
    country: str = Field(default="ZW", pattern=r"^[A-Z]{2}$")
    utc_offset: str = "UTC+02:00"

    @field_validator("roles")
    @classmethod
    def valid_roles(cls, value):
        if (
            not value
            or any(not terms or not all(t.strip() for t in terms) for terms in value.values())
            or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", key) for key in value)
        ):
            raise ValueError("role categories require nonempty search terms")
        return value

    @field_validator("utc_offset")
    @classmethod
    def valid_offset(cls, value):
        offset_minutes(value)
        return value

    @field_validator("employment_types")
    @classmethod
    def valid_types(cls, value):
        if not value or not set(value) <= set(EMPLOYMENT_TYPES):
            raise ValueError("unsupported employment type")
        return value


def safe_himalayas_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "himalayas.app"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/companies/")
        or "/jobs/" not in parsed.path
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("expected an original HTTPS Himalayas job URL")
    return value


class ProviderJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    guid: str = Field(min_length=1, max_length=512)
    applicationLink: str = Field(max_length=2048)
    title: str = Field(min_length=1, max_length=512)
    companyName: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=2_000_000)
    employmentType: str
    seniority: list[str] = Field(default_factory=list)
    locationRestrictions: list[dict[str, str] | str] | None = None
    timezoneRestrictions: list[str | int | float] | None = None
    categories: list[str] = Field(default_factory=list)
    parentCategories: list[str] = Field(default_factory=list)
    pubDate: int | None = None
    expiryDate: int | None = None
    minSalary: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    maxSalary: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    salaryPeriod: str | None = Field(
        default=None, pattern=r"^(hourly|weekly|fortnightly|monthly|annual)$"
    )

    _urls = field_validator("guid", "applicationLink")(safe_himalayas_url)

    @field_validator("seniority", mode="before")
    @classmethod
    def missing_seniority(cls, value):
        return [] if value is None else value

    @field_validator("pubDate", "expiryDate")
    @classmethod
    def valid_timestamp(cls, value):
        if value is not None:
            if datetime.fromtimestamp(value, UTC).year < 1000:
                raise ValueError("timestamp outside MySQL DATETIME range")
        return value


def text_key(value: str) -> str:
    value = re.sub(r"(?i)\b(front|back)[ -]?end\b", r"\1end", value)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def evaluate(job: ProviderJob, criteria: Criteria) -> tuple[str, str | None, bool] | None:
    title = text_key(job.title)
    if job.employmentType not in criteria.employment_types:
        return None
    junior = bool(re.search(r"\b(junior|jr|graduate|entry|intern|trainee)\b", title))
    senior_title = bool(
        re.search(
            r"\b(senior|sr|principal|staff|lead|director|executive|head|manager|chief|vp)\b", title
        )
    )
    lower_levels = set(job.seniority) & {"Entry-level", "Mid-level"}
    # Only an explicitly junior title plus lower-level metadata permits a conflicting title.
    review = senior_title and junior and bool(lower_levels)
    if senior_title and not review:
        return None
    if not lower_levels and not junior and job.employmentType != "Intern":
        return None
    if set(job.seniority) & {"Senior", "Manager", "Director", "Executive"}:
        if not lower_levels and not junior:
            return None
        review = True
    category = None
    for group, terms in criteria.roles.items():
        for term in terms:
            key = text_key(term)
            aliases = {key, key.replace("developer", "engineer")}
            if key == "site reliability engineer":
                aliases.add("sre")
            if "full stack" in key:
                aliases.add(key.replace("full stack", "fullstack"))
            if any(re.search(r"\b" + re.escape(alias) + r"\b", title) for alias in aliases):
                category = group
                break
        if category:
            break
    if category is None and re.search(r"\b(intern|internship)\b", title):
        evidence = text_key(" ".join(job.categories + job.parentCategories))
        description = text_key(job.description)
        for group, terms in criteria.roles.items():
            for term in terms:
                key = text_key(term)
                stem = key.rsplit(" ", 1)[0]
                discipline = key.replace("engineer", "engineering").replace("scientist", "science")
                title_evidence = (
                    re.fullmatch(r"(?:engineering|developer|technical) intern", title)
                    or re.search(
                        r"\b" + re.escape(stem) + r"(?: engineering| science)? intern(?:ship)?\b",
                        title,
                    )
                    or re.search(r"\b" + re.escape(discipline) + r"\b", title)
                )
                if (
                    title_evidence
                    and re.search(r"\b" + re.escape(stem) + r"\b", evidence)
                    and any(
                        re.search(r"\b" + re.escape(phrase) + r"\b", description)
                        for phrase in (key, discipline)
                    )
                ):
                    category = group
                    break
            if category:
                break
    if category is None:
        return None
    level: str | None = "junior" if junior else "mid" if "Mid-level" in lower_levels else "entry"
    if job.employmentType == "Intern" and not job.seniority:
        level = None
    return category, level, review


def offset_minutes(value: str | int | float) -> int:
    if isinstance(value, (int, float)):
        if (
            isinstance(value, bool)
            or not math.isfinite(value)
            or abs(value) > 14
            or value * 60 != int(value * 60)
        ):
            raise ValueError("invalid numeric UTC offset")
        return int(value * 60)
    match = re.fullmatch(r"(?:UTC)?([+-])(\d{1,2})(?::(\d{2}))?", value.strip(), re.I)
    if not match:
        raise ValueError("unrecognized UTC offset")
    sign, hours, minutes = match.groups()
    h, m = int(hours), int(minutes or 0)
    if h > 14 or m > 59 or (h == 14 and m):
        raise ValueError("invalid UTC offset")
    return (h * 60 + m) * (1 if sign == "+" else -1)


def compatibility(job: ProviderJob, criteria: Criteria) -> tuple[str, str, list[str]]:
    locations = job.locationRestrictions
    if locations is None:
        location = "unknown"
    elif not locations:
        location = "compatible"
    else:
        codes: list[str | None] = []
        for item in locations:
            label = item if isinstance(item, str) else item.get("alpha2", "")
            try:
                codes.append(pycountry.countries.lookup(label).alpha_2)
            except LookupError:
                codes.append(None)
        location = (
            "compatible"
            if criteria.country in codes
            else "unknown"
            if None in codes
            else "incompatible"
        )
    timezones = job.timezoneRestrictions
    if timezones is None:
        timezone = "unknown"
    elif not timezones:
        timezone = "compatible"
    else:
        parsed = []
        malformed = False
        for offset in timezones:
            try:
                parsed.append(offset_minutes(offset))
            except ValueError:
                malformed = True
        timezone = (
            "compatible"
            if offset_minutes(criteria.utc_offset) in parsed
            else "unknown"
            if malformed
            else "incompatible"
        )
    return (
        location,
        timezone,
        [
            f"country:{location}",
            f"timezone:{timezone}",
            "Work authorization needs independent verification",
        ],
    )


def normalize(job: ProviderJob, criteria: Criteria, now: datetime) -> dict | None:
    match = evaluate(job, criteria)
    if match is None:
        return None
    category, level, review = match
    location, timezone, reasons = compatibility(job, criteria)
    expiry = datetime.fromtimestamp(job.expiryDate, UTC) if job.expiryDate is not None else None
    # Descriptions are exposed as plain text; clients never need to render provider HTML.
    description = unescape(re.sub(r"<[^>]*>", " ", job.description))
    result = dict(
        external_id=job.guid,
        title=job.title,
        company_name=job.companyName,
        description=description,
        employment_type=job.employmentType,
        seniority=level,
        provider_seniority=job.seniority,
        role_category=category,
        location_restrictions=job.locationRestrictions,
        timezone_restrictions=job.timezoneRestrictions,
        location_compatibility=location,
        timezone_compatibility=timezone,
        eligibility_reasons=reasons,
        needs_review=review,
        min_salary=job.minSalary,
        max_salary=job.maxSalary,
        currency=job.currency,
        salary_period=job.salaryPeriod,
        application_url=job.applicationLink,
        provider_updated_at=datetime.fromtimestamp(job.pubDate, UTC)
        if job.pubDate is not None
        else None,
        provider_expires_at=expiry,
        posted_at=None,
        status="expired" if expiry and expiry <= now else "open",
        provenance={
            "source": "Himalayas",
            "source_url": "https://himalayas.app",
            "guid": job.guid,
            "categories": job.categories,
            "parent_categories": job.parentCategories,
        },
    )
    result["fingerprint"] = hashlib.sha256(
        json.dumps(result, sort_keys=True, default=str).encode()
    ).hexdigest()
    return result


def search_plan(criteria: Criteria) -> list[dict[str, str]]:
    plan = []
    for terms in criteria.roles.values():
        for term in terms:
            for employment in criteria.employment_types:
                query = {"q": term, "employment_type": employment, "sort": "recent"}
                if employment != "Intern":
                    query["seniority"] = "Entry-level,Mid-level"
                # Leave geography to local rules so unknown restrictions remain discoverable.
                plan.append(query)
    return plan
