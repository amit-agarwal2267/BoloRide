"""Create persistent demo phone leases.

Revision ID: 019
Revises: 018
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "019"
down_revision: str | Sequence[str] | None = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_phone_leases",
        sa.Column("auth_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number", sa.String(length=16), nullable=False),
        sa.Column("active_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_call_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("auth_user_id", name="pk_demo_phone_leases"),
        sa.UniqueConstraint("phone_number", name="uq_demo_phone_leases_phone"),
        sa.CheckConstraint(
            "phone_number ~ '^\\+91[6-9][0-9]{9}$'",
            name="ck_demo_phone_leases_indian_mobile",
        ),
        sa.CheckConstraint(
            "(active_call_id IS NULL AND active_call_expires_at IS NULL) OR "
            "(active_call_id IS NOT NULL AND active_call_expires_at IS NOT NULL)",
            name="ck_demo_phone_leases_call_pair",
        ),
    )


def downgrade() -> None:
    op.drop_table("demo_phone_leases")
