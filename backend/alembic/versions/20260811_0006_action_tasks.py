"""add action tasks

Revision ID: 20260811_0006
Revises: 20260810_0005
Create Date: 2026-08-11 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260811_0006"
down_revision: str | Sequence[str] | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("deadline", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('open', 'done', 'snoozed')", name="ck_action_tasks_status"),
        sa.ForeignKeyConstraint(["gmail_account_id", "user_id"], ["gmail_accounts.id", "gmail_accounts.user_id"], name="fk_action_tasks_account_owner", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id", "gmail_account_id", "user_id"], ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"], name="fk_action_tasks_thread_owner", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id", "thread_id", "gmail_account_id", "user_id"], ["gmail_messages.id", "gmail_messages.thread_id", "gmail_messages.gmail_account_id", "gmail_messages.user_id"], name="fk_action_tasks_message_thread_owner", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_action_tasks_message"),
    )
    op.create_index("ix_action_tasks_account_thread_status", "action_tasks", ["gmail_account_id", "thread_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_action_tasks_account_thread_status", table_name="action_tasks")
    op.drop_table("action_tasks")
