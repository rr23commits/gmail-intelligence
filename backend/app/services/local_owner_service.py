from __future__ import annotations

from app.core.config import get_settings
from app.models.user import User
from app.repositories.user_repository import UserRepository


class LocalOwnerService:
    """Provisions the single local V1 user without implementing login yet."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def ensure_owner(self) -> User:
        settings = get_settings()
        normalized_email = settings.local_owner_email.strip().lower()
        existing_owner = self._user_repository.get_by_normalized_email(normalized_email)
        if existing_owner is not None:
            return existing_owner

        return self._user_repository.add(
            User(
                email=settings.local_owner_email.strip(),
                email_normalized=normalized_email,
                display_name=settings.local_owner_display_name.strip() or None,
            )
        )
