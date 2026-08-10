import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.classification.m5 import ThreadSnapshot, classify_thread
from app.models.gmail_account import GmailAccount
from app.models.gmail_data import Classification, GmailMessage, GmailThread, SyncRun
from app.services.gmail_intelligence_service import (
    CLEAN_UP,
    CONSIDER,
    DO,
    GmailIntelligenceService,
    SyncAlreadyRunning,
    _decision_bucket,
)


def test_classifier_separates_action_category_from_priority() -> None:
    decision = classify_thread(ThreadSnapshot(subject="Confirm your place", body="Please confirm by Friday.", from_address="team@example.test", to_addresses="user@example.test", cc_addresses="", account_email="user@example.test", label_ids=("INBOX",), latest_message_at=datetime.now(UTC), message_count=1, is_in_inbox=True, is_unread=True, delivery_metadata={}))

    assert decision.category == "action_required"
    assert decision.priority_score > 0
    assert decision.explanation["category"]["selected"] == "action_required"


class ExistingThreadSession:
    def __init__(self, thread: GmailThread, current: Classification | None = None) -> None:
        self.thread = thread
        self.current = current
        self.added: list[object] = []
        self.executed = 0
        self.scalar_calls = 0

    def execute(self, statement):
        self.executed += 1

    def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return self.thread
        return self.current if self.scalar_calls == 3 else None

    def scalars(self, statement):
        return []

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass


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
    prior = Classification(
        user_id=user_id,
        gmail_account_id=account_id,
        thread_id=thread_id,
        category="FYI",
        priority_score=35,
        confidence=0.8,
        explanation={"summary": "M3 result"},
        source="rules",
        classifier_version="m3-rules",
        is_current=True,
    )
    session = ExistingThreadSession(thread, prior)
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")
    raw = {
        "id": "gmail-message",
        "threadId": "gmail-thread",
        "internalDate": "0",
        "snippet": "Please confirm by Friday.",
        "labelIds": ["INBOX"],
        "payload": {
            "body": {"data": "UGxlYXNlIGNvbmZpcm0gYnkgRnJpZGF5Lg"},
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "user@example.com"},
                {"name": "Subject", "value": "Deadline"},
            ],
        },
    }

    GmailIntelligenceService(session)._save_message(user_id, account, raw)  # type: ignore[arg-type]

    assert session.executed == 1
    assert thread.id == thread_id
    assert not any(isinstance(value, GmailThread) for value in session.added)
    classification = next(value for value in session.added if isinstance(value, Classification))
    assert classification.classifier_version == "m5.1-local"
    assert classification.category == "action_required"
    assert classification.is_current
    assert not prior.is_current


class RepeatSyncSession(ExistingThreadSession):
    def __init__(self, thread: GmailThread, existing_message: GmailMessage, current: Classification) -> None:
        super().__init__(thread, current)
        self.existing_message = existing_message
        self.save_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls in {1, 4}:
            return self.thread
        if self.scalar_calls == 2:
            return None
        if self.scalar_calls == 3:
            return self.current
        if self.scalar_calls == 5:
            return self.existing_message
        return None


def test_syncing_the_same_message_twice_does_not_add_a_second_current_classification() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="repeat", latest_message_at=datetime.now(UTC), message_count=1)
    current = Classification(user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, category="notification", priority_score=35, confidence=0.8, explanation={"summary": "existing"}, source="local_deterministic", classifier_version="m5.1-local", is_current=True)
    message = GmailMessage(id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, gmail_message_id="same-message", gmail_internal_date=datetime.now(UTC), from_address="sender@example.com", to_addresses={"to": "user@example.com"}, subject="Notice", snippet="Notice", body_text="Notice", label_ids=["INBOX"])
    session = RepeatSyncSession(thread, message, current)
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")
    raw = {"id": "same-message", "threadId": "repeat", "internalDate": "0", "snippet": "Notice", "labelIds": ["INBOX"], "payload": {"body": {"data": "Tm90aWNl"}, "headers": [{"name": "From", "value": "sender@example.com"}, {"name": "To", "value": "user@example.com"}, {"name": "Subject", "value": "Notice"}]}}

    service = GmailIntelligenceService(session)
    assert service._save_message(user_id, account, raw) == 1  # type: ignore[arg-type]
    assert service._save_message(user_id, account, raw) == 0  # type: ignore[arg-type]
    assert sum(isinstance(value, Classification) for value in session.added) == 1


def test_same_thread_messages_flush_current_handoff_before_next_classification() -> None:
    session = ExistingThreadSession(
        GmailThread(id=uuid.uuid4(), user_id=uuid.uuid4(), gmail_account_id=uuid.uuid4(), gmail_thread_id="thread", latest_message_at=datetime.now(UTC)),
    )
    account = GmailAccount(id=session.thread.gmail_account_id, user_id=session.thread.user_id, gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")
    raw = {"id": "message", "threadId": "thread", "internalDate": "0", "snippet": "Notice", "labelIds": ["INBOX"], "payload": {"body": {"data": "Tm90aWNl"}, "headers": [{"name": "From", "value": "sender@example.com"}, {"name": "To", "value": "user@example.com"}, {"name": "Subject", "value": "Notice"}]}}

    GmailIntelligenceService(session)._save_message(session.thread.user_id, account, raw)  # type: ignore[arg-type]

    assert session.added and any(isinstance(value, Classification) and value.is_current for value in session.added)


def test_duplicate_sync_request_is_rejected_before_gmail_work() -> None:
    account = GmailAccount(id=uuid.uuid4(), user_id=uuid.uuid4(), gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")

    class LockedService(GmailIntelligenceService):
        def _account(self, user_id, account_id):
            return account

        def _acquire_sync_lock(self, account_id):
            return False

    try:
        LockedService(object()).sync(user_id=account.user_id, account_id=account.id)  # type: ignore[arg-type]
    except SyncAlreadyRunning:
        pass
    else:
        raise AssertionError("duplicate sync request was not rejected")


def test_interrupted_sync_runs_are_recovered() -> None:
    run = SyncRun(user_id=uuid.uuid4(), gmail_account_id=uuid.uuid4(), mode="manual", status="running", started_at=datetime(2020, 1, 1, tzinfo=UTC))

    class RecoverySession:
        def scalars(self, statement):
            return [run]

        def flush(self):
            pass

    recovered = GmailIntelligenceService(RecoverySession())._recover_stale_runs(user_id=run.user_id, account_id=run.gmail_account_id)  # type: ignore[arg-type]

    assert recovered == 1
    assert run.status == "failed"
    assert run.error_code == "interrupted"


def test_m2_overview_and_decision_mapping_are_data_backed() -> None:
    class Result:
        def all(self):
            return [("action_required", 2), ("notification", 3)]

    class OverviewService(GmailIntelligenceService):
        def _count_current(self, **_kwargs):
            return 4

        def _decision_counts(self, **_kwargs):
            return {DO: 2, CONSIDER: 1, CLEAN_UP: 3}

    class Session:
        def execute(self, _statement):
            return Result()

    overview = OverviewService(Session()).overview(user_id=uuid.uuid4())

    assert overview["total_analyzed"] == 5
    assert overview["categories"]["action_required"] == 2
    assert overview["categories"]["notification"] == 3
    assert overview["decisions"] == {DO: 2, CONSIDER: 1, CLEAN_UP: 3}
    assert _decision_bucket("action_required", 1) == DO
    assert _decision_bucket("important_keep", 80) == DO
    assert _decision_bucket("opportunity", 1) == CONSIDER
    assert _decision_bucket("notification", 99) == CLEAN_UP


def test_sender_groups_preserve_each_current_category() -> None:
    rows = [
        (SimpleNamespace(category="notification", priority_score=20), None, None, SimpleNamespace(from_address="LinkedIn <updates@linkedin.com>")),
        (SimpleNamespace(category="opportunity", priority_score=50), None, None, SimpleNamespace(from_address="jobs@linkedin.com")),
        (SimpleNamespace(category="action_required", priority_score=90), None, None, SimpleNamespace(from_address="alerts@other.test")),
    ]

    class GroupService(GmailIntelligenceService):
        def _classified_thread_rows(self, **_kwargs):
            return rows

    groups = GroupService(object()).sender_groups(user_id=uuid.uuid4())

    linkedin = next(group for group in groups if group["sender"] == "linkedin.com")
    assert linkedin["total"] == 2
    assert linkedin["categories"]["notification"] == 1
    assert linkedin["categories"]["opportunity"] == 1
    assert linkedin["decisions"][CONSIDER] == 1


def test_cleanup_groups_candidates_by_sender_and_category() -> None:
    promotional = {"id": str(uuid.uuid4()), "category": "promotional_bulk", "account_id": "account-a"}
    notification = {"id": str(uuid.uuid4()), "category": "notification", "account_id": "account-b"}

    class CleanupService(GmailIntelligenceService):
        def feed(self, **kwargs):
            return [promotional] if kwargs["category"] == "promotional_bulk" else [notification]

        def _safe_low_priority(self, **_kwargs):
            return [promotional]

        def _classified_thread_rows(self, **_kwargs):
            return [
                (None, SimpleNamespace(id=uuid.UUID(promotional["id"])), None, SimpleNamespace(from_address="news@store.test")),
                (None, SimpleNamespace(id=uuid.UUID(notification["id"])), None, SimpleNamespace(from_address="alerts@updates.test")),
            ]

    cleanup = CleanupService(object()).cleanup(user_id=uuid.uuid4())

    assert cleanup["total_impact"] == 2
    assert {group["key"] for group in cleanup["groups"]} == {"store.test:promotional_bulk", "updates.test:notification"}
    assert all(len(group["items"]) == 1 for group in cleanup["groups"])


def test_thread_actions_reject_threads_outside_selected_account() -> None:
    account = GmailAccount(id=uuid.uuid4(), user_id=uuid.uuid4(), gmail_email="user@example.com", gmail_email_normalized="user@example.com", gmail_profile_id="profile")

    class OwnershipService(GmailIntelligenceService):
        def _account(self, *_args):
            return account

    class Session:
        def scalars(self, _statement):
            return []

    try:
        OwnershipService(Session()).apply_thread_action(user_id=account.user_id, account_id=account.id, thread_ids=[uuid.uuid4()], action="delete")
    except LookupError:
        pass
    else:
        raise AssertionError("an out-of-account thread action was accepted")
