from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.parse
import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db_session
from app.repositories.gmail_account_repository import GmailAccountRepository
from app.repositories.user_repository import UserRepository
from app.security.macos_keychain_token_store import MacOSKeychainTokenStore
from app.services.gmail_account_service import GmailAccountService
from app.services.gmail_intelligence_service import (
    GmailApiError,
    GmailIntelligenceService,
    _request,
)
from app.services.local_owner_service import LocalOwnerService


async def provision_local_owner() -> None:
    """Ensure the local V1 owner exists after the database schema is migrated."""

    from app.db.session import SessionLocal
    from app.repositories.user_repository import UserRepository

    with SessionLocal() as session:
        LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()


def create_app(*, provision_owner_on_startup: bool = True) -> FastAPI:
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
    )

    @app.get("/health", tags=["system"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    def owner(session: Session = Depends(get_db_session)):
        result = LocalOwnerService(UserRepository(session)).ensure_owner()
        session.commit()
        return result

    @app.post("/api/v1/auth/gmail/start", tags=["gmail"])
    def start_gmail_connection(local_owner=Depends(owner)) -> dict[str, str]:
        settings = get_settings()
        if not settings.google_oauth_client_id or not settings.app_secret_key:
            raise HTTPException(503, "Google OAuth is not configured.")
        return {"authorization_url": _gmail_authorization_url(str(local_owner.id))}

    @app.get("/api/v1/auth/gmail/callback", tags=["gmail"])
    def gmail_callback(
        code: str, state: str, scope: str | None = None, session: Session = Depends(get_db_session)
    ) -> RedirectResponse:
        try:
            user_id = uuid.UUID(_read_state(state))
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
            return RedirectResponse(f"{settings.frontend_url}/accounts?connected=1")
        except (GmailApiError, ValueError, KeyError) as exc:
            session.rollback()
            return RedirectResponse(f"{get_settings().frontend_url}/accounts?error={urllib.parse.quote(str(exc))}")

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
        except (GmailApiError, RuntimeError) as exc:
            session.rollback()
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
    def intelligence(account_id: uuid.UUID | None = None, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> list[dict]:
        return GmailIntelligenceService(session).feed(user_id=local_owner.id, account_id=account_id)

    @app.get("/api/v1/intelligence/{thread_id}", tags=["intelligence"])
    def intelligence_detail(thread_id: uuid.UUID, local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> dict:
        result = GmailIntelligenceService(session).detail(user_id=local_owner.id, thread_id=thread_id)
        if result is None:
            raise HTTPException(404, "Intelligence item not found.")
        return result

    @app.get("/api/v1/dashboard", tags=["intelligence"])
    def dashboard(local_owner=Depends(owner), session: Session = Depends(get_db_session)) -> dict:
        feed = GmailIntelligenceService(session).feed(user_id=local_owner.id)
        return {"items": feed[:5], "action_required": sum(item["priority"] >= 70 for item in feed), "accounts": len(GmailAccountService(GmailAccountRepository(session)).list_accounts(user_id=local_owner.id))}

    return app


app = create_app()

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def _sign_state(user_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"user_id": user_id}).encode()).decode().rstrip("=")
    signature = hmac.new(get_settings().app_secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _gmail_authorization_url(user_id: str) -> str:
    settings = get_settings()
    query = urllib.parse.urlencode(
        {
            "client_id": settings.google_oauth_client_id,
            "redirect_uri": settings.google_oauth_redirect_uri,
            "response_type": "code",
            "scope": GMAIL_READONLY_SCOPE,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": _sign_state(user_id),
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _read_state(state: str) -> str:
    try:
        payload, signature = state.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid OAuth state.") from exc
    expected = hmac.new(get_settings().app_secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid OAuth state.")
    return json.loads(base64.urlsafe_b64decode(payload + "=="))["user_id"]
