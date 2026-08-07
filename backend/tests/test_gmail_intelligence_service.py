import uuid
from datetime import UTC, datetime

from app.models.gmail_account import GmailAccount
from app.models.gmail_data import GmailThread
from app.services.gmail_intelligence_service import GmailIntelligenceService, classify


def test_classifier_prioritizes_deadlines_over_generic_context() -> None:
    assert classify("Assignment deadline changed", "Due Friday")[0:2] == ("Action required", 92)
    assert classify("Newsletter", "Useful reading")[0] == "FYI"


class ExistingThreadSession:
    def __init__(self, thread: GmailThread) -> None:
        self.thread = thread
        self.added: list[object] = []
        self.executed = 0
        self.scalar_calls = 0

    def execute(self, statement):
        self.executed += 1

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.thread if self.scalar_calls == 1 else None

    def add(self, value: object) -> None:
        self.added.append(value)


def test_saving_a_message_reuses_an_existing_gmail_thread() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(
        id=thread_id,
        user_id=user_id,
        gmail_account_id=account_id,
        gmail_thread_id="gmail-thread",
        latest_message_at=datetime.now(UTC),
        message_count=1,
    )
    session = ExistingThreadSession(thread)
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")
    raw = {"id": "gmail-message", "threadId": "gmail-thread", "internalDate": "0", "snippet": "Due tomorrow", "labelIds": ["INBOX"], "payload": {"headers": [{"name": "From", "value": "sender@example.com"}, {"name": "Subject", "value": "Deadline"}]}}

    GmailIntelligenceService(session)._save_message(user_id, account, raw)  # type: ignore[arg-type]

    assert session.executed == 1
    assert thread.id == thread_id
    assert not any(isinstance(value, GmailThread) for value in session.added)
