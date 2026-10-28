# F01 verification report

Verified on 2026-10-28 with Python 3.14.4.

## Completed checks

- Full suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/pytest -q`.
  Result: 71 passed, 1 skipped, 1 dependency deprecation warning.
- `.venv/bin/ruff check .`: passed with Ruff 0.17.3.
- `.venv/bin/ruff format --check .`: all checked files formatted.
- Mypy 2.4.1: no issues in 10 source files.
- `python3 -m compileall -q src tests migrations`: passed.
- `alembic upgrade head --sql` and `alembic downgrade 0001:base --sql`: compiled for MySQL.
  The generated SQL contains InnoDB, utf8mb4, MEDIUMTEXT, the unique source/external key,
  and the expected upgrade/downgrade table operations. This verifies generation, not execution.
- OpenAPI generated all six requested path contracts. Both list/detail operations share the
  effective lifecycle status expression, including expiry and stale status filtering.
- Uvicorn started on loopback, served `/health` and `/openapi.json` with 200, and stopped cleanly.
  `/ready` returned 503 because no MySQL server was available.
- A bounded real Himalayas search returned HTTP 200 with 20 records. The captured response
  validated all 20 through `ProviderJob`; 12 matched the final local role rules. No live records were stored.
  Several validation requests were needed to resolve the observed schema mismatch. The captured
  response is a temporary local artifact and is not committed as a provider snapshot.

## Failure and integrity evidence

`test_duplicate_idempotency` ingests identical fixtures twice and verifies one stored job and zero
new inserts. `test_failed_batch_rolls_back` forces a real SQLAlchemy persistence failure, verifies
the old description survives and updated counts stay zero, then verifies the next ingestion recovers.
`test_failed_search_never_closes_existing` confirms partial HTTP failure preserves open records.
Lifecycle tests distinguish 410 closure, 404 unknown, expiry, and failed verification.

Focused regression tests failed before corrections for category/description fallback, invalid offset
configuration, standard discipline internship titles, live restriction types, and browse status
filtering. The initial runtime environment lacked pytest, so failing-before execution of the initial
feature tests was unavailable until dependencies installed. This was incremental testing, not a
claim that every production line followed a demonstrated red/green cycle.

The architecture review compared atomic bounded persistence and per-page checkpoints. A read-only
reviewer checked the implementation for data loss, transaction boundaries, lifecycle behavior,
classification, and maintainability. Findings corrected include MySQL description capacity, effective
status consistency, internship evidence, input validation, and verification counters. Actual-code
checks reproduced the internship gap. There is no existing project verification skill to maintain.
No broad multi-model review or benchmark was performed.

## Environment limits

The configured Docker daemon socket is unavailable, no MySQL server binary was found, and
`TEST_DATABASE_URL` was not configured. The real MySQL test explicitly skipped. MySQL advisory
locking, actual migration upgrade/check/downgrade, and MySQL write behavior remain unverified live.
The MySQL test fixture applies Alembic, checks schema drift, exercises locking/upserts/unique-key
rollback, and downgrades its disposable `_test` database when an instance is supplied.

SQLite tests prove fast orchestration and API behavior only. They do not prove MySQL collation,
locking, storage limits, or transaction behavior. Before deployment, start MySQL and run the marked
test plus a bounded CLI ingestion after enabling the source policy.

The host exports unrelated ROS pytest plugins which fail on import, so plugin autoload was disabled.
The tests require no external pytest plugins. FastAPI TestClient stalled within the execution
sandbox; the full suite passed outside it. Installed Starlette warns that its HTTPX-based TestClient
will move to HTTPX2. The warning does not affect the passing current contracts.
