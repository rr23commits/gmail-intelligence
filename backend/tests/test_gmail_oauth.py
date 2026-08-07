from urllib.parse import parse_qs, urlparse

from app.main import GMAIL_READONLY_SCOPE, _gmail_authorization_url


def test_gmail_authorization_request_escalates_an_existing_openid_grant(monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "google_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "app_secret_key", "test-secret")

    query = parse_qs(urlparse(_gmail_authorization_url("00000000-0000-0000-0000-000000000000")).query)

    assert query["scope"] == [GMAIL_READONLY_SCOPE]
    assert query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"]
