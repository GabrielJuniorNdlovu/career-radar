# F01 implementation decisions

Status: Accepted for F01. Date: 2026-10-28.

The owner authorized a backend-only discovery increment on the design-only repository.
F01 uses FastAPI, synchronous SQLAlchemy 2.x with PyMySQL, MySQL 8.4, Alembic, Pydantic, and HTTPX.
UUIDs use readable CHAR-compatible string storage. All timestamps cross API boundaries as UTC.

The module design compares two alternatives: per-page commits with durable checkpoints, and bounded
collection followed by atomic persistence. The latter fits the manual bounded workload and keeps
HTTP out of transactions. The source service owns all opportunity writes, run state, and locking.
Provider transport and deterministic classification remain independent of FastAPI and SQLAlchemy.

The published architecture's broad domain tables, worker scheduling, React, and Gemini are deferred
by the explicit F01 scope. F01 uses `opportunity_sources` as the source registry, per the owner's
minimum schema. A later cross-source identity design will need a migration if it introduces a
separate many-to-many provenance table with the same conceptual name.

A read-only design reviewer agreed with the bounded atomic design and called out advisory-lock
connection lifetime and committed statistics as the central safety requirements. The subsequent
code review found description column capacity, effective status filtering, and category evidence
gaps. Regression tests cover the resulting corrections. Live MySQL execution is recorded separately
in the verification report rather than inferred from SQLite tests.
