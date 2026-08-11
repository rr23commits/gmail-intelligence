"""SQLAlchemy persistence models loaded for Alembic metadata discovery."""

from app.models.gmail_account import GmailAccount, GmailSyncState
from app.models.gmail_data import (
    ActionTask,
    Classification,
    ClassificationFeedback,
    FeedbackEvent,
    GmailMessage,
    GmailThread,
    Recommendation,
    SyncRun,
)
from app.models.user import User

__all__ = [
    "ActionTask",
    "Classification",
    "ClassificationFeedback",
    "FeedbackEvent",
    "GmailAccount",
    "GmailMessage",
    "GmailSyncState",
    "GmailThread",
    "Recommendation",
    "SyncRun",
    "User",
]
