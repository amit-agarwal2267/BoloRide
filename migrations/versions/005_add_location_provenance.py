"""Add provider-neutral location metadata.

Revision ID: 005
Revises: 004
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: str | Sequence[str] | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("saved_places", sa.Column("display_name", sa.String(255)))
    op.add_column("saved_places", sa.Column("provider", sa.String(50)))
    op.add_column("saved_places", sa.Column("provider_place_id", sa.String(255)))

    op.add_column("rides", sa.Column("pickup_display_name", sa.String(255)))
    op.add_column("rides", sa.Column("pickup_provider", sa.String(50)))
    op.add_column("rides", sa.Column("pickup_provider_place_id", sa.String(255)))
    op.add_column("rides", sa.Column("destination_display_name", sa.String(255)))
    op.add_column("rides", sa.Column("destination_provider", sa.String(50)))
    op.add_column(
        "rides", sa.Column("destination_provider_place_id", sa.String(255))
    )


def downgrade() -> None:
    op.drop_column("rides", "destination_provider_place_id")
    op.drop_column("rides", "destination_provider")
    op.drop_column("rides", "destination_display_name")
    op.drop_column("rides", "pickup_provider_place_id")
    op.drop_column("rides", "pickup_provider")
    op.drop_column("rides", "pickup_display_name")
    op.drop_column("saved_places", "provider_place_id")
    op.drop_column("saved_places", "provider")
    op.drop_column("saved_places", "display_name")