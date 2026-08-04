from __future__ import annotations

import uuid

import pytest

from app.security.macos_keychain_token_store import MacOSKeychainTokenStore
from app.security.token_store import TokenNotFoundError


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def delete_password(self, service_name: str, username: str) -> None:
        del self.values[(service_name, username)]


def test_keychain_store_returns_only_a_non_secret_reference() -> None:
    account_id = uuid.uuid4()
    store = MacOSKeychainTokenStore(FakeKeyring())

    reference = store.save_refresh_token(gmail_account_id=account_id, refresh_token="secret-refresh-token")

    assert reference == f"keychain://{store.service_name}/{account_id}"
    assert "secret-refresh-token" not in reference
    assert store.get_refresh_token(gmail_account_id=account_id) == "secret-refresh-token"


def test_keychain_store_reports_missing_token() -> None:
    store = MacOSKeychainTokenStore(FakeKeyring())

    with pytest.raises(TokenNotFoundError):
        store.get_refresh_token(gmail_account_id=uuid.uuid4())
