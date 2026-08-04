from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.user import User


class GmailAccount(Base):
    """One independently authorized Gmail mailbox owned by one application user."""

    __tablename__ = "gmail_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_email_normalized", name="uq_gmail_accounts_user_email"),
        UniqueConstraint("user_id", "gmail_profile_id", name="uq_gmail_accounts_user_profile"),
        UniqueConstraint("id", "user_id", name="uq_gmail_accounts_id_user"),
        Index("ix_gmail_accounts_user_status", "user_id", "status"),
        Index("ix_gmail_accounts_user_last_sync", "user_id", "last_successful_sync_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_email: Mapped[str] = mapped_column(String(320), nullable=False)
    gmail_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    gmail_profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="gmail_accounts")


class GmailOAuthCredential(Base):
    """Non-secret OAuth metadata and a reference to a Keychain credential item."""

    __tablename__ = "gmail_oauth_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_oauth_credentials_account_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint("credential_store", "credential_reference", name="uq_oauth_credential_reference"),
        CheckConstraint(
            "credential_store = 'macos_keychain'", name="ck_oauth_credentials_v1_keychain_only"
        ),
    )

    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    credential_store: Mapped[str] = mapped_column(String(64), nullable=False, server_default="macos_keychain")
    credential_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    credential_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class GmailSyncState(Base):
    """Per-account incremental synchronization checkpoint; sync behavior comes later."""

    __tablename__ = "gmail_sync_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_sync_states_account_owner",
            ondelete="CASCADE",
        ),
    )

    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    history_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
