import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.classification.m5 import ThreadSnapshot, classify_thread
from app.models.gmail_account import GmailAccount
from app.models.gmail_data import (
    ActionTask,
    Classification,
    ClassificationFeedback,
    GmailMessage,
    GmailThread,
    SyncRun,
)
from app.services.gmail_intelligence_service import (
    CLEAN_UP,
    CONSIDER,
    DO,
    GmailIntelligenceService,
    SyncAlreadyRunning,
    _action_title,
    _decision_bucket,
    _display_body,
    _explicit_deadline,
    _related_conversation_messages,
)


def test_classifier_separates_action_category_from_priority() -> None:
    decision = classify_thread(ThreadSnapshot(subject="Confirm your place", body="Please confirm by Friday.", from_address="team@example.test", to_addresses="user@example.test", cc_addresses="", account_email="user@example.test", label_ids=("INBOX",), latest_message_at=datetime.now(UTC), message_count=1, is_in_inbox=True, is_unread=True, delivery_metadata={}))

    assert decision.category == "action_required"
    assert decision.priority_score > 0
    assert decision.explanation["category"]["selected"] == "action_required"


def test_detail_reconstructs_a_gmail_thread_in_chronological_order() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "m4_shehacks_thread.json").read_text())
    thread = GmailThread(
        id=thread_id,
        user_id=user_id,
        gmail_account_id=account_id,
        gmail_thread_id="shehacks-thread",
        latest_message_at=datetime.fromisoformat(fixture[-1]["at"]),
        is_unread=True,
    )
    account = GmailAccount(
        id=account_id,
        user_id=user_id,
        gmail_email="user@example.test",
        gmail_email_normalized="user@example.test",
        gmail_profile_id="profile",
    )
    classification = Classification(
        user_id=user_id,
        gmail_account_id=account_id,
        thread_id=thread_id,
        category="opportunity",
        priority_score=50,
        confidence=0.9,
        explanation={
            "summary": "SheHacks update.",
            "reasons": [{"signal": "requested_action", "label": "A confirmation is explicitly requested"}],
        },
        source="local_deterministic",
        classifier_version="m5.1-local",
        is_current=True,
    )
    messages = [
        GmailMessage(
            id=uuid.uuid4(),
            user_id=user_id,
            gmail_account_id=account_id,
            thread_id=thread_id,
            gmail_message_id=item["id"],
            gmail_internal_date=datetime.fromisoformat(item["at"]),
            from_address=item["from"],
            to_addresses={"to": "user@example.test"},
            subject=item["subject"],
            snippet=item["body"],
            body_text=item["body"],
            label_ids=["INBOX"],
        )
        for item in fixture
    ]

    class Result:
        def one_or_none(self):
            return classification, thread, account

    class Session:
        def execute(self, _statement):
            return Result()

        def scalars(self, _statement):
            return messages

        def scalar(self, _statement):
            return None

    detail = GmailIntelligenceService(Session()).detail(user_id=user_id, thread_id=thread_id)  # type: ignore[arg-type]

    assert [message["subject"] for message in detail["messages"]] == [item["subject"] for item in fixture]
    assert [message["is_current"] for message in detail["messages"]] == [False, False, True]
    assert detail["thread_intelligence"] == {
        "state": "3 messages in this Gmail conversation · unread",
        "latest_event": "SheHacks — First Round Cleared",
        "open_action": None,
        "explicit_deadline": "Deadline: 18 August 2026",
    }
    opened = GmailIntelligenceService(Session()).detail(  # type: ignore[arg-type]
        user_id=user_id, thread_id=thread_id, message_id=messages[0].id
    )
    assert [message["is_current"] for message in opened["messages"]] == [True, False, False]
    assert opened["messages"][0]["thread_id"] == str(thread_id)


def test_related_conversation_requires_same_domain_and_meaningful_subject_overlap() -> None:
    user_id, account_id, native_thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def message(thread_id: uuid.UUID, subject: str, sender: str) -> GmailMessage:
        return GmailMessage(
            id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=thread_id,
            gmail_message_id=str(uuid.uuid4()), gmail_internal_date=datetime.now(UTC), from_address=sender,
            to_addresses={"to": "user@example.test"}, subject=subject, snippet="", body_text="", label_ids=["INBOX"],
        )

    native = message(native_thread_id, "Urgent Action Required | Logitech x Aspire For Her", "Logitech <team@logitech.test>")
    related = message(uuid.uuid4(), "Participation Confirmation Pending | Women Who Master by Logitech x Aspire For Her", "Logitech <team@logitech.test>")
    unrelated = message(uuid.uuid4(), "Your Logitech order receipt", "Logitech <team@logitech.test>")

    assert _related_conversation_messages([native], [related, unrelated]) == [related]


def test_display_body_renders_html_email_without_raw_markup_or_whitespace_noise() -> None:
    rendered = _display_body(
        "```html\n<style>.email { margin-left: 900px }</style><p>Hello <b>there</b>.</p>\n"
        "<p>Read the <a href=\"https://example.test/details\">details</a>.</p>\n````\n"
    )

    assert rendered == '<p>Hello <b>there</b>.</p>\n<p>Read the <a href="https://example.test/details" target="_blank" rel="noreferrer">details</a>.</p>'
    assert "```" not in rendered
    assert "style" not in rendered
    assert _display_body("Hello\nPlain text") == "<p>Hello Plain text</p>"


def test_explicit_deadline_strips_html_and_inline_styles() -> None:
    message = GmailMessage(id=uuid.uuid4(), user_id=uuid.uuid4(), gmail_account_id=uuid.uuid4(), thread_id=uuid.uuid4(), gmail_message_id="deadline", gmail_internal_date=datetime.now(UTC), from_address="team@example.test", to_addresses={"to": "user@example.test"}, subject="Deadline", snippet="", body_text='Deadline extension expires in just <span style="font-size: 13pt; color: rgb(0, 0, 0)">one hour</span>', label_ids=["INBOX"])

    assert _explicit_deadline([message]) == "Deadline extension expires in just one hour"


def test_explicit_action_creates_an_open_task_with_its_deadline() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="task", latest_message_at=datetime.now(UTC))
    session = ExistingThreadSession(thread)
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    raw = {"id": "task-message", "threadId": "task", "internalDate": "0", "snippet": "Please send your availability for an interview by Friday.", "labelIds": ["INBOX"], "payload": {"body": {"data": "UGxlYXNlIHNlbmQgeW91ciBhdmFpbGFiaWxpdHkgZm9yIGFuIGludGVydmlldyBieSBGcmlkYXku"}, "headers": [{"name": "From", "value": "team@example.test"}, {"name": "To", "value": "user@example.test"}, {"name": "Subject", "value": "Interview"}]}}

    GmailIntelligenceService(session)._save_message(user_id, account, raw)  # type: ignore[arg-type]

    task = next(item for item in session.added if isinstance(item, ActionTask))
    assert (task.title, task.status, task.deadline, task.thread_id) == ("Send your availability for an interview", "open", "by Friday", thread_id)
    source = next(item for item in session.added if isinstance(item, GmailMessage))
    assert session.events.index(("add", source)) < session.events.index(("flush", None)) < session.events.index(("add", task))


def test_non_actionable_email_creates_no_task() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="fyi", latest_message_at=datetime.now(UTC))
    session = ExistingThreadSession(thread)
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    raw = {"id": "fyi-message", "threadId": "fyi", "internalDate": "0", "snippet": "Your monthly report is ready.", "labelIds": ["INBOX"], "payload": {"body": {"data": "WW91ciBtb250aGx5IHJlcG9ydCBpcyByZWFkeS4"}, "headers": [{"name": "From", "value": "team@example.test"}, {"name": "To", "value": "user@example.test"}, {"name": "Subject", "value": "Report"}]}}

    GmailIntelligenceService(session)._save_message(user_id, account, raw)  # type: ignore[arg-type]

    assert not any(isinstance(item, ActionTask) for item in session.added)


def test_existing_actionable_email_is_backfilled_once() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="existing", latest_message_at=datetime.now(UTC))
    message = GmailMessage(id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, gmail_message_id="existing-message", gmail_internal_date=datetime.now(UTC), from_address="team@example.test", to_addresses={"to": "user@example.test"}, subject="Participation", snippet="Please confirm your participation.", body_text="Please confirm your participation.", label_ids=["INBOX"])
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")

    class Session:
        def __init__(self):
            self.added: list[object] = []

        def execute(self, _statement):
            pass

        def scalar(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is GmailThread:
                return thread
            if entity is GmailMessage:
                return message
            return next((item for item in self.added if isinstance(item, ActionTask)), None)

        def add(self, value):
            self.added.append(value)

    session = Session()
    service = GmailIntelligenceService(session)  # type: ignore[arg-type]
    raw = {"id": "existing-message", "threadId": "existing", "internalDate": "0", "snippet": message.snippet, "labelIds": ["INBOX"], "payload": {"headers": []}}

    assert service._save_message(user_id, account, raw) == 0
    assert service._save_message(user_id, account, raw) == 0
    tasks = [item for item in session.added if isinstance(item, ActionTask)]
    assert [(task.title, task.status) for task in tasks] == [("Confirm your participation", "open")]


def test_existing_non_actionable_email_is_not_backfilled() -> None:
    message = GmailMessage(id=uuid.uuid4(), user_id=uuid.uuid4(), gmail_account_id=uuid.uuid4(), thread_id=uuid.uuid4(), gmail_message_id="fyi", gmail_internal_date=datetime.now(UTC), from_address="team@example.test", to_addresses={"to": "user@example.test"}, subject="Report", snippet="Your report is ready.", body_text="Your report is ready.", label_ids=["INBOX"])

    class Session:
        def scalar(self, _statement):
            return None

        def add(self, _value):
            raise AssertionError("non-actionable email created a task")

    GmailIntelligenceService(Session())._ensure_action_task(  # type: ignore[arg-type]
        user_id=message.user_id, account_id=message.gmail_account_id, message=message
    )


def test_clear_imperative_actions_create_tasks() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    class Session:
        def __init__(self):
            self.added: list[object] = []

        def add(self, value):
            self.added.append(value)

    session = Session()
    service = GmailIntelligenceService(session)  # type: ignore[arg-type]
    for body in ("<title>General</title><p>Complete the final step now.</p>", "Confirm your participation."):
        message = GmailMessage(id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, gmail_message_id=str(uuid.uuid4()), gmail_internal_date=datetime.now(UTC), from_address="team@example.test", to_addresses={"to": "user@example.test"}, subject="Action required", snippet=body, body_text=body, label_ids=["INBOX"])
        service._ensure_action_task(user_id=user_id, account_id=account_id, message=message, is_new=True)

    assert [task.title for task in session.added if isinstance(task, ActionTask)] == ["Complete the final step now", "Confirm your participation"]


def test_action_title_detects_concrete_requests_but_not_status_messages() -> None:
    assert _action_title("FINAL 60 MINUTES: Submit your Prototype Now | AI for Bharat") == "Submit your Prototype Now"
    assert _action_title("Upload documents before Friday.") == "Upload documents"
    assert _action_title("Complete a form to continue.") == "Complete a form to continue"
    assert _action_title("Submission Successful for AI for Bharat") is None
    assert _action_title("Your Certificate of Participation has been issued") is None
    assert _action_title("Announcement of shortlisted teams") is None
    assert _action_title("Send it to <span>5,00,000+ subscribers</span>") is None


def test_dashboard_reuses_open_tasks_consider_and_cleanup_data() -> None:
    user_id, account_id, thread_id, message_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    task = ActionTask(id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, message_id=message_id, title="Submit your prototype", deadline="by Friday", status="open")
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="briefing", subject_normalized="Prototype deadline", latest_message_at=datetime.now(UTC))
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    classification = Classification(user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, category="action_required", priority_score=90, confidence=0.9, explanation={}, source="local_deterministic", classifier_version="m5.1-local", is_current=True)
    consider = [{"id": str(uuid.uuid4()), "subject": "A relevant opportunity", "category": "opportunity", "priority": 55}]

    class Session:
        def execute(self, statement):
            assert account_id in statement.compile().params.values()
            return [(task, thread, account, classification)]

    class Service(GmailIntelligenceService):
        def feed(self, *, user_id, account_id=None, decision=None, **_kwargs):
            assert user_id == task.user_id and account_id == task.gmail_account_id and decision == CONSIDER
            return consider

        def cleanup(self, *, user_id, account_id=None, **_kwargs):
            assert user_id == task.user_id and account_id == task.gmail_account_id
            return {"total_impact": 7}

        def _decision_count(self, **_kwargs):
            return 1

        def _cleanup_count(self, **_kwargs):
            return 7

    briefing = Service(Session()).dashboard(user_id=user_id, account_id=account_id)  # type: ignore[arg-type]

    assert briefing["tasks"] == [{
        "id": str(task.id), "title": "Submit your prototype", "deadline": "by Friday", "status": "open",
        "source_thread_id": str(thread_id), "source_message_id": str(message_id), "account_id": str(account_id),
        "account": "user@example.test", "priority": 90, "latest_event": "Prototype deadline", "open_action": "Submit your prototype",
    }]
    assert briefing["consider"] == consider
    assert briefing["consider_count"] == 1
    assert briefing["cleanup_count"] == 7


def test_sync_runs_are_account_scoped() -> None:
    user_id, account_id = uuid.uuid4(), uuid.uuid4()
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    run = SyncRun(user_id=user_id, gmail_account_id=account_id, mode="manual", status="failed", messages_examined=0, messages_imported=0, error_code="IntegrityError", error_summary="source message missing")

    class Session:
        def scalar(self, _statement):
            return account

        def scalars(self, statement):
            assert account_id in statement.compile().params.values()
            return [run]

    logs = GmailIntelligenceService(Session()).sync_runs(user_id=user_id, account_id=account_id)  # type: ignore[arg-type]

    assert logs == [{"status": "failed", "started_at": run.started_at, "completed_at": None, "messages_examined": 0, "messages_imported": 0, "error_code": "IntegrityError", "error_summary": "source message missing"}]


def test_task_status_update_is_account_scoped() -> None:
    user_id, account_id, other_account_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    task = ActionTask(id=uuid.uuid4(), user_id=user_id, gmail_account_id=account_id, thread_id=uuid.uuid4(), message_id=uuid.uuid4(), title="Send availability")

    class Session:
        def scalar(self, statement):
            return task if account_id in statement.compile().params.values() else None

    service = GmailIntelligenceService(Session())  # type: ignore[arg-type]
    assert service.update_task_status(user_id=user_id, account_id=other_account_id, task_id=task.id, status="done") is None
    updated = service.update_task_status(user_id=user_id, account_id=account_id, task_id=task.id, status="done")
    assert updated and updated["status"] == task.status == "done"


def test_sync_hydrates_every_message_in_a_gmail_thread() -> None:
    user_id, account_id = uuid.uuid4(), uuid.uuid4()
    fixture = json.loads((Path(__file__).parent / "fixtures" / "m4_shehacks_thread.json").read_text())
    account = GmailAccount(
        id=account_id,
        user_id=user_id,
        gmail_email="user@example.test",
        gmail_email_normalized="user@example.test",
        gmail_profile_id="profile",
    )
    saved: list[dict] = []

    class Session:
        def scalar(self, _statement):
            return None

        def scalars(self, _statement):
            return []

        def add(self, _value):
            pass

        def flush(self):
            pass

        def commit(self):
            pass

        def get(self, _model, _id):
            return None

    class Service(GmailIntelligenceService):
        def _account(self, _user_id, _account_id):
            return account

        def _acquire_sync_lock(self, _account_id):
            return True

        def _release_sync_lock(self, _account_id):
            pass

        def _refresh_access_token(self, _token):
            return "access-token"

        def _get(self, path, _access_token):
            if path == "/profile":
                return {"historyId": "1"}
            if path == "/messages?maxResults=100":
                return {"messages": [{"id": fixture[-1]["id"], "threadId": "shehacks-thread"}]}
            if path == "/threads/shehacks-thread?format=full":
                return {
                    "messages": [
                        {
                            "id": item["id"],
                            "threadId": "shehacks-thread",
                            "internalDate": str(int(datetime.fromisoformat(item["at"]).timestamp() * 1000)),
                        }
                        for item in fixture
                    ]
                }
            raise AssertionError(path)

        def _save_message(self, _user_id, _account, raw):
            saved.append(raw)
            return 1

    service = Service(Session(), token_store=SimpleNamespace(get_refresh_token=lambda **_: "refresh-token"))
    result = service.sync(user_id=user_id, account_id=account_id)

    assert result == {"messages_examined": 1, "messages_imported": 3}
    assert [message["id"] for message in saved] == [item["id"] for item in fixture]


def test_sync_uses_gmail_history_after_the_first_sync() -> None:
    user_id, account_id = uuid.uuid4(), uuid.uuid4()
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    state = SimpleNamespace(history_id="100", last_successful_sync_at=None, last_error_code=None, last_error_at=None)
    paths: list[str] = []
    saved: list[str] = []

    class Session:
        def scalar(self, _statement):
            return None

        def scalars(self, _statement):
            return []

        def add(self, _value):
            pass

        def flush(self):
            pass

        def commit(self):
            pass

        def get(self, _model, _id):
            return state

    class Service(GmailIntelligenceService):
        def _account(self, _user_id, _account_id):
            return account

        def _acquire_sync_lock(self, _account_id):
            return True

        def _release_sync_lock(self, _account_id):
            pass

        def _refresh_access_token(self, _token):
            return "access-token"

        def _get(self, path, _access_token):
            paths.append(path)
            if path == "/profile":
                return {"historyId": "101"}
            if path == "/history?startHistoryId=100&historyTypes=messageAdded&maxResults=500":
                return {"history": [{"messagesAdded": [{"message": {"id": "new", "threadId": "new-thread"}}]}]}
            if path == "/threads/new-thread?format=full":
                return {"messages": [{"id": "new", "threadId": "new-thread", "internalDate": "0"}]}
            raise AssertionError(path)

        def _save_message(self, _user_id, _account, raw):
            saved.append(raw["id"])
            return 1

    result = Service(Session(), token_store=SimpleNamespace(get_refresh_token=lambda **_: "refresh-token")).sync(user_id=user_id, account_id=account_id)  # type: ignore[arg-type]

    assert result == {"messages_examined": 1, "messages_imported": 1}
    assert saved == ["new"]
    assert not any(path.startswith("/messages?") for path in paths)
    assert state.history_id == "101"


class ExistingThreadSession:
    def __init__(self, thread: GmailThread, current: Classification | None = None) -> None:
        self.thread = thread
        self.current = current
        self.added: list[object] = []
        self.events: list[tuple[str, object | None]] = []
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
        self.events.append(("add", value))

    def flush(self) -> None:
        self.events.append(("flush", None))


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


def test_two_corrections_change_a_later_synced_message(monkeypatch) -> None:
    user_id, account_id = uuid.uuid4(), uuid.uuid4()
    thread = GmailThread(
        id=uuid.uuid4(),
        user_id=user_id,
        gmail_account_id=account_id,
        gmail_thread_id="later-thread",
        latest_message_at=datetime.now(UTC),
    )
    feedback = [
        ClassificationFeedback(
            user_id=user_id,
            gmail_account_id=account_id,
            thread_id=uuid.uuid4(),
            original_category="notification",
            corrected_category="promotional_bulk",
            classifier_version="m5.1-local",
            sender_address="news@sender.test",
            sender_domain="sender.test",
        )
        for _ in range(2)
    ]

    class FeedbackSyncSession(ExistingThreadSession):
        def scalars(self, _statement):
            return feedback

    monkeypatch.setattr(
        "app.services.gmail_intelligence_service.classify_thread_m5_1",
        lambda _snapshot: SimpleNamespace(
            category="notification",
            priority_score=20,
            confidence=0.9,
            explanation={"summary": "Notice", "reasons": []},
        ),
    )
    session = FeedbackSyncSession(thread)
    account = GmailAccount(
        id=account_id,
        user_id=user_id,
        gmail_email="user@example.com",
        gmail_email_normalized="user@example.com",
        gmail_profile_id="profile",
    )
    raw = {
        "id": "later-message",
        "threadId": "later-thread",
        "internalDate": "0",
        "snippet": "Newsletter",
        "labelIds": ["INBOX"],
        "payload": {
            "body": {"data": "TmV3c2xldHRlcg"},
            "headers": [
                {"name": "From", "value": "news@sender.test"},
                {"name": "To", "value": "user@example.com"},
                {"name": "Subject", "value": "Newsletter"},
            ],
        },
    }

    GmailIntelligenceService(session)._save_message(user_id, account, raw)  # type: ignore[arg-type]

    current = next(
        item
        for item in session.added
        if isinstance(item, Classification) and item.is_current
    )
    assert current.category == "promotional_bulk"
    assert current.classifier_version == "m5.1-feedback-local"


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


def test_sync_lock_is_transaction_scoped() -> None:
    class Session:
        def scalar(self, statement):
            assert "pg_try_advisory_xact_lock" in str(statement)
            return True

    assert GmailIntelligenceService(Session())._acquire_sync_lock(uuid.uuid4())  # type: ignore[arg-type]


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
    assert _decision_bucket("important_keep", 80) == CONSIDER
    assert _decision_bucket("opportunity", 1) == CONSIDER
    assert _decision_bucket("notification", 99) == CLEAN_UP


def test_feed_filters_with_the_same_decision_buckets_as_overview() -> None:
    def row(category: str, priority_score: int) -> tuple:
        return (
            SimpleNamespace(category=category, priority_score=priority_score, confidence=0.9, explanation={}),
            SimpleNamespace(
                id=uuid.uuid4(),
                subject_normalized=category,
                snippet="",
                latest_message_at=datetime.now(UTC),
                is_unread=False,
            ),
            SimpleNamespace(id=uuid.uuid4(), gmail_email="user@example.test"),
        )

    rows = [
        row("action_required", 20),
        row("important_keep", 80),
        row("important_keep", 79),
        row("opportunity", 50),
        row("personal_conversation", 50),
        row("promotional_bulk", 20),
        row("notification", 20),
        row("otp_verification", 20),
        row("unclear", 20),
    ]

    class Session:
        def execute(self, _statement):
            return rows

    service = GmailIntelligenceService(Session())

    assert [item["category"] for item in service.feed(user_id=uuid.uuid4(), decision=DO)] == ["action_required"]
    assert [item["category"] for item in service.feed(user_id=uuid.uuid4(), decision=CONSIDER)] == [
        "important_keep",
        "important_keep",
        "opportunity",
        "personal_conversation",
    ]
    assert [item["category"] for item in service.feed(user_id=uuid.uuid4(), decision=CLEAN_UP)] == [
        "promotional_bulk",
        "notification",
        "otp_verification",
        "unclear",
    ]


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
            assert kwargs["decision"] == CLEAN_UP
            return [promotional, notification]

    class Session:
        def execute(self, _statement):
            return [
                (uuid.UUID(promotional["id"]), "news@store.test"),
                (uuid.UUID(notification["id"]), "alerts@updates.test"),
            ]

        def scalar(self, _statement):
            return 2

    cleanup = CleanupService(Session()).cleanup(user_id=uuid.uuid4())

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
