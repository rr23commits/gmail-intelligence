from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.classification.feedback import validate_corrected_category
from app.classification.m5 import CATEGORIES
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db_session
from app.models.gmail_data import SyncRun
from app.repositories.gmail_account_repository import GmailAccountRepository
from app.repositories.user_repository import UserRepository
from app.security.macos_keychain_token_store import MacOSKeychainTokenStore
from app.services.gmail_account_service import GmailAccountService
from app.services.gmail_intelligence_service import (
    CLEAN_UP,
    CONSIDER,
    DO,
    GmailApiError,
    GmailIntelligenceService,
    SyncAlreadyRunning,
    _request,
)
from app.services.local_owner_service import LocalOwnerService


class ClassificationCorrection(BaseModel):
    corrected_category: str


class ThreadAction(BaseModel):
    action: str
    thread_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class ReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class TaskStatusUpdate(BaseModel):
    status: str


class LocalLogin(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


logger = logging.getLogger(__name__)
SESSION_COOKIE = "gmail_intelligence_session"
OAUTH_STATE_COOKIE = "gmail_intelligence_oauth_state"


class RateLimiter:
    """Small local-process guard for the development API."""

    # ponytail: in-memory limits reset on restart; use Redis/shared storage when scaling beyond one process.
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, client: str, bucket: str, limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[(client, bucket)]
            while hits and hits[0] <= now - window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


def _record_sync_failure(*, user_id: uuid.UUID, account_id: uuid.UUID, error: Exception) -> None:
    """Keep a user-visible failure record after the import transaction rolls back."""
    with SessionLocal() as log_session:
        log_session.add(
            SyncRun(
                user_id=user_id,
                gmail_account_id=account_id,
                mode="manual",
                status="failed",
                completed_at=datetime.now(UTC),
                error_code=type(error).__name__,
                error_summary=str(error)[:500],
            )
        )
        log_session.commit()


async def provision_local_owner() -> None:
    """Ensure the local V1 owner exists after the database schema is migrated."""

    from app.db.session import SessionLocal
    from app.repositories.user_repository import UserRepository

    with SessionLocal() as session:
        LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()


def create_app(*, provision_owner_on_startup: bool = True) -> FastAPI:
    limiter = RateLimiter()

    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if provision_owner_on_startup:
            await provision_local_owner()
        yield

    app = FastAPI(title="Gmail Intelligence API", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[get_settings().frontend_url],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    @app.middleware("http")
    async def limit_requests(request: Request, call_next):
        client = request.client.host if request.client else "unknown"
        limit = 10 if request.url.path.endswith(("/sync", "/reply", "/threads/action")) else 60
        if not limiter.allow(client, request.url.path, limit):
            return JSONResponse({"detail": "Too many requests."}, status_code=429)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    def owner(request: Request, session: Session = Depends(get_db_session)):
        claims = _read_session(request.cookies.get(SESSION_COOKIE))
        if claims is None:
            raise HTTPException(401, "Sign in required.")
        result = LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()
        if claims["user_id"] != str(result.id):
            raise HTTPException(401, "Invalid session.")
        return result

    @app.get("/api/v1/auth/session", tags=["auth"])
    def session_status(local_owner=Depends(owner)) -> dict[str, str]:
        return {"email": local_owner.email or ""}

    @app.post("/api/v1/auth/login", tags=["auth"])
    def login(credentials: LocalLogin, session: Session = Depends(get_db_session)) -> Response:
        settings = get_settings()
        if not settings.local_auth_password or not hmac.compare_digest(
            credentials.password, settings.local_auth_password
        ):
            raise HTTPException(401, "Invalid password.")
        local_owner = LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()
        response = Response(status_code=204)
        response.set_cookie(
            SESSION_COOKIE,
            _sign_session(str(local_owner.id)),
            httponly=True,
            secure=settings.app_env != "development",
            samesite="lax",
            max_age=settings.session_ttl_seconds,
        )
        return response

    @app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
    def logout() -> Response:
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.post("/api/v1/auth/gmail/start", tags=["gmail"])
    def start_gmail_connection(local_owner=Depends(owner)) -> Response:
        settings = get_settings()
        if not settings.google_oauth_client_id or not settings.app_secret_key:
            raise HTTPException(503, "Google OAuth is not configured.")
        nonce = secrets.token_urlsafe(32)
        response = JSONResponse({"authorization_url": _gmail_authorization_url(str(local_owner.id), nonce)})
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            nonce,
            httponly=True,
            secure=settings.app_env != "development",
            samesite="lax",
            max_age=settings.oauth_state_ttl_seconds,
        )
        return response

    @app.get("/api/v1/auth/gmail/callback", tags=["gmail"])
    def gmail_callback(
        code: str,
        state: str,
        request: Request,
        scope: str | None = None,
        session: Session = Depends(get_db_session),
    ) -> RedirectResponse:
        try:
            claims = _read_state(state)
            nonce = request.cookies.get(OAUTH_STATE_COOKIE)
            if not nonce or not hmac.compare_digest(nonce, claims["nonce"]):
                raise ValueError("Invalid OAuth state.")
            user_id = uuid.UUID(claims["user_id"])
            if scope is not None and GMAIL_READONLY_SCOPE not in scope.split():
                raise GmailApiError("Gmail permission was not granted. Connect again and allow Gmail read access.")
            settings = get_settings()
            exchange = _request("https://oauth2.googleapis.com/token", data=urllib.parse.urlencode({"code": code, "client_id": settings.google_oauth_client_id, "client_secret": settings.google_oauth_client_secret, "redirect_uri": settings.google_oauth_redirect_uri, "grant_type": "authorization_code"}).encode())
            if exchange.get("scope") and GMAIL_READONLY_SCOPE not in exchange["scope"].split():
                raise GmailApiError("Google returned a token without Gmail read access.")
            refresh_token = exchange.get("refresh_token")
            if not refresh_token:
                raise GmailApiError("Google did not return a refresh token. Reconnect and grant consent.")
            profile = _request("https://gmail.googleapis.com/gmail/v1/users/me/profile", headers={"Authorization": f"Bearer {exchange['access_token']}"})
            account = GmailAccountService(GmailAccountRepository(session)).register_account_metadata(user_id=user_id, gmail_email=profile["emailAddress"], gmail_profile_id=profile["emailAddress"], display_name=profile["emailAddress"].split("@", 1)[0])
            MacOSKeychainTokenStore().save_refresh_token(gmail_account_id=account.id, refresh_token=refresh_token)
            session.commit()
            response = RedirectResponse(f"{settings.frontend_url}/accounts?connected=1")
        except (GmailApiError, ValueError, KeyError):
            session.rollback()
            response = RedirectResponse(f"{get_settings().frontend_url}/accounts?error=connection_failed")
        response.delete_cookie(OAUTH_STATE_COOKIE)
        return response

    @app.get("/api/v1/accounts", tags=["gmail"])
    def accounts(local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> list[dict]:
        return [{"id": str(account.id), "email": account.gmail_email, "name": account.display_name, "status": account.status, "last_synced_at": account.last_successful_sync_at} for account in GmailAccountService(GmailAccountRepository(session)).list_accounts(user_id=local_owner.id)]

    @app.post("/api/v1/accounts/{account_id}/sync", tags=["gmail"])
    def sync(account_id: uuid.UUID, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> dict:
        try:
            result = GmailIntelligenceService(session, MacOSKeychainTokenStore()).sync(user_id=local_owner.id, account_id=account_id)
            session.commit()
            return result
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except SyncAlreadyRunning as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            session.rollback()
            _record_sync_failure(user_id=local_owner.id, account_id=account_id, error=exc)
            logger.exception("Gmail sync failed account=%s", account_id)
            raise HTTPException(502, "Sync failed. Open Sync log for details.") from exc

    @app.get("/api/v1/accounts/{account_id}/sync-runs", tags=["gmail"])
    def sync_runs(account_id: uuid.UUID, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> list[dict]:
        try:
            return GmailIntelligenceService(session).sync_runs(user_id=local_owner.id, account_id=account_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/v1/accounts/{account_id}/threads/action", tags=["gmail"])
    def thread_action(
        account_id: uuid.UUID,
        request: ThreadAction,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        if request.action not in {"archive", "delete", "mark_read", "mark_unread"} or not request.thread_ids:
            raise HTTPException(422, "A supported action and at least one thread are required.")
        try:
            count = GmailIntelligenceService(session, MacOSKeychainTokenStore()).apply_thread_action(
                user_id=local_owner.id,
                account_id=account_id,
                thread_ids=request.thread_ids,
                action=request.action,
            )
            session.commit()
            return {"updated": count}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (GmailApiError, RuntimeError) as exc:
            session.rollback()
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/v1/accounts/{account_id}/threads/{thread_id}/reply", tags=["gmail"])
    def reply_to_thread(
        account_id: uuid.UUID,
        thread_id: uuid.UUID,
        request: ReplyRequest,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        if not request.body.strip():
            raise HTTPException(422, "Reply body is required.")
        try:
            GmailIntelligenceService(session, MacOSKeychainTokenStore()).reply_to_thread(user_id=local_owner.id, account_id=account_id, thread_id=thread_id, body=request.body.strip())
            return {"sent": True}
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (GmailApiError, RuntimeError) as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.delete("/api/v1/accounts/{account_id}", status_code=204, tags=["gmail"])
    def disconnect(account_id: uuid.UUID, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> None:
        account = GmailAccountRepository(session).get_for_user(user_id=local_owner.id, account_id=account_id)
        if account is None:
            raise HTTPException(404, "Gmail account not found.")
        MacOSKeychainTokenStore().delete_refresh_token(gmail_account_id=account.id)
        GmailAccountRepository(session).delete(account)
        session.commit()

    @app.get("/api/v1/intelligence", tags=["intelligence"])
    def intelligence(
        account_id: uuid.UUID | None = None,
        category: str | None = None,
        review: bool = False,
        decision: str | None = None,
        limit: int = 100,
        offset: int = 0,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> list[dict]:
        if category is not None and category not in CATEGORIES:
            raise HTTPException(422, "category must be a canonical M5 category.")
        if category is not None and review:
            raise HTTPException(422, "review is a priority view and cannot be combined with category.")
        if decision is not None and decision not in {DO, CONSIDER, CLEAN_UP}:
            raise HTTPException(422, "decision must be do, consider, or clean_up.")
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, "limit must be 1–100 and offset must not be negative.")
        return GmailIntelligenceService(session).feed(
            user_id=local_owner.id,
            account_id=account_id,
            category=category,
            review=review,
            decision=decision,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/intelligence/{thread_id:uuid}", tags=["intelligence"])
    def intelligence_detail(
        thread_id: uuid.UUID,
        message_id: uuid.UUID | None = None,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        result = GmailIntelligenceService(session).detail(
            user_id=local_owner.id, thread_id=thread_id, message_id=message_id
        )
        if result is None:
            raise HTTPException(404, "Intelligence item not found.")
        return result

    @app.post("/api/v1/accounts/{account_id}/tasks/{task_id}/status", tags=["intelligence"])
    def task_status(
        account_id: uuid.UUID,
        task_id: uuid.UUID,
        update: TaskStatusUpdate,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        if update.status not in {"open", "done", "snoozed"}:
            raise HTTPException(422, "status must be open, done, or snoozed.")
        result = GmailIntelligenceService(session).update_task_status(
            user_id=local_owner.id,
            account_id=account_id,
            task_id=task_id,
            status=update.status,
        )
        if result is None:
            raise HTTPException(404, "Task not found.")
        session.commit()
        return result

    @app.get("/api/v1/intelligence/overview", tags=["intelligence"])
    def intelligence_overview(
        account_id: uuid.UUID | None = None,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        return GmailIntelligenceService(session).overview(user_id=local_owner.id, account_id=account_id)

    @app.get("/api/v1/intelligence/senders", tags=["intelligence"])
    def intelligence_senders(
        account_id: uuid.UUID | None = None,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> list[dict]:
        return GmailIntelligenceService(session).sender_groups(user_id=local_owner.id, account_id=account_id)

    @app.get("/api/v1/intelligence/learned-preferences", tags=["intelligence"])
    def learned_preferences(
        account_id: uuid.UUID,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> list[dict]:
        if GmailAccountRepository(session).get_for_user(user_id=local_owner.id, account_id=account_id) is None:
            raise HTTPException(404, "Gmail account not found.")
        return GmailIntelligenceService(session).learned_preferences(
            user_id=local_owner.id, account_id=account_id
        )

    @app.get("/api/v1/intelligence/cleanup", tags=["intelligence"])
    def intelligence_cleanup(
        account_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, "limit must be 1–100 and offset must not be negative.")
        return GmailIntelligenceService(session).cleanup(user_id=local_owner.id, account_id=account_id, limit=limit, offset=offset)

    @app.post("/api/v1/intelligence/{thread_id}/classification-feedback", tags=["intelligence"])
    def classification_feedback(
        thread_id: uuid.UUID,
        correction: ClassificationCorrection,
        local_owner=Depends(owner),
        session: Session = Depends(get_db_session),
    ) -> dict:
        try:
            validate_corrected_category(correction.corrected_category)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        result = GmailIntelligenceService(session).correct_classification(
            user_id=local_owner.id,
            thread_id=thread_id,
            corrected_category=correction.corrected_category,
        )
        if result is None:
            raise HTTPException(404, "Intelligence item not found.")
        session.commit()
        return result

    @app.get("/api/v1/dashboard", tags=["intelligence"])
    def dashboard(account_id: uuid.UUID | None = None, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> dict:
        if account_id and GmailAccountRepository(session).get_for_user(user_id=local_owner.id, account_id=account_id) is None:
            raise HTTPException(404, "Gmail account not found.")
        return GmailIntelligenceService(session).dashboard(user_id=local_owner.id, account_id=account_id)

    return app


app = create_app()

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def _sign_payload(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(get_settings().app_secret_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _read_payload(value: str) -> dict[str, object]:
    try:
        payload, signature = value.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid signed value.") from exc
    expected = hmac.new(get_settings().app_secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise TypeError("Invalid signed value.")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=="))
    if not isinstance(decoded, dict):
        raise TypeError("Invalid signed value.")
    return decoded


def _sign_session(user_id: str) -> str:
    return _sign_payload({"user_id": user_id, "expires_at": int(time.time()) + get_settings().session_ttl_seconds})


def _read_session(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    try:
        claims = _read_payload(value)
        if not isinstance(claims.get("user_id"), str) or int(claims["expires_at"]) < time.time():
            return None
        return {"user_id": claims["user_id"]}
    except (TypeError, ValueError, KeyError):
        return None


def _sign_state(user_id: str, nonce: str) -> str:
    return _sign_payload(
        {
            "user_id": user_id,
            "nonce": nonce,
            "expires_at": int(time.time()) + get_settings().oauth_state_ttl_seconds,
        }
    )


def _gmail_authorization_url(user_id: str, nonce: str = "test-nonce") -> str:
    settings = get_settings()
    query = urllib.parse.urlencode(
        {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": f"{GMAIL_READONLY_SCOPE} {GMAIL_MODIFY_SCOPE} {GMAIL_SEND_SCOPE}",
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": _sign_state(user_id, nonce),
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _read_state(state: str) -> dict[str, str]:
    try:
        claims = _read_payload(state)
        if (
            not isinstance(claims.get("user_id"), str)
            or not isinstance(claims.get("nonce"), str)
            or int(claims["expires_at"]) < time.time()
        ):
            raise ValueError("Invalid OAuth state.")
        return {"user_id": claims["user_id"], "nonce": claims["nonce"]}
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Invalid OAuth state.") from exc
