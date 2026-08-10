"""add classification feedback

Revision ID: 20260810_0005
Revises: 20260807_0004
Create Date: 2026-08-10 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260810_0005"
down_revision: str | Sequence[str] | None = "20260807_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classification_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_category", sa.String(length=64), nullable=False),
        sa.Column("corrected_category", sa.String(length=64), nullable=False),
        sa.Column("classifier_version", sa.String(length=128), nullable=False),
        sa.Column("sender_address", sa.String(length=320), nullable=False),
        sa.Column("sender_domain", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["gmail_account_id", "user_id"], ["gmail_accounts.id", "gmail_accounts.user_id"], name="fk_classification_feedback_account_owner", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id", "gmail_account_id", "user_id"], ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"], name="fk_classification_feedback_thread_owner", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id", "thread_id", "gmail_account_id", "user_id"], ["gmail_messages.id", "gmail_messages.thread_id", "gmail_messages.gmail_account_id", "gmail_messages.user_id"], name="fk_classification_feedback_message_thread_owner", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "thread_id", "original_category", "corrected_category", name="uq_classification_feedback_thread_correction"),
    )
    op.create_index("ix_classification_feedback_sender", "classification_feedback", ["user_id", "gmail_account_id", "sender_domain"])


def downgrade() -> None:
    op.drop_index("ix_classification_feedback_sender", table_name="classification_feedback")
    op.drop_table("classification_feedback")
