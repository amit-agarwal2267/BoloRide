"""Create durable provider booking attempts and recovery snapshots.

Revision ID: 011
Revises: 010
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_idempotency_key", sa.String(255), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("authorized_quote_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider_call_started_at", sa.DateTime(timezone=True)),
        sa.Column("provider_booking_id", sa.String(255)),
        sa.Column("provider_result_snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("failure_category", sa.String(64)),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True)),
        sa.Column("capacity_reserved", sa.Boolean(), nullable=False),
        sa.Column("ride_id", postgresql.UUID(as_uuid=True)),
        sa.Column("reconciliation_count", sa.Integer(), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("state IN ('ready','provider_calling','provider_confirmed','finalized','definitively_failed','outcome_unknown','requote_required')", name="ck_booking_attempts_state"),
        sa.CheckConstraint("snapshot_version = 1", name="ck_booking_attempts_snapshot_version"),
        sa.CheckConstraint("request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_booking_attempts_fingerprint"),
        sa.CheckConstraint("NOT capacity_reserved OR offer_id IS NOT NULL", name="ck_booking_attempts_capacity_offer"),
        sa.CheckConstraint("(provider_booking_id IS NULL AND provider_result_snapshot IS NULL) OR (provider_booking_id IS NOT NULL AND provider_result_snapshot IS NOT NULL)", name="ck_booking_attempts_provider_result"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name="fk_booking_attempts_customer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], name="fk_booking_attempts_offer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_booking_attempts_ride", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_booking_attempts"),
        sa.UniqueConstraint("quote_id", name="uq_booking_attempts_quote"),
        sa.UniqueConstraint("provider_idempotency_key", name="uq_booking_attempts_idempotency_key"),
        sa.UniqueConstraint("ride_id", name="uq_booking_attempts_ride"),
        sa.UniqueConstraint("provider", "provider_booking_id", name="uq_booking_attempts_provider_booking"),
    )
    op.create_index(
        "ix_booking_attempts_offer_capacity",
        "booking_attempts",
        ["customer_id", "offer_id", "capacity_reserved"],
        postgresql_where=sa.text("capacity_reserved"),
    )


def downgrade() -> None:
    # Stage 6 attempts are operational recovery metadata only. Removing them does
    # not reinterpret or rewrite any finalized Stage 1-5 business records.
    op.drop_index("ix_booking_attempts_offer_capacity", table_name="booking_attempts")
    op.drop_table("booking_attempts")
