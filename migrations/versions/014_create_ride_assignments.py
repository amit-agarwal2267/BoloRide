"""Create durable ride assignments.

Revision ID: 014
Revises: 013
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_vehicles_id_driver_id", "vehicles", ["id", "driver_id"]
    )
    op.create_table(
        "ride_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ride_id", sa.UUID(), nullable=False),
        sa.Column("driver_id", sa.UUID(), nullable=False),
        sa.Column("vehicle_id", sa.UUID(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("release_reason", sa.String(16)),
        sa.CheckConstraint(
            "(released_at IS NULL AND release_reason IS NULL) OR "
            "(released_at IS NOT NULL AND release_reason IN ('cancelled', 'completed'))",
            name="ck_ride_assignments_release_pair",
        ),
        sa.ForeignKeyConstraint(["ride_id"], ["rides.id"], name="fk_ride_assignments_ride_id_rides", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], name="fk_ride_assignments_driver_id_drivers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["vehicle_id", "driver_id"], ["vehicles.id", "vehicles.driver_id"],
            name="fk_ride_assignments_vehicle_driver", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ride_assignments"),
        sa.UniqueConstraint("ride_id", name="uq_ride_assignments_ride_id"),
    )
    op.create_index(
        "uq_ride_assignments_active_driver", "ride_assignments", ["driver_id"],
        unique=True, postgresql_where=sa.text("released_at IS NULL"),
    )


def downgrade() -> None:
    existing = op.get_bind().scalar(sa.text("SELECT count(*) FROM ride_assignments"))
    if existing:
        raise RuntimeError(
            "cannot downgrade migration 014 while durable ride assignments exist"
        )
    op.drop_index("uq_ride_assignments_active_driver", table_name="ride_assignments")
    op.drop_table("ride_assignments")
    op.drop_constraint("uq_vehicles_id_driver_id", "vehicles", type_="unique")
