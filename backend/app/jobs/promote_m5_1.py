"""Promote validated M5.1 shadow classifications without deleting history."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification.m5 import CATEGORIES, CLASSIFIER_VERSION, M5_1_CLASSIFIER_VERSION
from app.models.gmail_data import Classification


def promote_account(session: Session, *, user_id: uuid.UUID, gmail_account_id: uuid.UUID) -> int:
    """Make each validated M5.1 shadow row current, preserving M3/M5.0 rows."""
    current_rows = list(
        session.scalars(
            select(Classification).where(
                Classification.user_id == user_id,
                Classification.gmail_account_id == gmail_account_id,
                Classification.classifier_version == CLASSIFIER_VERSION,
                Classification.is_current,
            )
        )
    )
    pairs: list[tuple[Classification, Classification]] = []
    for current in current_rows:
        shadow = session.scalar(
            select(Classification).where(
                Classification.thread_id == current.thread_id,
                Classification.classifier_version == M5_1_CLASSIFIER_VERSION,
                Classification.is_current.is_(False),
            )
        )
        if shadow is None:
            raise ValueError(f"Missing M5.1 shadow classification for thread {current.thread_id}.")
        if shadow.category not in CATEGORIES:
            raise ValueError(f"Invalid M5.1 category {shadow.category!r} for thread {current.thread_id}.")
        pairs.append((current, shadow))

    for current, shadow in pairs:
        current.is_current = False
        session.flush()
        shadow.is_current = True
    return len(pairs)
