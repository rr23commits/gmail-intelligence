from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.classification.m5 import CATEGORIES, ThreadSnapshot, classify_thread, classify_thread_m5_1

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "m5_threads.json").read_text())


def snapshot(case: dict) -> ThreadSnapshot:
    return ThreadSnapshot(
        subject=case["subject"],
        body=case["body"],
        from_address=case["from"],
        to_addresses=case["to"],
        cc_addresses="",
        account_email="user@example.test",
        label_ids=("INBOX", "UNREAD"),
        latest_message_at=datetime(2026, 8, 7, tzinfo=UTC),
        message_count=1,
        is_in_inbox=True,
        is_unread=True,
        delivery_metadata=case["metadata"],
    )


@pytest.mark.parametrize("case", FIXTURES, ids=lambda case: case["name"])
def test_contextual_fixture_categories_are_deterministic(case: dict) -> None:
    first = classify_thread(snapshot(case), now=datetime(2026, 8, 7, tzinfo=UTC))
    second = classify_thread(snapshot(case), now=datetime(2026, 8, 7, tzinfo=UTC))

    assert first == second
    assert first.category == case["category"]
    assert first.category in CATEGORIES
    assert 0 <= first.priority_score <= 100
    assert 0 <= first.confidence <= 1
    assert first.explanation["category"]["selected"] == first.category
    assert first.explanation["reasons"]


def test_time_and_financial_signals_do_not_create_extra_categories() -> None:
    categories = {classify_thread(snapshot(case)).category for case in FIXTURES}

    assert categories == CATEGORIES
    assert "financial" not in categories
    assert "time_sensitive" not in categories


@pytest.mark.parametrize(
    ("subject", "body", "sender", "expected"),
    [
        (
            "Your verification code",
            "Your security code is 123456 and expires in 10 minutes.",
            "security@bank.example.test",
            "otp_verification",
        ),
        (
            "July product launches",
            "<style>.login{width:2026px}</style> Sign in to learn more: https://example.test/20261234",
            "hello@product.example.test",
            "notification",
        ),
        (
            "Internships picked for you",
            "Apply now for jobs and internships that match your skills.",
            "noreply@unstop.news",
            "opportunity",
        ),
        (
            "Your Top Job matches",
            "Your job matches include an opportunity to apply. Account preferences are available online.",
            "noreply@jobright.ai",
            "opportunity",
        ),
        (
            "India's space college broke its bond with ISRO",
            "Read this editorial analysis and review the numbers behind the story.",
            "info@the-ken.com",
            "notification",
        ),
        (
            "Sale ends soon. Summer savings",
            "Try unlimited access and save with this offer. Upgrade now.",
            "news@e.newyorktimes.com",
            "promotional_bulk",
        ),
        (
            "Leah added you",
            "Leah added you. View their profile.",
            "informational@email.snapchat.com",
            "notification",
        ),
        (
            "Free access. One month. No credit card.",
            "Try now and upgrade to free access.",
            "nytimes@e.newyorktimes.com",
            "promotional_bulk",
        ),
        (
            "Creating meaningful impact, together | ESG Report 2025-26",
            "Please review our ESG Report 2025-26 and its sustainability highlights.",
            "services@custcomm.icici.bank.in",
            "notification",
        ),
        (
            "Keep distractions at bay in special snaps with bae",
            "Please review these special snaps from our latest product campaign.",
            "mail@mail.adobe.com",
            "promotional_bulk",
        ),
        (
            "NetAcad Student Newsletter | July 2026",
            "Please review the NetAcad Student Newsletter for this month. See our account privacy policy.",
            "netacademail@external.cisco.com",
            "promotional_bulk",
        ),
        (
            "Interview Readiness: Practice Test Series",
            "Please review our Practice Test Series.",
            "contests@codechef.com",
            "promotional_bulk",
        ),
        (
            "274680 is your Substack verification code",
            "Your verification code is 274680 and expires in 10 minutes.",
            "no-reply@substack.com",
            "otp_verification",
        ),
    ],
)
def test_m5_1_audit_regressions(
    subject: str,
    body: str,
    sender: str,
    expected: str,
) -> None:
    decision = classify_thread_m5_1(
        ThreadSnapshot(
            subject=subject,
            body=body,
            from_address=sender,
            to_addresses="user@example.test",
            cc_addresses="",
            account_email="user@example.test",
            label_ids=("INBOX",),
            latest_message_at=datetime(2026, 8, 7, tzinfo=UTC),
            message_count=1,
            is_in_inbox=True,
            is_unread=True,
            delivery_metadata={},
        )
    )

    assert decision.category == expected
