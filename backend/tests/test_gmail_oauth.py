from urllib.parse import parse_qs, urlparse

from app.main import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    _gmail_authorization_url,
    _read_session,
    _read_state,
    _sign_session,
    _sign_state,
)


def test_gmail_authorization_request_escalates_an_existing_openid_grant(monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "app_secret_key", "test-secret")

    query = parse_qs(urlparse(_gmail_authorization_url("00000000-0000-0000-0000-000000000000")).query)

    assert query["scope"] == [f"{GMAIL_READONLY_SCOPE} {GMAIL_MODIFY_SCOPE} {GMAIL_SEND_SCOPE}"]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"]


def test_signed_session_and_oauth_state_expire_and_preserve_the_bound_values(monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "app_secret_key", "test-secret")
    monkeypatch.setattr(settings, "session_ttl_seconds", 60)
    monkeypatch.setattr(settings, "oauth_state_ttl_seconds", 60)

    assert _read_session(_sign_session("user-id")) == {"user_id": "user-id"}
    assert _read_state(_sign_state("user-id", "nonce")) == {"user_id": "user-id", "nonce": "nonce"}

    monkeypatch.setattr(settings, "session_ttl_seconds", -1)
    monkeypatch.setattr(settings, "oauth_state_ttl_seconds", -1)
    assert _read_session(_sign_session("user-id")) is None
    try:
        _read_state(_sign_state("user-id", "nonce"))
    except ValueError:
        pass
    else:
        raise AssertionError("expired OAuth state was accepted")
