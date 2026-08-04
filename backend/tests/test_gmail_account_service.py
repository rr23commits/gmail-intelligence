from __future__ import annotations

import uuid

from app.models.gmail_account import GmailAccount
from app.services.gmail_account_service import GmailAccountService


class FakeGmailAccountRepository:
    def __init__(self) -> None:
        self.accounts: list[GmailAccount] = []

    def add(self, account: GmailAccount) -> GmailAccount:
        self.accounts.append(account)
        return account

    def get_for_user_by_profile(self, *, user_id: uuid.UUID, gmail_profile_id: str) -> GmailAccount | None:
        return next(
            (
                account
                for account in self.accounts
                if account.user_id == user_id and account.gmail_profile_id == gmail_profile_id
            ),
            None,
        )

    def list_for_user(self, *, user_id: uuid.UUID) -> list[GmailAccount]:
        return [account for account in self.accounts if account.user_id == user_id]


def test_registering_multiple_accounts_keeps_them_scoped_to_the_owner() -> None:
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    repository = FakeGmailAccountRepository()
    service = GmailAccountService(repository)  # type: ignore[arg-type]

    personal = service.register_account_metadata(
        user_id=owner_id,
        gmail_email="Personal@Example.com",
        gmail_profile_id="profile-personal",
    )
    service.register_account_metadata(
        user_id=owner_id,
        gmail_email="work@example.com",
        gmail_profile_id="profile-work",
    )

    assert personal.gmail_email_normalized == "personal@example.com"
    assert {account.gmail_profile_id for account in service.list_accounts(user_id=owner_id)} == {
        "profile-personal",
        "profile-work",
    }
    assert service.list_accounts(user_id=other_user_id) == []
