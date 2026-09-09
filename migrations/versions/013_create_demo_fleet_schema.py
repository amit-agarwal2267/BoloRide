"""Create normalized driver and vehicle fleet schema.

Revision ID: 013
Revises: 012
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drivers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "availability",
            sa.Enum(
                "available", "assigned", "on_trip",
                name="driver_availability", native_enum=False, create_constraint=True,
            ),
            server_default="available",
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("seed_version", sa.String(64)),
        sa.Column("seed_key", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("name !~ '^[[:space:]]*$'", name="ck_drivers_name_nonempty"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_drivers_latitude"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_drivers_longitude"),
        sa.CheckConstraint("city !~ '^[[:space:]]*$'", name="ck_drivers_city_nonempty"),
        sa.CheckConstraint("state !~ '^[[:space:]]*$'", name="ck_drivers_state_nonempty"),
        sa.PrimaryKeyConstraint("id", name="pk_drivers"),
        sa.UniqueConstraint("seed_key", name="uq_drivers_seed_key"),
    )
    op.create_index(
        "ix_drivers_dispatch_area", "drivers", ["availability", "state", "city"]
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("driver_id", sa.UUID(), nullable=False),
        sa.Column("vehicle_type_code", sa.String(32), nullable=False),
        sa.Column("registration_number", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], name="fk_vehicles_driver_id_drivers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_type_code"], ["vehicle_types.code"], name="fk_vehicles_vehicle_type_code_vehicle_types", ondelete="RESTRICT"),
        sa.CheckConstraint(
            "registration_number ~ '^(RJ|UP|MP|PB)[0-9]{2}[A-Z]{2}[0-9]{4}$'",
            name="ck_vehicles_synthetic_registration_format",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicles"),
        sa.UniqueConstraint("driver_id", name="uq_vehicles_driver_id"),
        sa.UniqueConstraint("registration_number", name="uq_vehicles_registration_number"),
    )
    op.create_index("ix_vehicles_vehicle_type_code", "vehicles", ["vehicle_type_code"])


def downgrade() -> None:
    op.drop_index("ix_vehicles_vehicle_type_code", table_name="vehicles")
    op.drop_table("vehicles")
    op.drop_index("ix_drivers_dispatch_area", table_name="drivers")
    op.drop_table("drivers")
