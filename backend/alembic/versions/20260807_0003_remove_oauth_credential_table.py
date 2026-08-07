"""remove OAuth credential metadata table

Revision ID: 20260807_0003
Revises: 20260804_0002
Create Date: 2026-08-07 00:00:01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260807_0003"
down_revision: str | Sequence[str] | None = "20260804_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("gmail_oauth_credentials")


def downgrade() -> None:
    # Credentials intentionally remain Keychain-only; downgrade cannot recreate token metadata.
    pass
