from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GmailThread(Base):
    """An account-scoped Gmail conversation thread."""

    __tablename__ = "gmail_threads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_threads_account_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("gmail_account_id", "gmail_thread_id", name="uq_threads_account_gmail_id"),
        UniqueConstraint("id", "gmail_account_id", "user_id", name="uq_threads_id_account_user"),
        Index("ix_threads_account_latest", "gmail_account_id", "latest_message_at"),
        Index("ix_threads_user_account_inbox_latest", "user_id", "gmail_account_id", "is_in_inbox", "latest_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_normalized: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_in_inbox: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class GmailMessage(Base):
    """An account-scoped Gmail message belonging to one internal thread."""

    __tablename__ = "gmail_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_messages_account_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_messages_thread_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("gmail_account_id", "gmail_message_id", name="uq_messages_account_gmail_id"),
        UniqueConstraint(
            "id", "thread_id", "gmail_account_id", "user_id", name="uq_messages_id_thread_account_user"
        ),
        Index("ix_messages_thread_date", "thread_id", "gmail_internal_date"),
        Index("ix_messages_account_date", "gmail_account_id", "gmail_internal_date"),
        Index("ix_messages_account_sender", "gmail_account_id", "from_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    gmail_internal_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    from_address: Mapped[str] = mapped_column(String(320), nullable=False)
    to_addresses: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cc_addresses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Classification(Base):
    """Historical thread-level classification; only one result is current per thread."""

    __tablename__ = "classifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_classifications_account_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_classifications_thread_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "gmail_account_id", "user_id", name="uq_classifications_id_account_user"),
        Index(
            "uq_current_classification_per_thread",
            "thread_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_classifications_account_current_priority", "gmail_account_id", "is_current", "priority_score"),
        Index("ix_classifications_account_current_category", "gmail_account_id", "is_current", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    explanation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(128), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FeedbackEvent(Base):
    """Append-only account-scoped user feedback and preference history."""

    __tablename__ = "feedback_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_feedback_account_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_feedback_thread_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
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
        ForeignKeyConstraint(
            ["classification_id", "gmail_account_id", "user_id"],
            ["classifications.id", "classifications.gmail_account_id", "classifications.user_id"],
            name="fk_feedback_classification_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint("message_id IS NULL OR thread_id IS NOT NULL", name="ck_feedback_message_requires_thread"),
        Index("ix_feedback_account_thread_created", "gmail_account_id", "thread_id", "created_at"),
        Index("ix_feedback_account_type_created", "gmail_account_id", "feedback_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    classification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Recommendation(Base):
    """An account-scoped, read-only recommendation for a Gmail thread."""

    __tablename__ = "recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_recommendations_account_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["thread_id", "gmail_account_id", "user_id"],
            ["gmail_threads.id", "gmail_threads.gmail_account_id", "gmail_threads.user_id"],
            name="fk_recommendations_thread_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["classification_id", "gmail_account_id", "user_id"],
            ["classifications.id", "classifications.gmail_account_id", "classifications.user_id"],
            name="fk_recommendations_classification_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_active_recommendation_per_thread_type",
            "thread_id",
            "recommendation_type",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_recommendations_account_status_created", "gmail_account_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    classification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SyncRun(Base):
    """Operational history for one account-scoped synchronization attempt."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_sync_runs_account_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint("completed_at IS NULL OR completed_at >= started_at", name="ck_sync_runs_completion"),
        Index("ix_sync_runs_account_started", "gmail_account_id", "started_at"),
        Index("ix_sync_runs_account_status_started", "gmail_account_id", "status", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    messages_examined: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    messages_imported: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    threads_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
