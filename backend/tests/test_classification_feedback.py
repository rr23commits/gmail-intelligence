import uuid
from datetime import UTC, datetime

import pytest

from app.classification.feedback import (
    FEEDBACK_CLASSIFIER_VERSION,
    FeedbackSignal,
    apply_feedback,
    user_correction,
    validate_corrected_category,
)
from app.classification.m5 import ClassificationDecision
from app.models.gmail_account import GmailAccount
from app.models.gmail_data import Classification, ClassificationFeedback, GmailMessage, GmailThread
from app.services.gmail_intelligence_service import GmailIntelligenceService


def decision(category: str = "notification") -> ClassificationDecision:
    return ClassificationDecision(category, 42, 0.9, {"summary": "Original", "category": {"selected": category}, "reasons": []})


def test_invalid_correction_category_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_corrected_category("made_up")


def test_user_correction_is_displayed_without_mutating_original_decision() -> None:
    original = decision()
    corrected = user_correction(original, category="promotional_bulk")

    assert corrected.category == "promotional_bulk"
    assert corrected.explanation["feedback"]["original_category"] == "notification"
    assert original.category == "notification"


def test_repeated_feedback_changes_only_the_same_sender_category() -> None:
    feedback = [
        FeedbackSignal("sender.test", "notification", "promotional_bulk"),
        FeedbackSignal("sender.test", "notification", "promotional_bulk"),
    ]

    assert apply_feedback(decision(), sender_domain="sender.test", feedback=feedback).category == "promotional_bulk"
    assert apply_feedback(decision(), sender_domain="other.test", feedback=feedback).category == "notification"


def test_feedback_never_overrides_otp() -> None:
    feedback = [
        FeedbackSignal("sender.test", "otp_verification", "notification"),
        FeedbackSignal("sender.test", "otp_verification", "notification"),
    ]

    assert apply_feedback(decision("otp_verification"), sender_domain="sender.test", feedback=feedback).category == "otp_verification"


class _Result:
    def __init__(self, row: object) -> None:
        self.row = row

    def one_or_none(self) -> object:
        return self.row


class FeedbackSession:
    def __init__(self, row: object, values: list[object]) -> None:
        self.row, self.values, self.added = row, iter(values), []

    def execute(self, statement):
        return _Result(self.row)

    def scalar(self, statement):
        return next(self.values)

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        pass


def test_saving_a_correction_creates_new_current_history_row() -> None:
    user_id, account_id, thread_id, message_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    account = GmailAccount(id=account_id, user_id=user_id, gmail_email="user@example.test", gmail_email_normalized="user@example.test", gmail_profile_id="profile")
    thread = GmailThread(id=thread_id, user_id=user_id, gmail_account_id=account_id, gmail_thread_id="thread", latest_message_at=datetime.now(UTC))
    original = Classification(user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, category="notification", priority_score=42, confidence=0.9, explanation=decision().explanation, source="local_deterministic", classifier_version="m5.1-local", is_current=True)
    message = GmailMessage(id=message_id, user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, gmail_message_id="message", gmail_internal_date=datetime.now(UTC), from_address="Sender <news@sender.test>", to_addresses={"to": "user@example.test"}, cc_addresses=None, subject="News", snippet="News", body_text="News", label_ids=[])
    session = FeedbackSession((original, thread, account), [original, None, message])

    saved = GmailIntelligenceService(session).correct_classification(user_id=user_id, thread_id=thread_id, corrected_category="promotional_bulk")  # type: ignore[arg-type]

    feedback = next(item for item in session.added if isinstance(item, ClassificationFeedback))
    replacement = next(item for item in session.added if isinstance(item, Classification))
    assert feedback.sender_domain == "sender.test"
    assert replacement.classifier_version == FEEDBACK_CLASSIFIER_VERSION
    assert replacement.category == saved["category"] == "promotional_bulk"
    assert not original.is_current and replacement.is_current


def test_feedback_leaves_m3_and_m5_history_unchanged() -> None:
    user_id, account_id, thread_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    history = [
        Classification(user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, category="notification", priority_score=35, confidence=0.8, explanation={}, source="rules", classifier_version="m3-rules", is_current=False),
        Classification(user_id=user_id, gmail_account_id=account_id, thread_id=thread_id, category="unclear", priority_score=35, confidence=0.8, explanation={}, source="local_deterministic", classifier_version="m5.0-local", is_current=False),
    ]
    before = [(item.category, item.classifier_version, item.is_current) for item in history]

    user_correction(decision(), category="promotional_bulk")

    assert [(item.category, item.classifier_version, item.is_current) for item in history] == before
