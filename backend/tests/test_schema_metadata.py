import app.models  # noqa: F401
from app.db.base import Base


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "classifications",
        "classification_feedback",
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


def test_m5_metadata_and_score_constraints_are_registered() -> None:
    message_columns = Base.metadata.tables["gmail_messages"].columns
    classification_constraints = Base.metadata.tables["classifications"].constraints

    assert "delivery_metadata" in message_columns
    assert {"ck_classifications_priority_range", "ck_classifications_confidence_range"} <= {
        getattr(constraint, "name", None) for constraint in classification_constraints
    }
