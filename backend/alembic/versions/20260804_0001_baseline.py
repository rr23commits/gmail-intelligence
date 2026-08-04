"""baseline

Revision ID: 20260804_0001
Revises:
Create Date: 2026-08-04 00:00:00

Milestone 1 deliberately creates no application tables. The baseline records
that all subsequent schema changes must be performed through Alembic.
"""

revision: str = "20260804_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
