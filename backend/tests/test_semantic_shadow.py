from __future__ import annotations

import pytest

from app.classification.semantic_shadow import SemanticClassificationError, validate_decision


def test_validated_semantic_decision_preserves_provider_metadata() -> None:
    decision = validate_decision(
        {
            "category": "action_required",
            "confidence": 0.9,
            "requires_user_action": True,
            "evidence": "It requests approval by Friday.",
        },
        model="future-model",
        classifier_version="future-shadow-v1",
    )

    assert decision.category == "action_required"
    assert decision.explanation["model"] == "future-model"
    assert decision.explanation["requires_user_action"] is True


@pytest.mark.parametrize(
    "value",
    [
        "not json",
        {"category": "bad", "confidence": 0.5, "requires_user_action": False, "evidence": "x"},
    ],
)
def test_semantic_decision_rejects_invalid_provider_output(value: object) -> None:
    with pytest.raises(SemanticClassificationError):
        validate_decision(value, model="future-model", classifier_version="future-shadow-v1")
