import app.models  # noqa: F401
from app.db.base import Base


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "classifications",
        "feedback_events",
        "gmail_accounts",
        "gmail_messages",
        "gmail_oauth_credentials",
        "gmail_sync_states",
        "gmail_threads",
        "recommendations",
        "sync_runs",
        "users",
    }


def test_oauth_metadata_table_cannot_store_tokens() -> None:
    columns = Base.metadata.tables["gmail_oauth_credentials"].columns.keys()

    assert "refresh_token" not in columns
    assert "refresh_token_ciphertext" not in columns
    assert "access_token" not in columns
    assert "access_token_ciphertext" not in columns
    assert {"credential_store", "credential_reference", "granted_scopes"} <= set(columns)


def test_gmail_thread_and_message_ids_are_account_scoped() -> None:
    thread_constraints = Base.metadata.tables["gmail_threads"].constraints
    message_constraints = Base.metadata.tables["gmail_messages"].constraints

    assert any(
        getattr(constraint, "name", None) == "uq_threads_account_gmail_id" for constraint in thread_constraints
    )
    assert any(
        getattr(constraint, "name", None) == "uq_messages_account_gmail_id" for constraint in message_constraints
    )
