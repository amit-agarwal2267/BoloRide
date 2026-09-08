"""Add complete customer identity after resetting prototype business data.

Revision ID: 006
Revises: 005

This destructive cleanup is an explicit Prototype v1 decision because existing
rows contain no real customer data and cannot be truthfully backfilled. It must
not be copied as a production migration strategy.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # rides restrict user deletion; saved places cascade, but explicit deletion
    # makes the intended prototype-only reset order clear and deterministic.
    op.execute("DELETE FROM rides")
    op.execute("DELETE FROM saved_places")
    op.execute("DELETE FROM users")

    op.add_column("users", sa.Column("name", sa.Text(), nullable=False))
    op.add_column("users", sa.Column("normalized_name", sa.Text(), nullable=False))
    op.add_column("users", sa.Column("age", sa.Integer(), nullable=False))
    op.create_check_constraint(
        "ck_users_name_nonempty", "users", "name !~ '^[[:space:]]*$'"
    )
    op.create_check_constraint(
        "ck_users_normalized_name_canonical",
        "users",
        "normalized_name <> '' AND normalized_name = "
        "lower(regexp_replace(btrim(normalized_name), '[[:space:]]+', ' ', 'g'))",
    )
    op.create_check_constraint(
        "ck_users_age_range", "users", "age BETWEEN 1 AND 120"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_age_range", "users", type_="check")
    op.drop_constraint("ck_users_normalized_name_canonical", "users", type_="check")
    op.drop_constraint("ck_users_name_nonempty", "users", type_="check")
    op.drop_column("users", "age")
    op.drop_column("users", "normalized_name")
    op.drop_column("users", "name")
