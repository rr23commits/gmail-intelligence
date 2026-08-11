from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from email.utils import parseaddr
from html import escape, unescape
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.classification.feedback import (
    FEEDBACK_CLASSIFIER_VERSION,
    FeedbackSignal,
    apply_feedback,
    user_correction,
)
from app.classification.m5 import (
    CATEGORIES,
    M5_1_CLASSIFIER_VERSION,
    ClassificationDecision,
    ThreadSnapshot,
    classify_thread_m5_1,
)
from app.models.gmail_account import GmailAccount, GmailSyncState
from app.models.gmail_data import (
    Classification,
    ClassificationFeedback,
    GmailMessage,
    GmailThread,
    SyncRun,
)
from app.security.token_store import TokenStore

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
logger = logging.getLogger(__name__)
DO = "do"
CONSIDER = "consider"
CLEAN_UP = "clean_up"


class GmailApiError(RuntimeError):
    pass


class SyncAlreadyRunning(RuntimeError):
    """This account already has a live synchronization run."""


class GmailIntelligenceService:
    def __init__(self, session: Session, token_store: TokenStore | None = None) -> None:
        self.session = session
        self.token_store = token_store

    def sync(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> dict[str, int]:
        account = self._account(user_id, account_id)
        acquired = self._acquire_sync_lock(account.id)
        if not acquired:
            raise SyncAlreadyRunning("A Gmail sync is already running for this account.")
        self._recover_stale_runs(user_id=user_id, account_id=account.id)
        active = self.session.scalar(
            select(SyncRun).where(
                SyncRun.user_id == user_id,
                SyncRun.gmail_account_id == account.id,
                SyncRun.status == "running",
            )
        )
        if active is not None:
            self._release_sync_lock(account.id)
            raise SyncAlreadyRunning("A Gmail sync is already running for this account.")
        run = SyncRun(user_id=user_id, gmail_account_id=account.id, mode="manual", status="running")
        self.session.add(run)
        self.session.flush()
        logger.info("Gmail sync started account=%s run=%s", account.id, run.id)
        try:
            if self.token_store is None:
                raise RuntimeError("No token store is configured.")
            token = self.token_store.get_refresh_token(gmail_account_id=account.id)
            access_token = self._refresh_access_token(token)
            profile = self._get("/profile", access_token)
            imported = 0
            examined = 0
            page_token: str | None = None
            synced_thread_ids: set[str] = set()
            while True:
                path = "/messages?maxResults=100"
                if page_token:
                    path += f"&pageToken={urllib.parse.quote(page_token)}"
                page = self._get(path, access_token)
                items = page.get("messages", [])
                examined += len(items)
                logger.info("Gmail sync page account=%s run=%s page_messages=%s examined=%s", account.id, run.id, len(items), examined)
                for item in items:
                    gmail_thread_id = item.get("threadId")
                    if not gmail_thread_id or gmail_thread_id in synced_thread_ids:
                        continue
                    synced_thread_ids.add(gmail_thread_id)
                    gmail_thread = self._get(
                        f"/threads/{urllib.parse.quote(gmail_thread_id, safe='')}?format=full", access_token
                    )
                    for message in sorted(gmail_thread.get("messages", []), key=lambda value: int(value["internalDate"])):
                        imported += self._save_message(user_id, account, message)
                run.messages_examined, run.messages_imported = examined, imported
                self.session.commit()
                logger.info("Gmail sync checkpoint account=%s run=%s examined=%s imported=%s", account.id, run.id, examined, imported)
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
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
            run.messages_examined, run.messages_imported = examined, imported
            logger.info("Gmail sync completed account=%s run=%s examined=%s imported=%s", account.id, run.id, examined, imported)
            return {"messages_examined": examined, "messages_imported": imported}
        except Exception as exc:
            run.status, run.completed_at, run.error_code = "failed", datetime.now(UTC), type(exc).__name__
            run.error_summary = str(exc)[:500]
            raise
        finally:
            self._release_sync_lock(account.id)

    def _acquire_sync_lock(self, account_id: uuid.UUID) -> bool:
        return bool(
            self.session.scalar(
                select(func.pg_try_advisory_lock(func.hashtextextended(str(account_id), 0)))
            )
        )

    def _release_sync_lock(self, account_id: uuid.UUID) -> None:
        self.session.scalar(select(func.pg_advisory_unlock(func.hashtextextended(str(account_id), 0))))

    def _recover_stale_runs(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> int:
        stale = list(
            self.session.scalars(
                select(SyncRun).where(
                    SyncRun.user_id == user_id,
                    SyncRun.gmail_account_id == account_id,
                    SyncRun.status == "running",
                )
            )
        )
        now = datetime.now(UTC)
        for run in stale:
            run.status = "failed"
            run.completed_at = now
            run.error_code = "interrupted"
            run.error_summary = "Recovered as abandoned after the sync process stopped."
        if stale:
            self.session.flush()
            logger.warning("Recovered %s abandoned Gmail sync run(s) account=%s", len(stale), account_id)
        return len(stale)

    def feed(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID | None = None,
        category: str | None = None,
        review: bool = False,
        decision: str | None = None,
    ) -> list[dict]:
        statement = (
            select(Classification, GmailThread, GmailAccount)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .where(Classification.user_id == user_id, Classification.is_current, GmailThread.is_in_inbox)
            .order_by(Classification.priority_score.desc(), GmailThread.latest_message_at.desc())
        )
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        if category:
            statement = statement.where(Classification.category == category)
        if review:
            statement = statement.where(Classification.priority_score.between(35, 79))
        return [
            self._feed_item(classification, thread, account)
            for classification, thread, account in self.session.execute(statement)
            if decision is None or _decision_bucket(classification.category, classification.priority_score) == decision
        ]

    def detail(
        self, *, user_id: uuid.UUID, thread_id: uuid.UUID, message_id: uuid.UUID | None = None
    ) -> dict | None:
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
        result["explanation"] = classification.explanation
        result["classifier_version"] = classification.classifier_version
        result["categories"] = sorted(CATEGORIES)
        result["gmail_url"] = f"https://mail.google.com/mail/u/0/#all/{urllib.parse.quote(thread.gmail_thread_id, safe='')}"
        messages = list(
            self.session.scalars(
                select(GmailMessage)
                .where(
                    GmailMessage.user_id == user_id,
                    GmailMessage.gmail_account_id == account.id,
                    GmailMessage.thread_id == thread.id,
                )
                .order_by(GmailMessage.gmail_internal_date, GmailMessage.id)
            )
        )
        related_messages = _related_conversation_messages(
            messages,
            self.session.scalars(
                select(GmailMessage).where(
                    GmailMessage.user_id == user_id,
                    GmailMessage.gmail_account_id == account.id,
                    GmailMessage.thread_id != thread.id,
                )
            ),
        )
        messages = sorted({message.id: message for message in [*messages, *related_messages]}.values(), key=lambda message: (message.gmail_internal_date, message.id))
        current_message_id = next((message.id for message in messages if message.id == message_id), messages[-1].id if messages else None)
        result["messages"] = [
            {
                "id": str(message.id),
                "thread_id": str(message.thread_id),
                "from": message.from_address,
                "subject": message.subject,
                "body": _display_body(message.body_text or message.snippet),
                "at": message.gmail_internal_date,
                "is_current": message.id == current_message_id,
            }
            for message in messages
        ]
        result["thread_intelligence"] = _thread_intelligence(
            messages=messages, explanation=classification.explanation, is_unread=thread.is_unread
        )
        return result

    def overview(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> dict:
        statement = (
            select(Classification.category, func.count())
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .where(Classification.user_id == user_id, Classification.is_current, GmailThread.is_in_inbox)
            .group_by(Classification.category)
        )
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        counts = {category: 0 for category in CATEGORIES}
        counts.update(dict(self.session.execute(statement).all()))
        safe = ("notification", "promotional_bulk", "personal_conversation", "unclear")
        return {
            "total_analyzed": sum(counts.values()),
            "categories": counts,
            "needs_attention": counts["action_required"] + counts["important_keep"],
            "opportunities": counts["opportunity"],
            "important": counts["important_keep"],
            "low_priority": self._count_current(user_id=user_id, account_id=account_id, categories=safe, max_priority=34),
            "promotional": counts["promotional_bulk"],
            "notifications": counts["notification"],
            "decisions": self._decision_counts(user_id=user_id, account_id=account_id),
        }

    def sender_groups(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> list[dict]:
        groups: dict[str, dict] = {}
        for classification, _, _, message in self._classified_thread_rows(user_id=user_id, account_id=account_id):
            sender = _sender_domain(message.from_address)
            if not sender:
                continue
            group = groups.setdefault(
                sender,
                {"sender": sender, "total": 0, "categories": {category: 0 for category in CATEGORIES}, "decisions": {DO: 0, CONSIDER: 0, CLEAN_UP: 0}},
            )
            group["total"] += 1
            group["categories"][classification.category] += 1
            group["decisions"][_decision_bucket(classification.category, classification.priority_score)] += 1
        return sorted(groups.values(), key=lambda group: (-group["total"], group["sender"]))

    def learned_preferences(self, *, user_id: uuid.UUID, account_id: uuid.UUID) -> list[dict]:
        feedback = [
            FeedbackSignal(
                sender_domain=item.sender_domain,
                original_category=item.original_category,
                corrected_category=item.corrected_category,
            )
            for item in self.session.scalars(
                select(ClassificationFeedback).where(
                    ClassificationFeedback.user_id == user_id,
                    ClassificationFeedback.gmail_account_id == account_id,
                )
            )
        ]
        preferences = []
        for domain, original_category in sorted({(item.sender_domain, item.original_category) for item in feedback}):
            adjusted = apply_feedback(
                ClassificationDecision(original_category, 0, 1.0, {}),
                sender_domain=domain,
                feedback=feedback,
            )
            if adjusted.category == original_category:
                continue
            count = sum(
                item.sender_domain == domain
                and item.original_category == original_category
                and item.corrected_category == adjusted.category
                for item in feedback
            )
            preferences.append(
                {
                    "domain": domain,
                    "original_category": original_category,
                    "learned_category": adjusted.category,
                    "correction_count": count,
                }
            )
        return sorted(preferences, key=lambda item: (-item["correction_count"], item["domain"]))

    def cleanup(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None = None) -> dict:
        candidates = {
            item["id"]: item
            for item in self.feed(user_id=user_id, account_id=account_id, decision=CLEAN_UP)
        }
        senders = {str(thread.id): _sender_domain(message.from_address) for _, thread, _, message in self._classified_thread_rows(user_id=user_id, account_id=account_id)}
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in candidates.values():
            sender = senders.get(item["id"], "")
            groups.setdefault((sender or "unknown-sender", item["category"]), []).append(item)
        return {
            "total_impact": len(candidates),
            "groups": [
                {"key": f"{sender}:{category}", "title": sender, "description": category.replace("_", " "), "items": items}
                for (sender, category), items in sorted(groups.items())
            ],
        }

    def _classified_thread_rows(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None) -> list[tuple]:
        statement = (
            select(Classification, GmailThread, GmailAccount, GmailMessage)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .join(GmailMessage, GmailMessage.thread_id == GmailThread.id)
            .where(Classification.user_id == user_id, Classification.is_current, GmailThread.is_in_inbox)
            .order_by(GmailThread.id, GmailMessage.gmail_internal_date.desc())
        )
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        latest: dict[uuid.UUID, tuple] = {}
        for row in self.session.execute(statement):
            latest.setdefault(row[1].id, row)
        return list(latest.values())

    def _decision_counts(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None) -> dict[str, int]:
        counts = {DO: 0, CONSIDER: 0, CLEAN_UP: 0}
        for classification, _, _, _ in self._classified_thread_rows(user_id=user_id, account_id=account_id):
            counts[_decision_bucket(classification.category, classification.priority_score)] += 1
        return counts

    def apply_thread_action(
        self, *, user_id: uuid.UUID, account_id: uuid.UUID, thread_ids: list[uuid.UUID], action: str
    ) -> int:
        account = self._account(user_id, account_id)
        threads = list(self.session.scalars(select(GmailThread).where(GmailThread.user_id == user_id, GmailThread.gmail_account_id == account_id, GmailThread.id.in_(thread_ids))))
        if len(threads) != len(set(thread_ids)):
            raise LookupError("One or more selected emails do not belong to this Gmail account.")
        token = self.token_store.get_refresh_token(gmail_account_id=account.id) if self.token_store else None
        if not token:
            raise RuntimeError("No token store is configured.")
        access_token = self._refresh_access_token(token)
        for thread in threads:
            if action == "delete":
                self._post(f"/threads/{thread.gmail_thread_id}/trash", access_token)
                thread.is_in_inbox = False
            else:
                labels = {"archive": {"removeLabelIds": ["INBOX"]}, "mark_read": {"removeLabelIds": ["UNREAD"]}, "mark_unread": {"addLabelIds": ["UNREAD"]}}[action]
                self._post(f"/threads/{thread.gmail_thread_id}/modify", access_token, labels)
                if action == "archive":
                    thread.is_in_inbox = False
                else:
                    thread.is_unread = action == "mark_unread"
            for message in self.session.scalars(select(GmailMessage).where(GmailMessage.thread_id == thread.id)):
                labels = set(message.label_ids)
                if action in {"archive", "delete"}:
                    labels.discard("INBOX")
                elif action == "mark_read":
                    labels.discard("UNREAD")
                else:
                    labels.add("UNREAD")
                message.label_ids = list(labels)
        return len(threads)

    def reply_to_thread(self, *, user_id: uuid.UUID, account_id: uuid.UUID, thread_id: uuid.UUID, body: str) -> None:
        account = self._account(user_id, account_id)
        thread = self.session.scalar(select(GmailThread).where(GmailThread.id == thread_id, GmailThread.user_id == user_id, GmailThread.gmail_account_id == account_id))
        if thread is None:
            raise LookupError("Email does not belong to this Gmail account.")
        message = self.session.scalar(select(GmailMessage).where(GmailMessage.thread_id == thread.id).order_by(GmailMessage.gmail_internal_date.desc()))
        if message is None:
            raise LookupError("Email has no message to reply to.")
        token = self.token_store.get_refresh_token(gmail_account_id=account.id) if self.token_store else None
        if not token:
            raise RuntimeError("No token store is configured.")
        recipient = parseaddr(message.from_address)[1]
        subject = message.subject or thread.subject_normalized or ""
        raw = base64.urlsafe_b64encode(f"To: {recipient}\r\nSubject: Re: {subject}\r\n\r\n{body}".encode()).decode().rstrip("=")
        self._post("/messages/send", self._refresh_access_token(token), {"raw": raw, "threadId": thread.gmail_thread_id})

    def correct_classification(
        self, *, user_id: uuid.UUID, thread_id: uuid.UUID, corrected_category: str
    ) -> dict | None:
        row = self.session.execute(
            select(Classification, GmailThread, GmailAccount)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .where(Classification.user_id == user_id, Classification.thread_id == thread_id, Classification.is_current)
        ).one_or_none()
        if row is None:
            return None
        current, thread, account = row
        original = self.session.scalar(
            select(Classification)
            .where(
                Classification.thread_id == thread.id,
                Classification.classifier_version == M5_1_CLASSIFIER_VERSION,
            )
            .order_by(Classification.created_at.desc())
        ) or current
        if corrected_category == current.category:
            return self._feed_item(current, thread, account)
        duplicate = self.session.scalar(
            select(ClassificationFeedback).where(
                ClassificationFeedback.user_id == user_id,
                ClassificationFeedback.thread_id == thread.id,
                ClassificationFeedback.original_category == original.category,
                ClassificationFeedback.corrected_category == corrected_category,
            )
        )
        if duplicate is not None:
            return self._feed_item(current, thread, account)
        message = self.session.scalar(
            select(GmailMessage)
            .where(GmailMessage.thread_id == thread.id, GmailMessage.user_id == user_id)
            .order_by(GmailMessage.gmail_internal_date.desc())
        )
        sender_address = message.from_address if message else "Unknown"
        self.session.add(
            ClassificationFeedback(
                user_id=user_id,
                gmail_account_id=account.id,
                thread_id=thread.id,
                message_id=message.id if message else None,
                original_category=original.category,
                corrected_category=corrected_category,
                classifier_version=original.classifier_version,
                sender_address=sender_address,
                sender_domain=_sender_domain(sender_address),
            )
        )
        decision = user_correction(
            ClassificationDecision(
                category=original.category,
                priority_score=original.priority_score,
                confidence=float(original.confidence),
                explanation=original.explanation,
            ),
            category=corrected_category,
        )
        current.is_current = False
        self.session.flush()
        replacement = Classification(
            user_id=user_id,
            gmail_account_id=account.id,
            thread_id=thread.id,
            category=decision.category,
            priority_score=decision.priority_score,
            confidence=decision.confidence,
            explanation=decision.explanation,
            source="local_feedback",
            classifier_version=FEEDBACK_CLASSIFIER_VERSION,
            is_current=True,
        )
        self.session.add(replacement)
        self.session.flush()
        return self._feed_item(replacement, thread, account)

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
        delivery_metadata = _delivery_metadata(headers)
        self.session.add(GmailMessage(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, gmail_message_id=raw["id"], gmail_internal_date=internal_date, from_address=headers.get("from", "Unknown"), to_addresses={"to": headers.get("to", "")}, cc_addresses={"cc": headers["cc"]} if headers.get("cc") else None, subject=headers.get("subject"), snippet=raw.get("snippet"), body_text=body, label_ids=raw.get("labelIds", []), delivery_metadata=delivery_metadata, has_attachments=False))
        thread.message_count += 1
        decision = classify_thread_m5_1(
            ThreadSnapshot(
                subject=headers.get("subject", ""),
                body=body,
                from_address=headers.get("from", "Unknown"),
                to_addresses=headers.get("to", ""),
                cc_addresses=headers.get("cc", ""),
                account_email=account.gmail_email,
                label_ids=tuple(raw.get("labelIds", [])),
                latest_message_at=internal_date,
                message_count=thread.message_count,
                is_in_inbox=thread.is_in_inbox,
                is_unread=thread.is_unread,
                delivery_metadata=delivery_metadata,
            )
        )
        current = self.session.scalar(
            select(Classification)
            .where(
                Classification.thread_id == thread.id,
                Classification.user_id == user_id,
                Classification.gmail_account_id == account.id,
                Classification.is_current,
            )
            .with_for_update()
        )
        if current:
            current.is_current = False
            self.session.flush()
        base = Classification(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, category=decision.category, priority_score=decision.priority_score, confidence=decision.confidence, explanation=decision.explanation, source="local_deterministic", classifier_version=M5_1_CLASSIFIER_VERSION, is_current=True)
        adjusted = self._apply_feedback(
            user_id=user_id,
            account_id=account.id,
            sender_address=headers.get("from", "Unknown"),
            decision=decision,
        )
        if adjusted.category == decision.category:
            self.session.add(base)
        else:
            base.is_current = False
            self.session.add(base)
            self.session.add(Classification(user_id=user_id, gmail_account_id=account.id, thread_id=thread.id, category=adjusted.category, priority_score=adjusted.priority_score, confidence=adjusted.confidence, explanation=adjusted.explanation, source="local_feedback", classifier_version=FEEDBACK_CLASSIFIER_VERSION, is_current=True))
        # SessionLocal disables autoflush; make the one-current-row handoff
        # visible before the next message in the same thread is processed.
        self.session.flush()
        return 1

    def _apply_feedback(
        self, *, user_id: uuid.UUID, account_id: uuid.UUID, sender_address: str, decision: ClassificationDecision
    ) -> ClassificationDecision:
        sender_domain = _sender_domain(sender_address)
        feedback = [
            FeedbackSignal(
                sender_domain=item.sender_domain,
                original_category=item.original_category,
                corrected_category=item.corrected_category,
            )
            for item in self.session.scalars(
                select(ClassificationFeedback).where(
                    ClassificationFeedback.user_id == user_id,
                    ClassificationFeedback.gmail_account_id == account_id,
                    ClassificationFeedback.sender_domain == sender_domain,
                    ClassificationFeedback.original_category == decision.category,
                )
            )
        ]
        return apply_feedback(decision, sender_domain=sender_domain, feedback=feedback)

    def _count_current(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None, categories: tuple[str, ...], max_priority: int) -> int:
        statement = select(func.count()).select_from(Classification).join(GmailThread, Classification.thread_id == GmailThread.id).where(Classification.user_id == user_id, Classification.is_current, GmailThread.is_in_inbox, Classification.category.in_(categories), Classification.priority_score <= max_priority)
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        return self.session.scalar(statement) or 0

    def _safe_low_priority(self, *, user_id: uuid.UUID, account_id: uuid.UUID | None) -> list[dict]:
        statement = (
            select(Classification, GmailThread, GmailAccount)
            .join(GmailThread, Classification.thread_id == GmailThread.id)
            .join(GmailAccount, Classification.gmail_account_id == GmailAccount.id)
            .where(Classification.user_id == user_id, Classification.is_current, GmailThread.is_in_inbox, Classification.priority_score <= 34, Classification.category.not_in(("action_required", "important_keep", "otp_verification")))
            .order_by(Classification.priority_score.asc(), GmailThread.latest_message_at.desc())
        )
        if account_id:
            statement = statement.where(Classification.gmail_account_id == account_id)
        return [self._feed_item(classification, thread, account) for classification, thread, account in self.session.execute(statement)]

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

    def _post(self, path: str, access_token: str, payload: dict | None = None) -> dict:
        return _request(f"{GMAIL_API}{path}", data=json.dumps(payload or {}).encode(), headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})

    @staticmethod
    def _feed_item(classification: Classification, thread: GmailThread, account: GmailAccount) -> dict:
        return {"id": str(thread.id), "account_id": str(account.id), "account": account.gmail_email, "subject": thread.subject_normalized or "Untitled email", "snippet": thread.snippet or "", "category": classification.category, "decision": _decision_bucket(classification.category, classification.priority_score), "priority": classification.priority_score, "confidence": float(classification.confidence), "summary": classification.explanation.get("summary", ""), "at": thread.latest_message_at, "is_unread": thread.is_unread}


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


def _delivery_metadata(headers: dict[str, str]) -> dict[str, object]:
    """Persist only delivery facts needed by the local classifier, never raw headers."""
    precedence = headers.get("precedence", "").lower()
    return {
        "is_list_delivery": bool(headers.get("list-id") or headers.get("list-unsubscribe")),
        "has_unsubscribe": bool(headers.get("list-unsubscribe")),
        "bulk_precedence": precedence in {"bulk", "list", "junk"},
        "reply_to_present": bool(headers.get("reply-to")),
    }


def _sender_domain(address: str) -> str:
    """Normalize the sender domain without retaining extra header information."""
    return parseaddr(address)[1].rsplit("@", 1)[-1].lower() if "@" in parseaddr(address)[1] else ""


_TOPIC_STOPWORDS = frozenset(
    {
        "action", "application", "confirmation", "first", "from", "important", "pending",
        "participation", "received", "registration", "required", "round", "update", "urgent", "with", "your",
    }
)


def _related_conversation_messages(
    messages: list[GmailMessage], candidates: list[GmailMessage] | object
) -> list[GmailMessage]:
    native = list(messages)
    return [
        candidate
        for candidate in candidates
        if any(_same_conversation_topic(message, candidate) for message in native)
    ]


def _same_conversation_topic(left: GmailMessage, right: GmailMessage) -> bool:
    if _sender_domain(left.from_address) != _sender_domain(right.from_address):
        return False
    left_terms, right_terms = _topic_terms(left.subject), _topic_terms(right.subject)
    return len(left_terms & right_terms) >= 2


def _topic_terms(subject: str | None) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]{3,}", unescape(subject or "").lower())
        if term not in _TOPIC_STOPWORDS
    }


class _EmailHtmlRenderer(HTMLParser):
    _allowed_tags: ClassVar[frozenset[str]] = frozenset({"a", "b", "br", "em", "i", "li", "ol", "p", "strong", "u", "ul"})
    _ignored_tags: ClassVar[frozenset[str]] = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0
        self.anchor_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._ignored_tags:
            self.ignored += 1
        elif not self.ignored and tag in self._allowed_tags:
            if tag == "a":
                href = dict(attrs).get("href") or ""
                if urlparse(href).scheme in {"http", "https", "mailto"}:
                    self.parts.append(f'<a href="{escape(href, quote=True)}" target="_blank" rel="noreferrer">')
                    self.anchor_tags.append("a")
                else:
                    self.parts.append("<span>")
                    self.anchor_tags.append("span")
            else:
                self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_tags:
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored and tag in self._allowed_tags:
            self.parts.append(
                f"</{self.anchor_tags.pop() if self.anchor_tags else 'span'}>"
                if tag == "a"
                else f"</{tag}>"
            )

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            text = re.sub(r"[ \t]+", " ", re.sub(r"(?m)^\s*```[^\n]*$", "", unescape(data)))
            self.parts.append(escape(text))


def _display_body(body: str | None) -> str:
    """Return safe, compact HTML while preserving the raw Gmail MIME body in storage."""
    body = body or ""
    if not re.search(r"<\s*[a-z][^>]*>", body, re.IGNORECASE):
        return _plain_text_html(body)
    renderer = _EmailHtmlRenderer()
    renderer.feed(body)
    renderer.close()
    return "".join(renderer.parts).strip() or _plain_text_html(body)


def _plain_text_html(text: str) -> str:
    paragraphs = [" ".join(line.strip() for line in paragraph.splitlines() if line.strip()) for paragraph in re.split(r"\n\s*\n", _clean_display_text(text))]
    return "".join(f"<p>{_linkify(paragraph)}</p>" for paragraph in paragraphs if paragraph)


def _clean_display_text(text: str) -> str:
    text = re.sub(r"(?m)^\s*```[^\n]*$", "", unescape(text))
    return re.sub(r"[ \t]+", " ", text).strip()


def _linkify(text: str) -> str:
    parts = re.split(r"(https?://[^\s<]+)", text)
    return "".join(
        f'<a href="{escape(part, quote=True)}" target="_blank" rel="noreferrer">{escape(part)}</a>'
        if part.startswith(("http://", "https://"))
        else escape(part)
        for part in parts
    )


def _thread_intelligence(*, messages: list[GmailMessage], explanation: dict, is_unread: bool) -> dict:
    latest = messages[-1] if messages else None
    reasons = explanation.get("reasons", [])
    action = next(
        (
            reason["label"]
            for reason in reasons
            if reason.get("signal") in {"requested_action", "confirmation_required"}
        ),
        None,
    )
    return {
        "state": f"{len(messages)} message{'s' if len(messages) != 1 else ''} in this Gmail conversation"
        + (" · unread" if is_unread else ""),
        "latest_event": (latest.subject or latest.snippet) if latest else None,
        "open_action": action,
        "explicit_deadline": _explicit_deadline(messages),
    }


def _explicit_deadline(messages: list[GmailMessage]) -> str | None:
    pattern = re.compile(
        r"\b(?:deadline|due(?:\s+on)?)(?:\s+is)?\s*[:\-]?\s*[^.!\n]+"
        r"|\bby\s+(?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(?:st|nd|rd|th)?\b[^.!\n]*)",
        re.IGNORECASE,
    )
    for message in reversed(messages):
        if match := pattern.search(f"{message.subject or ''}\n{message.body_text or message.snippet or ''}"):
            return match.group(0).strip()
    return None


def _decision_bucket(category: str, priority_score: int) -> str:
    if category == "action_required":
        return DO
    if category in {"opportunity", "important_keep", "personal_conversation"}:
        return CONSIDER
    return CLEAN_UP
