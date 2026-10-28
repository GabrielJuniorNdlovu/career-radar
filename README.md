# CareerRadar backend

F01 collects employment opportunities from Himalayas and serves stored records through FastAPI.
Jobs are sourced from [Himalayas](https://himalayas.app). Every application action must use the
original `application_url`. Descriptions returned by this API are plain text.

## Set up the backend

Use Python 3.11 or later and MySQL 8.4. Run these commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
docker compose up -d mysql
alembic upgrade head
career-radar source-init
```

The Compose credentials are for local development. Set different database passwords before hosting.
The MySQL port binds to loopback. The API is intended for private local use; authentication is
required before exposing it publicly.

The migration creates `opportunity_sources`, `opportunities`, and `ingestion_runs` with InnoDB,
utf8mb4, foreign keys, indexed browse fields, and a source/external-ID unique constraint.
`source-init` creates a disabled source. Read `docs/f01.md` and the linked provider rules before enabling.

## Run ingestion

```bash
career-radar source-init --enable
# Set SOURCE_SYNC_ENABLED=true in .env.
career-radar ingest --test-run
# After the provider's 24-hour polling interval:
career-radar ingest
# Or choose bounded limits:
career-radar ingest --max-queries 20 --max-pages 5 --max-requests 100
```

A test run persists results. It uses one search query, at most two pages and four HTTP attempts.
All executions respect the same 24-hour polling gate, including partial and failed runs, to avoid
repeated polling of cached provider results. The JSON summary reports `success`, `partial`, or
`failed`. Exit codes are 0, 2, and 1 respectively. Budget exhaustion produces a partial run.
A complete configured plan means every query reached an empty page; it does not guarantee every
matching listing was captured because provider search results can move between numbered pages.

Configuration uses environment variables, documented in `.env.example`. Optional `HIMALAYAS_API_KEY`
uses a server-side Bearer header. The source registry never stores keys. `CRITERIA_PATH` can point to
JSON overriding `roles`, `employment_types`, `country`, and `utc_offset`. For example:

```json
{"roles":{"data_analytics":["Data Engineer","Data Analyst"]},"country":"ZW","utc_offset":"UTC+02:00"}
```

Defaults include data and analytics, AI and ML, software and web, and infrastructure roles.
Employment types are Intern, Part Time, Contractor, and Full Time. Non-intern searches use
Entry-level and Mid-level provider values. Each role has a separate internship search without a
seniority filter. Local title rules recognize junior and graduate variants and reject explicit senior
or leadership titles, except conflicting junior/lower-level evidence flagged `needs_review`.

## Start and query the API

```bash
uvicorn career_radar.api:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl 'http://127.0.0.1:8000/api/v1/jobs?limit=20&offset=0&role_category=data_analytics'
```

Open [Swagger](http://127.0.0.1:8000/docs) for the generated API contract.

- `GET /health` checks the process.
- `GET /ready` checks database connectivity. Apply migrations before serving requests.
- `GET /api/v1/jobs` supports role_category, employment_type, seniority, company,
  location_compatibility, status, date_from, date_to, and keyword. Company uses exact matching.
  Keyword searches title and description as literal text. Date bounds filter first discovery,
  must include a timezone, and are inclusive. Pagination defaults to 20, maximum 100,
  with offset capped at 100000 and stable discovery/ID ordering.
- `GET /api/v1/jobs/filters` lists supported filter values.
- `GET /api/v1/jobs/{id}` returns details and provenance, or 404.
- `GET /api/v1/ingestion-runs/latest` returns the last run, or 404 before any run.

The default jobs list excludes closed, expired, and stale records. Geographic and timezone
compatibility are independent and can be unknown. Compatible remote geography does not establish
legal work authorization. Use `location_compatibility=compatible` to restrict geography.
No HTTP endpoint triggers ingestion.

## Run checks

```bash
ruff format --check .
ruff check .
mypy
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q
alembic upgrade head --sql
```

The default suite mocks HTTP and uses SQLite for fast orchestration/API checks. It does not prove
MySQL behavior. To run MySQL integration checks, create a disposable database ending in `_test`:

```bash
# Run in your MySQL administrative client:
# CREATE DATABASE careerradar_test CHARACTER SET utf8mb4;
# GRANT ALL ON careerradar_test.* TO 'careerradar'@'%';
TEST_DATABASE_URL='mysql+pymysql://careerradar:careerradar@127.0.0.1:3306/careerradar_test' PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m mysql
```

The MySQL fixture applies and checks Alembic migrations, then downgrades its test tables. Never use a production database.
Validate migrations against a fresh MySQL database with `alembic upgrade head`, `alembic check`,
and a downgrade/upgrade cycle on that disposable database. Back up production data before a rollback;
`alembic downgrade base` deletes these feature tables.

See [verification results and environment limits](docs/verification-f01.md) and
[F01 behavior and decisions](docs/f01.md) for pipeline semantics and limitations.
