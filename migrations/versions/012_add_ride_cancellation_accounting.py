"""Add final customer cost accounting for pre-trip cancellation.

Revision ID: 012
Revises: 011
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: str | Sequence[str] | None = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rides", sa.Column("final_customer_cost", sa.Numeric(12, 2)))
    # Prototype v1 defines every successful pre-trip cancellation as zero cost.
    # This deterministic backfill does not alter the immutable accepted quote.
    op.execute(
        "UPDATE rides SET final_customer_cost = 0.00 WHERE status = 'cancelled'"
    )
    op.create_check_constraint(
        "ck_rides_final_customer_cost_nonnegative",
        "rides",
        "final_customer_cost IS NULL OR final_customer_cost >= 0",
    )
    op.create_check_constraint(
        "ck_rides_cancelled_zero_cost",
        "rides",
        "status <> 'cancelled' OR "
        "(final_customer_cost IS NOT NULL AND final_customer_cost = 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_rides_cancelled_zero_cost", "rides", type_="check")
    op.drop_constraint(
        "ck_rides_final_customer_cost_nonnegative", "rides", type_="check"
    )
    op.drop_column("rides", "final_customer_cost")
