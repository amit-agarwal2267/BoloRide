"""Add optional driver-facing pickup instructions.

Revision ID: 016
Revises: 015
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rides",
        sa.Column("pickup_instructions", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rides", "pickup_instructions")
