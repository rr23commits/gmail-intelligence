from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Persistence operations for application users."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_normalized_email(self, email_normalized: str) -> User | None:
        statement = select(User).where(User.email_normalized == email_normalized)
        return self._session.scalar(statement)

    def add(self, user: User) -> User:
        self._session.add(user)
        self._session.flush()
        return user
