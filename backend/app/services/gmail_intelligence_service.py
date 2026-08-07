from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.gmail_account import GmailAccount, GmailSyncState
from app.models.gmail_data import Classification, GmailMessage, GmailThread, Recommendation, SyncRun
from app.security.token_store import TokenStore

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailApiError(RuntimeError):
    pass


def classify(subject: str, body: str) -> tuple[str, int, str]:
    """Small deterministic first-pass classifier; its result is persisted as intelligence."""
    text = f"{subject} {body}".lower()
    if any(word in text for word in ("deadline", "due", "assignment", "exam")):
        return "Action required", 92, "This email contains a deadline or task that needs attention."
    if any(word in text for word in ("meeting", "schedule", "calendar", "invite")):
        return "Schedule", 78, "This email appears to need scheduling attention."
    if any(word in text for word in ("invoice", "receipt", "payment", "bill")):
        return "Finance", 72, "This email relates to a payment or financial record."
    return "FYI", 35, "This email is useful context but has no detected urgent action."


class GmailIntelligenceService:
    def __init__(self, session: Session, token_store: TokenStore | None = None) -> None:
        self.session = session
        self.token_store = token_store

    def sync(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> dict[str, int]:
        account = self._account(user_id, account_id)
        run = SyncRun(user_id=user_id, gmail_account_id=account.id, mode="manual", status="running")
        self.session.add(run)
        try:
            if self.token_store is None:
                raise RuntimeError("No token store is configured.")
            token = self.token_store.get_refresh_token(gmail_account_id=account.id)
            access_token = self._refresh_access_token(token)
            profile = self._get("/profile", access_token)
            items = self._get("/messages?maxResults=50", access_token).get("messages", [])
            imported = 0
            for item in items:
                message = self._get(f"/messages/{item['id']}?format=full", access_token)
                imported += self._save_message(user_id, account, message)
            now = datetime.now(UTC)
            account.last_successful_sync_at = now
            state = self.session.get(GmailSyncState, account.id)
            if state is None:
                state = GmailSyncState(gmail_account_id=account.id, user_id=user_id)
                self.session.add(state)
            state.history_id = profile.get("historyId")
            state.last_successful_sync_at = now
            state.last_error_code = None
            state.last_error_at = None
            run.status, run.completed_at = "completed", now
            run.messages_examined, run.messages_imported = len(items), imported
            return {"messages_examined": len(items), "messages_imported": imported}
        except Exception as exc:
            run.status, run.completed_at, run.error_code = "failed", datetime.now(UTC), type(exc).__name__
            run.error_summary = str(exc)[:500]
            raise

    def feed(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> list[dict]:
        statement = (
            select(Classification, GmailThread, GmailAccount)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .where(Classification.user_id == user_id, Classification.is_current)
            .order_by(Classification.priority_score.desc(), GmailThread.latest_message_at.desc())
        )
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        return [self._feed_item(classification, thread, account) for classification, thread, account in self.session.execute(statement)]

    def detail(self, *, user_id: uuid.UUID, thread_id: uuid.UUID) -> dict | None:
        row = self.session.execute(
            select(Classification, GmailThread, GmailAccount)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .where(Classification.user_id == user_id, Classification.thread_id == thread_id, Classification.is_current)
        ).one_or_none()
        if row is None:
            return None
        classification, thread, account = row
        result = self._feed_item(classification, thread, account)
        result["messages"] = [
            {"from": message.from_address, "subject": message.subject, "body": message.body_text or message.snippet, "at": message.gmail_internal_date}
            for message in self.session.scalars(select(GmailMessage).where(GmailMessage.user_id == user_id, GmailMessage.thread_id == thread.id).order_by(GmailMessage.gmail_internal_date))
        ]
        return result

    def _save_message(self, user_id: uuid.UUID, account: GmailAccount, raw: dict) -> int:
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        internal_date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, UTC)
        thread = self._thread_for_message(
            user_id=user_id,
            account_id=account.id,
            gmail_thread_id=raw["threadId"],
            latest_message_at=internal_date,
        )
        thread.subject_normalized, thread.snippet, thread.latest_message_at = headers.get("subject"), raw.get("snippet"), internal_date
        thread.message_count, thread.is_in_inbox, thread.is_unread = 1, "INBOX" in raw.get("labelIds", []), "UNREAD" in raw.get("labelIds", [])
        existing = self.session.scalar(select(GmailMessage).where(GmailMessage.gmail_account_id == account.id, GmailMessage.gmail_message_id == raw["id"]))
        if existing:
            return 0
        body = _body(raw.get("payload", {}))
        self.session.add(GmailMessage(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, gmail_message_id=raw["id"], gmail_internal_date=internal_date, from_address=headers.get("from", "Unknown"), to_addresses={"to": headers.get("to", "")}, cc_addresses={"cc": headers["cc"]} if headers.get("cc") else None, subject=headers.get("subject"), snippet=raw.get("snippet"), body_text=body, label_ids=raw.get("labelIds", []), has_attachments=False))
        thread.message_count += 1
        category, score, explanation = classify(headers.get("subject", ""), body)
        current = self.session.scalar(select(Classification).where(Classification.thread_id == thread.id, Classification.is_current))
        if current:
            current.is_current = False
        classification = Classification(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, category=category, priority_score=score, confidence=0.8, explanation={"summary": explanation}, source="rules", classifier_version="m3-rules", is_current=True)
        self.session.add(classification)
        if score >= 70:
            self.session.add(Recommendation(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, classification_id=classification.id, recommendation_type="review", rationale={"summary": explanation}))
        return 1

    def _thread_for_message(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        gmail_thread_id: str,
        latest_message_at: datetime,
    ) -> GmailThread:
        statement = (
            insert(GmailThread)
            .values(
                user_id=user_id,
                gmail_account_id=account_id,
                gmail_thread_id=gmail_thread_id,
                latest_message_at=latest_message_at,
                message_count=0,
            )
            .on_conflict_do_nothing(constraint="uq_threads_account_gmail_id")
        )
        self.session.execute(statement)
        thread = self.session.scalar(
            select(GmailThread).where(
                GmailThread.gmail_account_id == account_id,
                GmailThread.gmail_thread_id == gmail_thread_id,
            )
        )
        if thread is None:
            raise RuntimeError("Gmail thread could not be created.")
        return thread

    def _account(self, user_id: uuid.UUID, account_id: uuid.UUID) -> GmailAccount:
        account = self.session.scalar(select(GmailAccount).where(GmailAccount.id == account_id, GmailAccount.user_id == user_id))
        if not account:
            raise LookupError("Gmail account not found.")
        return account

    def _refresh_access_token(self, refresh_token: str) -> str:
        from app.core.config import get_settings
        settings = get_settings()
        payload = urllib.parse.urlencode({"client_id": settings.google_oauth_client_id, "client_secret": settings.google_oauth_client_secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
        response = _request("https://oauth2.googleapis.com/token", data=payload)
        return response["access_token"]

    def _get(self, path: str, access_token: str) -> dict:
        return _request(f"{GMAIL_API}{path}", headers={"Authorization": f"Bearer {access_token}"})

    @staticmethod
    def _feed_item(classification: Classification, thread: GmailThread, account: GmailAccount) -> dict:
        return {"id": str(thread.id), "account_id": str(account.id), "account": account.gmail_email, "subject": thread.subject_normalized or "Untitled email", "snippet": thread.snippet or "", "category": classification.category, "priority": classification.priority_score, "summary": classification.explanation.get("summary", ""), "at": thread.latest_message_at}


def _request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers or {}), timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise GmailApiError(f"Gmail request failed ({exc.code}).") from exc


def _body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "===").decode(errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            return _body(part)
    return ""
