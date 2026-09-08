"""Align rides with the durable Prototype v1 lifecycle.

Revision ID: 007
Revises: 006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM rides WHERE status IN ('requested', 'confirmed')
            ) THEN
                RAISE EXCEPTION
                    'migration 007 cannot reinterpret requested or confirmed rides';
            END IF;
        END $$
        """
    )
    op.drop_constraint("ck_rides_status_fields", "rides", type_="check")
    op.drop_constraint("ck_rides_status", "rides", type_="check")
    op.alter_column("rides", "status", server_default="booked")
    op.create_check_constraint(
        "ck_rides_status",
        "rides",
        "status IN ('booked', 'assigned', 'on_trip', 'completed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_rides_status_fields",
        "rides",
        "confirmed_at IS NOT NULL AND provider IS NOT NULL "
        "AND provider_booking_id IS NOT NULL AND booked_at IS NOT NULL "
        "AND fare_amount IS NOT NULL AND fare_currency IS NOT NULL",
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM rides
                WHERE status IN ('assigned', 'on_trip', 'completed', 'cancelled')
            ) THEN
                RAISE EXCEPTION
                    'migration 007 downgrade cannot reinterpret durable ride states';
            END IF;
        END $$
        """
    )
    op.drop_constraint("ck_rides_status_fields", "rides", type_="check")
    op.drop_constraint("ck_rides_status", "rides", type_="check")
    op.alter_column("rides", "status", server_default="requested")
    op.create_check_constraint(
        "ck_rides_status",
        "rides",
        "status IN ('requested', 'confirmed', 'booked')",
    )
    op.create_check_constraint(
        "ck_rides_status_fields",
        "rides",
        "(status = 'requested' AND confirmed_at IS NULL AND provider IS NULL "
        "AND provider_booking_id IS NULL AND booked_at IS NULL "
        "AND fare_amount IS NULL AND fare_currency IS NULL) OR "
        "(status = 'confirmed' AND confirmed_at IS NOT NULL AND provider IS NULL "
        "AND provider_booking_id IS NULL AND booked_at IS NULL "
        "AND fare_amount IS NULL AND fare_currency IS NULL) OR "
        "(status = 'booked' AND confirmed_at IS NOT NULL AND provider IS NOT NULL "
        "AND provider_booking_id IS NOT NULL AND booked_at IS NOT NULL "
        "AND fare_amount IS NOT NULL AND fare_currency IS NOT NULL)",
    )
