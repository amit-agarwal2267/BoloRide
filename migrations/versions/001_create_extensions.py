"""Record the initial PostgreSQL extension decision.

Revision ID: 001
Revises:

No extension is currently required. In particular, pgvector is not justified
without a vector-search use case, and UUID extensions are not needed before an
identifier strategy and tables have been approved.
"""

from collections.abc import Sequence

revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Intentionally enable no PostgreSQL extensions."""


def downgrade() -> None:
    """No extensions were created, so there is nothing to remove."""
