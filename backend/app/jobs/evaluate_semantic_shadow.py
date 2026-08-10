"""Append-only shadow evaluation for a future semantic-classifier provider."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.m5 import CLASSIFIER_VERSION, ThreadSnapshot
from app.classification.semantic_shadow import (
    SemanticClassificationError,
    SemanticClassifier,
    validate_decision,
)
from app.models.gmail_account import GmailAccount
from app.models.gmail_data import Classification, GmailMessage, GmailThread


def evaluate_account(
    session: Session,
    *,
    user_id: uuid.UUID,
    gmail_account_id: uuid.UUID,
    classifier: SemanticClassifier,
    source: str,
    classifier_version: str,
) -> int:
    """Append validated non-current provider results; M5 and all prior history remain untouched."""
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
        current = session.scalar(
            select(Classification).where(Classification.thread_id == thread.id, Classification.is_current)
        )
        if current is None or current.classifier_version != CLASSIFIER_VERSION:
            continue
        if session.scalar(
            select(Classification.id).where(
                Classification.thread_id == thread.id,
                Classification.source == source,
                Classification.classifier_version == classifier_version,
            )
        ):
            continue
        messages = list(
            session.scalars(
                select(GmailMessage)
                .where(GmailMessage.user_id == user_id, GmailMessage.thread_id == thread.id)
                .order_by(GmailMessage.gmail_internal_date.desc())
                .limit(3)
            )
        )
        if not messages:
            continue
        message = messages[0]
        context = "\n\n".join(
            f"Message {index + 1} from {item.from_address}:\n{item.body_text or item.snippet or ''}"
            for index, item in enumerate(messages)
        )
        try:
            decision = classifier.classify(
                ThreadSnapshot(
                    subject=message.subject or "",
                    body=context,
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
            decision = validate_decision(
                {
                    "category": decision.category,
                    "confidence": decision.confidence,
                    "requires_user_action": decision.requires_user_action,
                    "evidence": decision.evidence,
                },
                model=decision.model,
                classifier_version=decision.classifier_version,
            )
        except SemanticClassificationError:
            continue
        session.add(
            Classification(
                user_id=user_id,
                gmail_account_id=gmail_account_id,
                thread_id=thread.id,
                category=decision.category,
                priority_score=0,
                confidence=decision.confidence,
                explanation=decision.explanation,
                source=source,
                classifier_version=classifier_version,
                is_current=False,
            )
        )
        count += 1
    return count
