import app.models  # noqa: F401
from app.db.base import Base


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "classifications",
        "feedback_events",
        "gmail_accounts",
        "gmail_messages",
        "gmail_sync_states",
        "gmail_threads",
        "recommendations",
        "sync_runs",
        "users",
    }


def test_no_oauth_credentials_table_is_registered() -> None:
    assert "gmail_oauth_credentials" not in Base.metadata.tables


def test_gmail_thread_and_message_ids_are_account_scoped() -> None:
    thread_constraints = Base.metadata.tables["gmail_threads"].constraints
    message_constraints = Base.metadata.tables["gmail_messages"].constraints

    assert any(
        getattr(constraint, "name", None) == "uq_threads_account_gmail_id" for constraint in thread_constraints
    )
    assert any(
        getattr(constraint, "name", None) == "uq_messages_account_gmail_id" for constraint in message_constraints
    )
