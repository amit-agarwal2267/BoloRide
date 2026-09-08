"""Create versioned pricing rules and immutable accepted quote snapshots.

Revision ID: 009
Revises: 008
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pricing_rules = op.create_table(
        "pricing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_type_code", sa.String(32), nullable=False),
        sa.Column("base_fare", sa.Numeric(10, 2), nullable=False),
        sa.Column("per_km_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("night_charge", sa.Numeric(10, 2), nullable=False),
        sa.Column("airport_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("base_fare >= 0", name="ck_pricing_rules_base_fare"),
        sa.CheckConstraint("per_km_rate >= 0", name="ck_pricing_rules_per_km_rate"),
        sa.CheckConstraint("night_charge >= 0", name="ck_pricing_rules_night_charge"),
        sa.CheckConstraint("airport_fee >= 0", name="ck_pricing_rules_airport_fee"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_pricing_rules_currency"),
        sa.ForeignKeyConstraint(["vehicle_type_code"], ["vehicle_types.code"], name="fk_pricing_rules_vehicle_type", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_pricing_rules"),
    )
    op.create_index(
        "uq_pricing_rules_active_vehicle", "pricing_rules", ["vehicle_type_code"],
        unique=True, postgresql_where=sa.text("active")
    )
    rows = [
        ("00000000-0000-4000-8000-000000000001", "auto", "30.00", "10.00", "50.00"),
        ("00000000-0000-4000-8000-000000000002", "mini", "40.00", "12.00", "100.00"),
        ("00000000-0000-4000-8000-000000000003", "sedan", "50.00", "14.00", "150.00"),
        ("00000000-0000-4000-8000-000000000004", "suv", "70.00", "18.00", "200.00"),
        ("00000000-0000-4000-8000-000000000005", "premium", "90.00", "22.00", "250.00"),
    ]
    op.bulk_insert(pricing_rules, [
        {"id": rule_id, "vehicle_type_code": code, "base_fare": base,
         "per_km_rate": rate, "night_charge": night, "airport_fee": "150.00",
         "currency": "INR", "active": True}
        for rule_id, code, base, rate, night in rows
    ])

    op.create_table(
        "accepted_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ride_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pricing_rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_type_code", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("route_provider", sa.String(50), nullable=False),
        sa.Column("route_distance_meters", sa.Integer(), nullable=False),
        sa.Column("route_duration_seconds", sa.Integer()),
        sa.Column("base_fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("distance_fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("night_charge", sa.Numeric(12, 2), nullable=False),
        sa.Column("airport_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("toll_estimate", sa.Numeric(12, 2)),
        sa.Column("toll_status", sa.String(32), nullable=False),
        sa.Column("estimated_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("quoted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("route_distance_meters >= 0", name="ck_accepted_quotes_distance"),
        sa.CheckConstraint("route_duration_seconds IS NULL OR route_duration_seconds >= 0", name="ck_accepted_quotes_duration"),
        sa.CheckConstraint("base_fare >= 0 AND distance_fare >= 0 AND night_charge >= 0 AND airport_fee >= 0 AND estimated_total >= 0", name="ck_accepted_quotes_amounts"),
        sa.CheckConstraint("toll_estimate IS NULL OR toll_estimate >= 0", name="ck_accepted_quotes_toll"),
        sa.CheckConstraint("toll_status IN ('estimate_available', 'may_apply', 'no_toll', 'unknown')", name="ck_accepted_quotes_toll_status"),
        sa.CheckConstraint("(toll_status = 'estimate_available') = (toll_estimate IS NOT NULL)", name="ck_accepted_quotes_toll_pair"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_accepted_quotes_currency"),
        sa.CheckConstraint("request_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_accepted_quotes_fingerprint"),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_accepted_quotes_ride", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_accepted_quotes"),
        sa.UniqueConstraint("ride_id", name="uq_accepted_quotes_ride_id"),
    )


def downgrade() -> None:
    op.drop_table("accepted_quotes")
    op.drop_index("uq_pricing_rules_active_vehicle", table_name="pricing_rules")
    op.drop_table("pricing_rules")
