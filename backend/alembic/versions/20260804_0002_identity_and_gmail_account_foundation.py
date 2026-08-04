"""identity and Gmail account foundation

Revision ID: 20260804_0002
Revises: 20260804_0001
Create Date: 2026-08-04 00:00:01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260804_0002"
down_revision: str | Sequence[str] | None = "20260804_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )
    op.create_table(
        "gmail_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_email", sa.String(length=320), nullable=False),
        sa.Column("gmail_email_normalized", sa.String(length=320), nullable=False),
        sa.Column("gmail_profile_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_gmail_accounts_id_user"),
        sa.UniqueConstraint("user_id", "gmail_email_normalized", name="uq_gmail_accounts_user_email"),
        sa.UniqueConstraint("user_id", "gmail_profile_id", name="uq_gmail_accounts_user_profile"),
    )
    op.create_index("ix_gmail_accounts_user_status", "gmail_accounts", ["user_id", "status"])
    op.create_index(
        "ix_gmail_accounts_user_last_sync", "gmail_accounts", ["user_id", "last_successful_sync_at"]
    )
    op.create_table(
        "gmail_oauth_credentials",
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_store", sa.String(length=64), server_default="macos_keychain", nullable=False),
        sa.Column("credential_reference", sa.String(length=512), nullable=False),
        sa.Column("granted_scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("credential_status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("credential_store = 'macos_keychain'", name="ck_oauth_credentials_v1_keychain_only"),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_oauth_credentials_account_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("gmail_account_id"),
        sa.UniqueConstraint("credential_store", "credential_reference", name="uq_oauth_credential_reference"),
    )
    op.create_table(
        "gmail_sync_states",
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("history_id", sa.String(length=255), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=128), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_sync_states_account_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("gmail_account_id"),
    )
    op.create_table(
        "gmail_threads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_thread_id", sa.String(length=255), nullable=False),
        sa.Column("subject_normalized", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("latest_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_in_inbox", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_unread", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_threads_account_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gmail_account_id", "gmail_thread_id", name="uq_threads_account_gmail_id"),
        sa.UniqueConstraint("id", "gmail_account_id", "user_id", name="uq_threads_id_account_user"),
    )
    op.create_index("ix_threads_account_latest", "gmail_threads", ["gmail_account_id", "latest_message_at"])
    op.create_index(
        "ix_threads_user_account_inbox_latest",
        "gmail_threads",
        ["user_id", "gmail_account_id", "is_in_inbox", "latest_message_at"],
    )
    op.create_table(
        "gmail_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_message_id", sa.String(length=255), nullable=False),
        sa.Column("gmail_internal_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_address", sa.String(length=320), nullable=False),
        sa.Column("to_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc_addresses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("label_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("has_attachments", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_messages_account_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_messages_thread_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gmail_account_id", "gmail_message_id", name="uq_messages_account_gmail_id"),
        sa.UniqueConstraint("id", "thread_id", "gmail_account_id", "user_id", name="uq_messages_id_thread_account_user"),
    )
    op.create_index("ix_messages_thread_date", "gmail_messages", ["thread_id", "gmail_internal_date"])
    op.create_index("ix_messages_account_date", "gmail_messages", ["gmail_account_id", "gmail_internal_date"])
    op.create_index("ix_messages_account_sender", "gmail_messages", ["gmail_account_id", "from_address"])
    op.create_table(
        "classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("classifier_version", sa.String(length=128), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_classifications_account_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_classifications_thread_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "gmail_account_id", "user_id", name="uq_classifications_id_account_user"),
    )
    op.create_index(
        "uq_current_classification_per_thread",
        "classifications",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_classifications_account_current_priority",
        "classifications",
        ["gmail_account_id", "is_current", "priority_score"],
    )
    op.create_index(
        "ix_classifications_account_current_category",
        "classifications",
        ["gmail_account_id", "is_current", "category"],
    )
    op.create_table(
        "feedback_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("classification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("feedback_type", sa.String(length=64), nullable=False),
        sa.Column("previous_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("message_id IS NULL OR thread_id IS NOT NULL", name="ck_feedback_message_requires_thread"),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_feedback_account_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_feedback_thread_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "thread_id", "gmail_account_id", "user_id"],
            [
                "gmail_messages.id",
                "gmail_messages.thread_id",
                "gmail_messages.gmail_account_id",
                "gmail_messages.user_id",
            ],
            name="fk_feedback_message_thread_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["classification_id", "gmail_account_id", "user_id"],
            ["classifications.id", "classifications.gmail_account_id", "classifications.user_id"],
            name="fk_feedback_classification_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_account_thread_created", "feedback_events", ["gmail_account_id", "thread_id", "created_at"])
    op.create_index("ix_feedback_account_type_created", "feedback_events", ["gmail_account_id", "feedback_type", "created_at"])
    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("classification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_type", sa.String(length=64), nullable=False),
        sa.Column("rationale", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_recommendations_account_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_recommendations_thread_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["classification_id", "gmail_account_id", "user_id"],
            ["classifications.id", "classifications.gmail_account_id", "classifications.user_id"],
            name="fk_recommendations_classification_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_active_recommendation_per_thread_type",
        "recommendations",
        ["thread_id", "recommendation_type"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_recommendations_account_status_created", "recommendations", ["gmail_account_id", "status", "created_at"]
    )
    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gmail_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("messages_examined", sa.Integer(), server_default="0", nullable=False),
        sa.Column("messages_imported", sa.Integer(), server_default="0", nullable=False),
        sa.Column("threads_updated", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="ck_sync_runs_completion"),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_sync_runs_account_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sync_runs_account_started", "sync_runs", ["gmail_account_id", "started_at"])
    op.create_index(
        "ix_sync_runs_account_status_started", "sync_runs", ["gmail_account_id", "status", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sync_runs_account_status_started", table_name="sync_runs")
    op.drop_index("ix_sync_runs_account_started", table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index("ix_recommendations_account_status_created", table_name="recommendations")
    op.drop_index("uq_active_recommendation_per_thread_type", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_feedback_account_type_created", table_name="feedback_events")
    op.drop_index("ix_feedback_account_thread_created", table_name="feedback_events")
    op.drop_table("feedback_events")
    op.drop_index("ix_classifications_account_current_category", table_name="classifications")
    op.drop_index("ix_classifications_account_current_priority", table_name="classifications")
    op.drop_index("uq_current_classification_per_thread", table_name="classifications")
    op.drop_table("classifications")
    op.drop_index("ix_messages_account_sender", table_name="gmail_messages")
    op.drop_index("ix_messages_account_date", table_name="gmail_messages")
    op.drop_index("ix_messages_thread_date", table_name="gmail_messages")
    op.drop_table("gmail_messages")
    op.drop_index("ix_threads_user_account_inbox_latest", table_name="gmail_threads")
    op.drop_index("ix_threads_account_latest", table_name="gmail_threads")
    op.drop_table("gmail_threads")
    op.drop_table("gmail_sync_states")
    op.drop_table("gmail_oauth_credentials")
    op.drop_index("ix_gmail_accounts_user_last_sync", table_name="gmail_accounts")
    op.drop_index("ix_gmail_accounts_user_status", table_name="gmail_accounts")
    op.drop_table("gmail_accounts")
    op.drop_table("users")
