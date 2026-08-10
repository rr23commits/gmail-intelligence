"""Provider-neutral semantic shadow-classification contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.classification.m5 import CATEGORIES, ThreadSnapshot


class SemanticClassificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SemanticDecision:
    category: str
    confidence: float
    requires_user_action: bool
    evidence: str
    model: str
    classifier_version: str

    @property
    def explanation(self) -> dict[str, object]:
        return {
            "summary": self.evidence,
            "category": {"selected": self.category},
            "confidence": {"value": self.confidence},
            "requires_user_action": self.requires_user_action,
            "model": self.model,
            "classifier_version": self.classifier_version,
        }


class SemanticClassifier(Protocol):
    """A provider adapter must raise SemanticClassificationError on a failed inference."""

    def classify(self, snapshot: ThreadSnapshot) -> SemanticDecision: ...


def validate_decision(value: object, *, model: str, classifier_version: str) -> SemanticDecision:
    """Validate a provider's structured response before it can be stored."""
    expected_fields = {"category", "confidence", "requires_user_action", "evidence"}
    if not isinstance(value, dict) or set(value) != expected_fields:
        raise SemanticClassificationError("Semantic classification has an invalid schema.")
    category, confidence = value["category"], value["confidence"]
    if category not in CATEGORIES or isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise SemanticClassificationError("Semantic classification has an invalid category or confidence.")
    if not 0 <= confidence <= 1 or not isinstance(value["requires_user_action"], bool):
        raise SemanticClassificationError("Semantic classification has invalid field values.")
    evidence = value["evidence"]
    if not isinstance(evidence, str) or not (evidence := re.sub(r"\s+", " ", evidence).strip()) or len(evidence) > 500:
        raise SemanticClassificationError("Semantic classification has invalid evidence.")
    return SemanticDecision(
        category,
        float(confidence),
        value["requires_user_action"],
        evidence,
        model,
        classifier_version,
    )
