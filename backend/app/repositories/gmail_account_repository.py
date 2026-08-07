from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.gmail_account import GmailAccount


class GmailAccountRepository:
    """Account-scoped persistence queries. Callers must always supply a user ID."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, account: GmailAccount) -> GmailAccount:
        self._session.add(account)
        self._session.flush()
        return account

    def get_for_user(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> GmailAccount | None:
        statement = select(GmailAccount).where(
            GmailAccount.id == account_id,
            GmailAccount.user_id == user_id,
        )
        return self._session.scalar(statement)

    def get_for_user_by_profile(
        self, *, user_id: uuid.UUID, gmail_profile_id: str
    ) -> GmailAccount | None:
        statement = select(GmailAccount).where(
            GmailAccount.user_id == user_id,
            GmailAccount.gmail_profile_id == gmail_profile_id,
        )
        return self._session.scalar(statement)

    def list_for_user(self, *, user_id: uuid.UUID) -> list[GmailAccount]:
        statement = select(GmailAccount).where(GmailAccount.user_id == user_id).order_by(
            GmailAccount.created_at
        )
        return list(self._session.scalars(statement))

    def delete(self, account: GmailAccount) -> None:
        self._session.delete(account)
