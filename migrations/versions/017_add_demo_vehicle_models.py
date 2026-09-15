"""Add an authoritative model name to demo fleet vehicles.

Revision ID: 017
Revises: 016
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "017"
down_revision: str | Sequence[str] | None = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("model_name", sa.String(120)))
    op.execute(
        """
        UPDATE vehicles
        SET model_name = CASE vehicle_type_code
            WHEN 'auto' THEN 'Bajaj RE'
            WHEN 'mini' THEN 'Maruti Suzuki Wagon R'
            WHEN 'sedan' THEN 'Maruti Suzuki Dzire'
            WHEN 'suv' THEN 'Toyota Innova'
            WHEN 'premium' THEN 'Honda City'
            ELSE 'Demo Vehicle'
        END
        """
    )
    op.alter_column("vehicles", "model_name", nullable=False)
    op.create_check_constraint(
        "ck_vehicles_model_name_nonempty",
        "vehicles",
        "model_name !~ '^[[:space:]]*$'",
    )
    op.add_column(
        "ride_assignments",
        sa.Column("eta_minutes", sa.Integer(), nullable=True),
    )
    # Existing prototype assignments predate persisted ETA. Five minutes was
    # the former mock-provider value, so preserve that historical behavior.
    op.execute("UPDATE ride_assignments SET eta_minutes = 5")
    op.alter_column("ride_assignments", "eta_minutes", nullable=False)
    op.create_check_constraint(
        "ck_ride_assignments_eta_minutes",
        "ride_assignments",
        "eta_minutes BETWEEN 1 AND 120",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ride_assignments_eta_minutes", "ride_assignments", type_="check"
    )
    op.drop_column("ride_assignments", "eta_minutes")
    op.drop_constraint(
        "ck_vehicles_model_name_nonempty", "vehicles", type_="check"
    )
    op.drop_column("vehicles", "model_name")
