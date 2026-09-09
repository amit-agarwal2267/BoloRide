"""Create dynamic offers, accepted snapshots, and redemption lifecycle.

Revision ID: 010
Revises: 009
"""
from collections.abc import Sequence
from datetime import UTC, datetime
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    offers = op.create_table(
        "offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("discount_type", sa.String(32), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("maximum_discount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("maximum_redemptions_per_customer", sa.Integer(), nullable=False),
        sa.Column("eligibility_type", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]*$'", name="ck_offers_code"),
        sa.CheckConstraint("display_name !~ '^[[:space:]]*$'", name="ck_offers_name"),
        sa.CheckConstraint("discount_type = 'percentage'", name="ck_offers_discount_type"),
        sa.CheckConstraint("percentage > 0 AND percentage <= 100", name="ck_offers_percentage"),
        sa.CheckConstraint("maximum_discount >= 0", name="ck_offers_maximum_discount"),
        sa.CheckConstraint("currency = 'INR'", name="ck_offers_currency"),
        sa.CheckConstraint("maximum_redemptions_per_customer > 0", name="ck_offers_redemption_limit"),
        sa.CheckConstraint("eligibility_type = 'new_customer'", name="ck_offers_eligibility_type"),
        sa.CheckConstraint("effective_until IS NULL OR effective_until > effective_from", name="ck_offers_effective_period"),
        sa.CheckConstraint("version > 0", name="ck_offers_version"),
        sa.PrimaryKeyConstraint("id", name="pk_offers"),
        sa.UniqueConstraint("code", name="uq_offers_code"),
    )
    op.bulk_insert(offers, [{
        "id": "00000000-0000-4000-8000-000000000101", "code": "NEW_CUSTOMER",
        "display_name": "New Customer Offer", "discount_type": "percentage",
        "percentage": "10.00", "maximum_discount": "50.00", "currency": "INR",
        "maximum_redemptions_per_customer": 3, "eligibility_type": "new_customer",
        "active": True, "effective_from": datetime(2026, 1, 1, tzinfo=UTC), "version": 1,
    }])
    for column in (
        sa.Column("pre_discount_estimated_total", sa.Numeric(12, 2)),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True)),
        sa.Column("offer_code", sa.String(64)),
        sa.Column("offer_display_name", sa.String(160)),
        sa.Column("offer_discount_type", sa.String(32)),
        sa.Column("offer_percentage", sa.Numeric(5, 2)),
        sa.Column("offer_maximum_discount", sa.Numeric(12, 2)),
        sa.Column("offer_discount_amount", sa.Numeric(12, 2)),
        sa.Column("offer_currency", sa.String(3)),
        sa.Column("offer_version", sa.Integer()),
    ):
        op.add_column("accepted_quotes", column)
    op.create_check_constraint(
        "ck_accepted_quotes_offer_snapshot", "accepted_quotes",
        "(offer_id IS NULL AND offer_code IS NULL AND offer_display_name IS NULL AND offer_discount_type IS NULL AND offer_percentage IS NULL AND offer_maximum_discount IS NULL AND offer_discount_amount IS NULL AND offer_currency IS NULL AND offer_version IS NULL) OR "
        "(offer_id IS NOT NULL AND offer_code IS NOT NULL AND offer_display_name IS NOT NULL AND offer_discount_type = 'percentage' AND offer_percentage > 0 AND offer_percentage <= 100 AND offer_maximum_discount >= 0 AND offer_discount_amount >= 0 AND offer_currency = currency AND offer_version > 0 AND pre_discount_estimated_total IS NOT NULL AND estimated_total = round(pre_discount_estimated_total - offer_discount_amount, 0))"
    )
    op.create_table(
        "offer_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ride_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'consumed', 'cancelled')", name="ck_offer_redemptions_status"),
        sa.CheckConstraint("(status = 'consumed') = (consumed_at IS NOT NULL)", name="ck_offer_redemptions_consumed_at"),
        sa.ForeignKeyConstraint(["offer_id"], ["offers.id"], name="fk_offer_redemptions_offer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name="fk_offer_redemptions_customer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_offer_redemptions_ride", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["accepted_quote_id"], ["accepted_quotes.id"], name="fk_offer_redemptions_quote", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_offer_redemptions"),
        sa.UniqueConstraint("ride_id", name="uq_offer_redemptions_ride"),
        sa.UniqueConstraint("accepted_quote_id", name="uq_offer_redemptions_quote"),
    )
    op.create_index("ix_offer_redemptions_capacity", "offer_redemptions", ["customer_id", "offer_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_offer_redemptions_capacity", table_name="offer_redemptions")
    op.drop_table("offer_redemptions")
    op.drop_constraint("ck_accepted_quotes_offer_snapshot", "accepted_quotes", type_="check")
    for name in ("offer_version", "offer_currency", "offer_discount_amount", "offer_maximum_discount", "offer_percentage", "offer_discount_type", "offer_display_name", "offer_code", "offer_id", "pre_discount_estimated_total"):
        op.drop_column("accepted_quotes", name)
    op.drop_table("offers")
