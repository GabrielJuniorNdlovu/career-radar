"""F01 sources, opportunities and ingestion runs.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import MEDIUMTEXT

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}
    op.create_table(
        "opportunity_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("url", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        **options,
    )
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("opportunity_sources.id"), nullable=False
        ),
        sa.Column("external_id", sa.String(512, collation="utf8mb4_bin"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("employment_type", sa.String(30), nullable=False),
        sa.Column("seniority", sa.String(30)),
        sa.Column("provider_seniority", sa.JSON(), nullable=False),
        sa.Column("role_category", sa.String(50), nullable=False),
        sa.Column("location_restrictions", sa.JSON()),
        sa.Column("timezone_restrictions", sa.JSON()),
        sa.Column("location_compatibility", sa.String(20), nullable=False),
        sa.Column("timezone_compatibility", sa.String(20), nullable=False),
        sa.Column("eligibility_reasons", sa.JSON(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("min_salary", sa.Numeric(18, 2)),
        sa.Column("max_salary", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("salary_period", sa.String(20)),
        sa.Column("application_url", sa.Text(), nullable=False),
        sa.Column("provider_updated_at", sa.DateTime()),
        sa.Column("provider_expires_at", sa.DateTime()),
        sa.Column("posted_at", sa.DateTime()),
        sa.Column("first_discovered_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_opportunity_source_external"),
        **options,
    )
    op.create_index(
        "ix_jobs_status_discovered", "opportunities", ["status", "first_discovered_at", "id"]
    )
    op.create_index(
        "ix_jobs_category_employment", "opportunities", ["role_category", "employment_type"]
    )
    op.create_index(
        "ix_jobs_location_status", "opportunities", ["location_compatibility", "status"]
    )
    op.create_index("ix_jobs_company", "opportunities", ["company_name"])
    op.create_index("ix_jobs_seniority", "opportunities", ["seniority"])
    op.create_index("ix_jobs_verified", "opportunities", ["last_verified_at"])
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("opportunity_sources.id"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fetched", sa.Integer(), nullable=False),
        sa.Column("accepted", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("unchanged", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        **options,
    )
    op.create_index("ix_runs_started", "ingestion_runs", ["started_at", "id"])


def downgrade():
    op.drop_table("ingestion_runs")
    op.drop_table("opportunities")
    op.drop_table("opportunity_sources")
