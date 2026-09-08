"""Create and seed the Prototype v1 vehicle type catalog.

Revision ID: 008
Revises: 007
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    vehicle_types = op.create_table(
        "vehicle_types",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("passenger_capacity", sa.Integer(), nullable=False),
        sa.Column(
            "active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]*$'", name="ck_vehicle_types_code_format"
        ),
        sa.CheckConstraint(
            "display_name !~ '^[[:space:]]*$'",
            name="ck_vehicle_types_display_name_nonempty",
        ),
        sa.CheckConstraint(
            "passenger_capacity > 0",
            name="ck_vehicle_types_passenger_capacity_positive",
        ),
        sa.PrimaryKeyConstraint("code", name="pk_vehicle_types"),
    )
    op.bulk_insert(
        vehicle_types,
        [
            {
                "code": "auto",
                "display_name": "Auto",
                "passenger_capacity": 3,
                "active": True,
            },
            {
                "code": "mini",
                "display_name": "Mini",
                "passenger_capacity": 4,
                "active": True,
            },
            {
                "code": "sedan",
                "display_name": "Sedan",
                "passenger_capacity": 4,
                "active": True,
            },
            {
                "code": "suv",
                "display_name": "SUV",
                "passenger_capacity": 6,
                "active": True,
            },
            {
                "code": "premium",
                "display_name": "Premium Cab",
                "passenger_capacity": 4,
                "active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("vehicle_types")
