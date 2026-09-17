"""Create demo access requests.

Revision ID: 018
Revises: 017
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "018"
down_revision: str | Sequence[str] | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_access_requests",

        sa.Column(
            "auth_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),

        sa.Column(
            "email",
            sa.String(length=320),
            nullable=False,
        ),

        sa.Column(
            "access_granted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),

        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),

        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),

        sa.PrimaryKeyConstraint(
            "auth_user_id",
            name="pk_demo_access_requests",
        ),

        sa.CheckConstraint(
            """
            (
                access_granted = false
                AND granted_at IS NULL
            )
            OR
            (
                access_granted = true
                AND granted_at IS NOT NULL
            )
            """,
            name="ck_demo_access_requests_grant_state",
        ),
    )

    op.create_index(
        "ix_demo_access_requests_waitlist",
        "demo_access_requests",
        ["requested_at", "auth_user_id"],
        unique=False,
        postgresql_where=sa.text("access_granted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_demo_access_requests_waitlist",
        table_name="demo_access_requests",
    )

    op.drop_table("demo_access_requests")