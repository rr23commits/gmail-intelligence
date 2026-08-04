"""SQLAlchemy persistence models loaded for Alembic metadata discovery."""

from app.models.gmail_account import GmailAccount, GmailOAuthCredential, GmailSyncState
from app.models.gmail_data import (
    Classification,
    FeedbackEvent,
    GmailMessage,
    GmailThread,
    Recommendation,
    SyncRun,
)
from app.models.user import User

__all__ = [
    "Classification",
    "FeedbackEvent",
    "GmailAccount",
    "GmailMessage",
    "GmailOAuthCredential",
    "GmailSyncState",
    "GmailThread",
    "Recommendation",
    "SyncRun",
    "User",
]
