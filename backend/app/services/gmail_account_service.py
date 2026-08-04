from __future__ import annotations

import uuid

from app.models.gmail_account import GmailAccount
from app.repositories.gmail_account_repository import GmailAccountRepository


class GmailAccountService:
    """Future Gmail connection workflows; no OAuth or Gmail calls occur in this milestone."""

    def __init__(self, gmail_account_repository: GmailAccountRepository) -> None:
        self._gmail_account_repository = gmail_account_repository

    def register_account_metadata(
        self,
        *,
        user_id: uuid.UUID,
        gmail_email: str,
        gmail_profile_id: str,
        display_name: str | None = None,
    ) -> GmailAccount:
        """Persist account identity after a future OAuth callback has verified it."""

        normalized_email = gmail_email.strip().lower()
        existing = self._gmail_account_repository.get_for_user_by_profile(
            user_id=user_id,
            gmail_profile_id=gmail_profile_id,
        )
        if existing is not None:
            existing.gmail_email = gmail_email.strip()
            existing.gmail_email_normalized = normalized_email
            existing.display_name = display_name.strip() if display_name else None
            return existing

        return self._gmail_account_repository.add(
            GmailAccount(
                user_id=user_id,
                gmail_email=gmail_email.strip(),
                gmail_email_normalized=normalized_email,
                gmail_profile_id=gmail_profile_id,
                display_name=display_name.strip() if display_name else None,
            )
        )

    def list_accounts(self, *, user_id: uuid.UUID) -> list[GmailAccount]:
        return self._gmail_account_repository.list_for_user(user_id=user_id)
