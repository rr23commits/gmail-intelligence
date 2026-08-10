"""Small, deterministic post-M5.1 feedback adjustment."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass

from app.classification.m5 import CATEGORIES, ClassificationDecision

FEEDBACK_CLASSIFIER_VERSION = "m5.1-feedback-local"


@dataclass(frozen=True)
class FeedbackSignal:
    sender_domain: str
    original_category: str
    corrected_category: str


def validate_corrected_category(category: str) -> str:
    if category not in CATEGORIES:
        raise ValueError("corrected_category must be a canonical M5 category.")
    return category


def apply_feedback(
    decision: ClassificationDecision, *, sender_domain: str, feedback: list[FeedbackSignal]
) -> ClassificationDecision:
    """Override only after two consistent, account-scoped corrections."""
    if decision.category == "otp_verification":
        return decision
    targets = [
        item.corrected_category
        for item in feedback
        if item.sender_domain == sender_domain and item.original_category == decision.category
    ]
    counts = Counter(targets)
    if not counts:
        return decision
    category, count = counts.most_common(1)[0]
    if count < 2 or list(counts.values()).count(count) > 1:
        return decision
    return _with_feedback(decision, category=category, count=count, source="repeated_sender_feedback")


def user_correction(decision: ClassificationDecision, *, category: str) -> ClassificationDecision:
    """Represent an explicit correction as a new, immutable classification version."""
    return _with_feedback(decision, category=category, count=1, source="user_correction")


def _with_feedback(
    decision: ClassificationDecision, *, category: str, count: int, source: str
) -> ClassificationDecision:
    explanation = deepcopy(decision.explanation)
    explanation["summary"] = "Classification corrected from local feedback."
    explanation["category"] = {"selected": category, "tie_breaker": source}
    reasons = list(explanation.get("reasons", []))
    reasons.insert(0, {"signal": source, "label": f"{count} matching correction(s) for this sender", "points": 0})
    explanation["reasons"] = reasons[:4]
    explanation["feedback"] = {"original_category": decision.category, "corrections": count}
    explanation["classifier_version"] = FEEDBACK_CLASSIFIER_VERSION
    return ClassificationDecision(
        category=category,
        priority_score=decision.priority_score,
        confidence=min(decision.confidence, 0.75),
        explanation=explanation,
    )
