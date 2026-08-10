"""add M5 classification context

Revision ID: 20260807_0004
Revises: 20260807_0003
Create Date: 2026-08-07 00:00:02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260807_0004"
down_revision: str | Sequence[str] | None = "20260807_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gmail_messages",
        sa.Column(
            "delivery_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint("ck_classifications_priority_range", "classifications", "priority_score BETWEEN 0 AND 100")
    op.create_check_constraint("ck_classifications_confidence_range", "classifications", "confidence BETWEEN 0 AND 1")


def downgrade() -> None:
    op.drop_constraint("ck_classifications_confidence_range", "classifications", type_="check")
    op.drop_constraint("ck_classifications_priority_range", "classifications", type_="check")
    op.drop_column("gmail_messages", "delivery_metadata")
