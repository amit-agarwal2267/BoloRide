"""Create the saved_places table.

Revision ID: 003
Revises: 002
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_places",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=50), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "label = lower(btrim(label))", name="ck_saved_places_label_normalized"
        ),
        sa.CheckConstraint(
            "latitude BETWEEN -90 AND 90", name="ck_saved_places_latitude"
        ),
        sa.CheckConstraint(
            "longitude BETWEEN -180 AND 180", name="ck_saved_places_longitude"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_saved_places_user_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_saved_places"),
        sa.UniqueConstraint("user_id", "label", name="uq_saved_places_user_label"),
    )


def downgrade() -> None:
    op.drop_table("saved_places")
