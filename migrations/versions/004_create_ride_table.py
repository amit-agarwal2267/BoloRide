"""Create the rides table.

Revision ID: 004
Revises: 003
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pickup_address", sa.Text(), nullable=False),
        sa.Column("pickup_latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("pickup_longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("destination_address", sa.Text(), nullable=False),
        sa.Column("destination_latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("destination_longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("requested_ride_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="requested", nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("provider_booking_id", sa.String(length=255), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fare_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("fare_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'booked')", name="ck_rides_status"
        ),
        sa.CheckConstraint("pickup_latitude BETWEEN -90 AND 90", name="ck_rides_pickup_latitude"),
        sa.CheckConstraint("pickup_longitude BETWEEN -180 AND 180", name="ck_rides_pickup_longitude"),
        sa.CheckConstraint("destination_latitude BETWEEN -90 AND 90", name="ck_rides_destination_latitude"),
        sa.CheckConstraint("destination_longitude BETWEEN -180 AND 180", name="ck_rides_destination_longitude"),
        sa.CheckConstraint(
            "pickup_latitude <> destination_latitude OR pickup_longitude <> destination_longitude",
            name="ck_rides_distinct_locations",
        ),
        sa.CheckConstraint(
            "(fare_amount IS NULL AND fare_currency IS NULL) OR "
            "(fare_amount > 0 AND fare_currency ~ '^[A-Z]{3}$')",
            name="ck_rides_fare_pair",
        ),
        sa.CheckConstraint(
            "(status = 'requested' AND confirmed_at IS NULL AND provider IS NULL "
            "AND provider_booking_id IS NULL AND booked_at IS NULL "
            "AND fare_amount IS NULL AND fare_currency IS NULL) OR "
            "(status = 'confirmed' AND confirmed_at IS NOT NULL AND provider IS NULL "
            "AND provider_booking_id IS NULL AND booked_at IS NULL "
            "AND fare_amount IS NULL AND fare_currency IS NULL) OR "
            "(status = 'booked' AND confirmed_at IS NOT NULL AND provider IS NOT NULL "
            "AND provider_booking_id IS NOT NULL AND booked_at IS NOT NULL "
            "AND fare_amount IS NOT NULL AND fare_currency IS NOT NULL)",
            name="ck_rides_status_fields",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_rides_user_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rides"),
        sa.UniqueConstraint("provider", "provider_booking_id", name="uq_rides_provider_booking"),
    )


def downgrade() -> None:
    op.drop_table("rides")
