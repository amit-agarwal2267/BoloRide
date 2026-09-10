"""Enforce one active ride per customer.

Revision ID: 015
Revises: 014
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    duplicate_customer = op.get_bind().scalar(
        sa.text(
            "SELECT user_id FROM rides "
            "WHERE status IN ('booked', 'assigned', 'on_trip') "
            "GROUP BY user_id HAVING count(*) > 1 LIMIT 1"
        )
    )
    if duplicate_customer is not None:
        raise RuntimeError(
            "cannot enforce one active ride per customer while duplicate active rides exist"
        )
    op.create_index(
        "uq_rides_one_active_per_customer",
        "rides",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('booked', 'assigned', 'on_trip')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_rides_one_active_per_customer", table_name="rides")
