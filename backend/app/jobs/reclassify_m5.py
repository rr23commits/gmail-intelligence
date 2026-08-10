"""One-time M5 reclassification helper; invoke explicitly after deployment."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.m5 import CLASSIFIER_VERSION, ThreadSnapshot, classify_thread
from app.models.gmail_account import GmailAccount
from app.models.gmail_data import Classification, GmailMessage, GmailThread


def reclassify_account(session: Session, *, user_id: uuid.UUID, gmail_account_id: uuid.UUID) -> int:
    """Append current M5 results for stored account-scoped threads without changing M3 history."""
    account = session.scalar(
        select(GmailAccount).where(GmailAccount.id == gmail_account_id, GmailAccount.user_id == user_id)
    )
    if account is None:
        raise LookupError("Gmail account not found.")
    threads = session.scalars(
        select(GmailThread).where(
            GmailThread.user_id == user_id,
            GmailThread.gmail_account_id == gmail_account_id,
        )
    )
    count = 0
    for thread in threads:
        message = session.scalar(
            select(GmailMessage)
            .where(GmailMessage.user_id == user_id, GmailMessage.thread_id == thread.id)
            .order_by(GmailMessage.gmail_internal_date.desc())
        )
        if message is None:
            continue
        current = session.scalar(
            select(Classification).where(Classification.thread_id == thread.id, Classification.is_current)
        )
        if current and current.classifier_version == CLASSIFIER_VERSION:
            continue
        if current:
            current.is_current = False
            session.flush()
        decision = classify_thread(
            ThreadSnapshot(
                subject=message.subject or "",
                body=message.body_text or message.snippet or "",
                from_address=message.from_address,
                to_addresses=message.to_addresses.get("to", ""),
                cc_addresses=(message.cc_addresses or {}).get("cc", ""),
                account_email=account.gmail_email,
                label_ids=tuple(message.label_ids),
                latest_message_at=message.gmail_internal_date,
                message_count=thread.message_count,
                is_in_inbox=thread.is_in_inbox,
                is_unread=thread.is_unread,
                delivery_metadata=message.delivery_metadata,
            )
        )
        session.add(
            Classification(
                user_id=user_id,
                gmail_account_id=gmail_account_id,
                thread_id=thread.id,
                category=decision.category,
                priority_score=decision.priority_score,
                confidence=decision.confidence,
                explanation=decision.explanation,
                source="local_deterministic",
                classifier_version=CLASSIFIER_VERSION,
                is_current=True,
            )
        )
        count += 1
    return count
