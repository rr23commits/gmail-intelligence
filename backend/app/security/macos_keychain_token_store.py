from __future__ import annotations

import platform
import uuid
from typing import Protocol

import keyring

from app.security.token_store import TokenNotFoundError, TokenStore


class KeyringBackend(Protocol):
    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def get_password(self, service_name: str, username: str) -> str | None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


class MacOSKeychainTokenStore(TokenStore):
    """Stores refresh tokens in the current macOS user's Keychain, never PostgreSQL."""

    credential_store_name = "macos_keychain"
    service_name = "com.gmail-manager.oauth"

    def __init__(self, keyring_backend: KeyringBackend | None = None) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("MacOSKeychainTokenStore is available only on macOS.")
        self._keyring = keyring_backend or keyring

    def save_refresh_token(self, *, gmail_account_id: uuid.UUID, refresh_token: str) -> str:
        self._keyring.set_password(self.service_name, str(gmail_account_id), refresh_token)
        return self._reference_for(gmail_account_id)

    def get_refresh_token(self, *, gmail_account_id: uuid.UUID) -> str:
        refresh_token = self._keyring.get_password(self.service_name, str(gmail_account_id))
        if refresh_token is None:
            raise TokenNotFoundError(f"No refresh token stored for Gmail account {gmail_account_id}.")
        return refresh_token

    def delete_refresh_token(self, *, gmail_account_id: uuid.UUID) -> None:
        try:
            self._keyring.delete_password(self.service_name, str(gmail_account_id))
        except keyring.errors.PasswordDeleteError:
            return

    def _reference_for(self, gmail_account_id: uuid.UUID) -> str:
        return f"keychain://{self.service_name}/{gmail_account_id}"
