from __future__ import annotations

import uuid
from abc import ABC, abstractmethod


class TokenNotFoundError(LookupError):
    """Raised when no refresh token exists for the requested Gmail account."""


class TokenStore(ABC):
    """Secret-storage boundary for account-specific OAuth refresh tokens."""

    @abstractmethod
    def save_refresh_token(self, *, gmail_account_id: uuid.UUID, refresh_token: str) -> str:
        """Save a secret in the platform token store."""

    @abstractmethod
    def get_refresh_token(self, *, gmail_account_id: uuid.UUID) -> str:
        """Load the refresh token for one account without exposing storage details."""

    @abstractmethod
    def delete_refresh_token(self, *, gmail_account_id: uuid.UUID) -> None:
        """Remove the refresh token for one account."""
