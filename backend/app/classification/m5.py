from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape

CLASSIFIER_VERSION = "m5.0-local"
M5_1_CLASSIFIER_VERSION = "m5.1-local"
CATEGORIES = frozenset(
    {
        "action_required",
        "opportunity",
        "important_keep",
        "personal_conversation",
        "notification",
        "otp_verification",
        "promotional_bulk",
        "unclear",
    }
)


@dataclass(frozen=True)
class ThreadSnapshot:
    subject: str
    body: str
    from_address: str
    to_addresses: str
    cc_addresses: str
    account_email: str
    label_ids: tuple[str, ...]
    latest_message_at: datetime
    message_count: int
    is_in_inbox: bool
    is_unread: bool
    delivery_metadata: dict[str, object]


@dataclass(frozen=True)
class Signal:
    name: str
    label: str
    points: int = 0


@dataclass(frozen=True)
class ClassificationDecision:
    category: str
    priority_score: int
    confidence: float
    explanation: dict[str, object]


def classify_thread(snapshot: ThreadSnapshot, *, now: datetime | None = None) -> ClassificationDecision:
    """Classify one message/thread snapshot using local, evidence-backed rules."""
    now = now or datetime.now(UTC)
    text = _normalize(f"{snapshot.subject}\n{snapshot.body}")
    signals = _extract_signals(snapshot, text)
    category, tie_breaker, certainty = _resolve_category(signals)
    components = _priority_components(snapshot, signals, category, now)
    priority = max(0, min(100, round(sum(components.values()))))
    confidence = _confidence(signals, certainty, snapshot)
    reasons = [
        {"signal": signal.name, "label": signal.label, "points": signal.points}
        for signal in signals
        if signal.points or signal.name in {"otp_context", "record_context", "broadcast_context"}
    ][:4]
    if not reasons:
        reasons = [{"signal": "insufficient_context", "label": "No reliable purpose signal was found", "points": 0}]
    summary = _summary(category, signals)
    return ClassificationDecision(
        category=category,
        priority_score=priority,
        confidence=confidence,
        explanation={
            "summary": summary,
            "category": {"selected": category, "tie_breaker": tie_breaker},
            "reasons": reasons,
            "priority_breakdown": {key: value for key, value in components.items() if value},
            "confidence": {"value": confidence, "factors": _confidence_factors(signals)},
            "policy": {},
            "classifier_version": CLASSIFIER_VERSION,
        },
    )


def classify_thread_m5_1(snapshot: ThreadSnapshot, *, now: datetime | None = None) -> ClassificationDecision:
    """Classify with the current deterministic M5.1 rules."""
    now = now or datetime.now(UTC)
    text = _visible_text(f"{snapshot.subject}\n{snapshot.body}")
    signals = _extract_signals_m5_1(snapshot, text)
    category, tie_breaker, certainty = _resolve_category_m5_1(signals)
    components = _priority_components(snapshot, signals, category, now)
    priority = max(0, min(100, round(sum(components.values()))))
    confidence = _confidence(signals, certainty, snapshot)
    reasons = [
        {"signal": signal.name, "label": signal.label, "points": signal.points}
        for signal in signals
        if signal.points or signal.name in {"otp_context", "record_context", "broadcast_context"}
    ][:4]
    if not reasons:
        reasons = [{"signal": "insufficient_context", "label": "No reliable purpose signal was found", "points": 0}]
    return ClassificationDecision(
        category=category,
        priority_score=priority,
        confidence=confidence,
        explanation={
            "summary": _summary(category, signals),
            "category": {"selected": category, "tie_breaker": tie_breaker},
            "reasons": reasons,
            "priority_breakdown": {key: value for key, value in components.items() if value},
            "confidence": {"value": confidence, "factors": _confidence_factors(signals)},
            "policy": {},
            "classifier_version": M5_1_CLASSIFIER_VERSION,
        },
    )


def _normalize(text: str) -> str:
    text = re.sub(r"\n(?:on .+ wrote:|from:.+)$.*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\n--\s*\n.*", "", text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", text).strip().lower()


def _visible_text(text: str) -> str:
    """Discard HTML/CSS/URL noise before applying M5.1 semantic rules."""
    text = re.sub(r"<(?:style|script)\b[^>]*>.*?</(?:style|script)>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return _normalize(unescape(text))


def _extract_signals(snapshot: ThreadSnapshot, text: str) -> list[Signal]:
    signals: list[Signal] = []
    direct = snapshot.account_email.lower() in snapshot.to_addresses.lower()
    list_delivery = bool(snapshot.delivery_metadata.get("is_list_delivery"))
    unsubscribe = bool(snapshot.delivery_metadata.get("has_unsubscribe"))
    bulk_precedence = bool(snapshot.delivery_metadata.get("bulk_precedence"))
    if direct:
        signals.append(Signal("direct_recipient", "Sent directly to this Gmail account", 8))
    if list_delivery or unsubscribe or bulk_precedence:
        signals.append(Signal("broadcast_context", "Delivery metadata indicates a mailing-list or campaign message", -18))

    code = re.search(r"\b\d{4,8}\b", text)
    auth_context = re.search(r"\b(verification|verify|one[- ]time|passcode|security code|sign[- ]in|login|recovery)\b", text)
    if code and auth_context:
        signals.append(Signal("otp_context", "A one-time code appears with verification or sign-in context", 30))
        if re.search(r"\b(expires?|valid for|minutes?)\b", text):
            signals.append(Signal("short_expiry", "The verification message describes a short expiry", 18))

    action = re.search(r"\b(reply|respond|confirm|approve|submit|complete|review|register|rsvp|fill out)\b", text)
    action_context = re.search(r"\b(please|need you to|action required|required|your response|awaiting)\b", text)
    if action and (action_context or direct):
        signals.append(Signal("requested_action", "The message asks the recipient to take a concrete next step", 28))
    if re.search(r"\b(confirm|rsvp|approve)\b", text) and action_context:
        signals.append(Signal("confirmation_required", "A confirmation or decision is explicitly required", 10))

    if re.search(r"\b(today|tomorrow|deadline|due|expires?|by\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", text):
        signals.append(Signal("time_sensitive", "The message contains a time-sensitive deadline or expiry", 20))

    record_terms = re.search(r"\b(statement|receipt|invoice|transaction|account summary|policy|contract)\b", text)
    record_structure = re.search(r"\b(account|amount|balance|reference|billing period|transaction date)\b", text)
    if record_terms and record_structure:
        signals.append(Signal("record_context", "The message is structured as an account or durable record", 8))

    opportunity_terms = re.search(r"\b(job|role|position|internship|fellowship|grant|hackathon|application|opportunity)\b", text)
    opportunity_context = re.search(r"\b(eligible|invited|opening|acceptance|selected|apply|registration)\b", text)
    if opportunity_terms and opportunity_context:
        signals.append(Signal("opportunity_context", "The message describes a role, event, or application opportunity", 8))

    promotion_terms = re.search(r"\b(offer|sale|discount|save|newsletter|subscribe|deal|limited offer|marketing)\b", text)
    broad_cta = re.search(r"\b(sign up|learn more|shop now|view offer|register now)\b", text)
    if promotion_terms and (broad_cta or list_delivery or unsubscribe or bulk_precedence or not direct):
        signals.append(Signal("promotional_context", "Campaign language is paired with broad delivery or marketing structure", -25))

    notification_context = re.search(r"\b(notification|mentioned you|new comment|new follower|status update|build (passed|failed)|digest)\b", text)
    if notification_context and not action:
        signals.append(Signal("notification_context", "The message reports an event or status without a requested task", 0))
    human_sender = not re.search(r"\b(no-reply|noreply|notification|mailer-daemon)\b", snapshot.from_address, re.IGNORECASE)
    if direct and human_sender and not action and not auth_context and not promotion_terms:
        signals.append(Signal("conversation_context", "A direct message from a human sender has no stronger automated purpose", 0))
    return signals


def _extract_signals_m5_1(snapshot: ThreadSnapshot, text: str) -> list[Signal]:
    signals: list[Signal] = []
    sender = snapshot.from_address.lower()
    local_part = sender.split("@", 1)[0].rsplit("<", 1)[-1]
    direct = snapshot.account_email.lower() in snapshot.to_addresses.lower()
    list_delivery = bool(snapshot.delivery_metadata.get("is_list_delivery"))
    unsubscribe = bool(snapshot.delivery_metadata.get("has_unsubscribe"))
    bulk_precedence = bool(snapshot.delivery_metadata.get("bulk_precedence"))
    automated_sender = bool(
        re.search(
            r"(?:no-?reply|noreply|notification|mailer-daemon|news\w*|newsletter|updates?\w*|informational|recommendation\w*|digest\w*|estatement|invitations?|hello)\b",
            local_part,
        )
    )
    editorial_sender = "the-ken.com" in sender
    campaign_sender = automated_sender or any(
        domain in sender
        for domain in ("newyorktimes.com", "mail.adobe.com", "external.cisco.com", "tafmx.grupoaxo.com", "codechef.com")
    )
    if direct:
        signals.append(Signal("direct_recipient", "Sent directly to this Gmail account", 8))
    if list_delivery or unsubscribe or bulk_precedence or editorial_sender:
        signals.append(Signal("broadcast_context", "Delivery or sender context indicates a broadcast message", -18))
    if editorial_sender:
        signals.append(Signal("editorial_context", "Sender is a known editorial publication", 0))
    if re.search(r"\b(esg report|annual report|sustainability report)\b", text):
        signals.append(Signal("informational_report", "The message shares an informational report", 0))
    if automated_sender:
        signals.append(Signal("automated_sender", "Sender address indicates an automated service message", 0))

    auth = re.compile(
        r"\b(?:verification|security|login|sign[- ]in|one[- ]time)\s+(?:code|passcode)\b|\bpasscode\b"
    )
    code = re.compile(r"\b\d{4,8}\b")
    if any(abs(match.start() - auth_match.start()) <= 100 for match in code.finditer(text) for auth_match in auth.finditer(text)):
        signals.append(Signal("otp_context", "A visible one-time code appears near verification context", 30))
        if re.search(r"\b(expires?|valid for|minutes?)\b", text):
            signals.append(Signal("short_expiry", "The verification message describes a short expiry", 18))

    action = r"(?:reply|respond|confirm|approve|submit|complete|review|register|rsvp|fill out)"
    explicit_request = re.search(
        rf"\b(?:please|kindly)\s+(?:\w+\s+){{0,3}}{action}\b|\b(?:need|require)\s+you\s+to\s+{action}\b|\b(?:your\s+)?response\s+(?:is\s+)?(?:required|needed)\b|\bawaiting\s+your\s+response\b|\baction\s+required\b",
        text,
    )
    if explicit_request:
        signals.append(Signal("requested_action", "The message explicitly asks the recipient to take a next step", 28))
    if explicit_request and re.search(r"\b(confirm|rsvp|approve)\b", text):
        signals.append(Signal("confirmation_required", "A confirmation or decision is explicitly required", 10))

    if re.search(r"\b(today|tomorrow|deadline|due|expires?|by\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b", text):
        signals.append(Signal("time_sensitive", "The message contains a time-sensitive deadline or expiry", 20))

    record_terms = re.search(r"\b(statement|receipt|invoice|transaction|account summary|policy|contract)\b", text)
    record_structure = re.search(r"\b(account|amount|balance|reference|billing period|transaction date)\b", text)
    if record_terms and record_structure:
        signals.append(Signal("record_context", "The message is structured as an account or durable record", 8))

    opportunity_terms = re.search(
        r"\b(jobs?|roles?|positions?|internships?|fellowships?|grants?|hackathons?|applications?|opportunit(?:y|ies)|hiring)\b",
        text,
    )
    opportunity_context = re.search(
        r"\b(eligible|invited|opening|acceptance|selected|apply|registration|match(?:es)?|stipend|hiring)\b",
        text,
    )
    if opportunity_terms and opportunity_context:
        signals.append(Signal("opportunity_context", "The message describes a role, event, or application opportunity", 8))

    promotion_terms = re.search(
        r"\b(offer|sale|discount|save|newsletter|subscribe|deal|limited offer|marketing|try|upgrade|free access|ends soon|ofertas|gratis)\b",
        text,
    )
    campaign_cta = re.search(r"\b(sign up|learn more|shop now|view offer|register now|try now|upgrade now|apply now|apply today)\b", text)
    campaign_message = re.search(r"\b(newsletter|special snaps|practice test series|free access)\b", text)
    transactional = bool(
        ((record_terms and record_structure) or "otp_context" in {signal.name for signal in signals})
        and not (campaign_sender and campaign_message)
    )
    if not transactional and (
        (promotion_terms and (campaign_cta or campaign_sender or list_delivery or unsubscribe or bulk_precedence))
        or (campaign_sender and campaign_message)
    ):
        signals.append(Signal("promotional_context", "Campaign language is paired with automated or broad delivery context", -25))

    notification_context = re.search(r"\b(notification|mentioned you|new comment|new follower|status update|build (passed|failed)|digest)\b", text)
    if (notification_context or automated_sender or editorial_sender) and "requested_action" not in {signal.name for signal in signals}:
        signals.append(Signal("notification_context", "The message reports automated activity or editorial content", 0))
    if direct and not automated_sender and not editorial_sender and "requested_action" not in {signal.name for signal in signals} and not promotion_terms and not opportunity_terms and "otp_context" not in {signal.name for signal in signals}:
        signals.append(Signal("conversation_context", "A direct message from a human sender has no stronger automated purpose", 0))
    return signals


def _resolve_category(signals: list[Signal]) -> tuple[str, str, float]:
    names = {signal.name for signal in signals}
    if "otp_context" in names:
        return "otp_verification", "verification_context", 0.95
    if "requested_action" in names:
        return "action_required", "explicit_requested_action", 0.9
    if "record_context" in names and "promotional_context" not in names:
        return "important_keep", "durable_record_context", 0.82
    if "opportunity_context" in names and "promotional_context" not in names:
        return "opportunity", "targeted_opportunity_context", 0.78
    if "promotional_context" in names or "broadcast_context" in names:
        return "promotional_bulk", "broadcast_or_campaign_context", 0.82
    if "conversation_context" in names:
        return "personal_conversation", "direct_human_context", 0.7
    if "notification_context" in names:
        return "notification", "informational_event_context", 0.72
    return "unclear", "insufficient_context", 0.3


def _resolve_category_m5_1(signals: list[Signal]) -> tuple[str, str, float]:
    names = {signal.name for signal in signals}
    if "otp_context" in names:
        return "otp_verification", "visible_code_near_verification_context", 0.95
    if "informational_report" in names:
        return "notification", "informational_report_context", 0.82
    if "requested_action" in names and "promotional_context" not in names:
        return "action_required", "explicit_recipient_request", 0.9
    if "opportunity_context" in names:
        return "opportunity", "opportunity_beats_record_or_campaign_noise", 0.82
    if "record_context" in names and "promotional_context" not in names:
        return "important_keep", "durable_record_context", 0.82
    if "editorial_context" in names:
        return "notification", "editorial_publication_context", 0.82
    if "promotional_context" in names or "broadcast_context" in names:
        return "promotional_bulk", "broadcast_or_campaign_context", 0.82
    if "conversation_context" in names:
        return "personal_conversation", "direct_human_context", 0.7
    if "notification_context" in names:
        return "notification", "automated_or_editorial_context", 0.72
    return "unclear", "insufficient_context", 0.3


def _priority_components(
    snapshot: ThreadSnapshot, signals: list[Signal], category: str, now: datetime
) -> dict[str, int]:
    names = {signal.name for signal in signals}
    actionability = 35 if "requested_action" in names else 0
    time_sensitivity = 25 if "short_expiry" in names else 20 if "time_sensitive" in names else 0
    directness = min(10, (8 if "direct_recipient" in names else 0) + (2 if snapshot.is_unread else 0))
    risk_impact = 10 if category == "otp_verification" else 7 if "record_context" in names else 0
    relationship = 5 if "conversation_context" in names else 0
    suppressions = -25 if "promotional_context" in names else -18 if "broadcast_context" in names else 0
    if (now - snapshot.latest_message_at).days > 30:
        suppressions -= 10
    return {
        "actionability": actionability,
        "time_sensitivity": time_sensitivity,
        "sender_relationship": relationship,
        "directness_thread_state": directness,
        "risk_impact": risk_impact,
        "suppressions": suppressions,
    }


def _confidence(signals: list[Signal], certainty: float, snapshot: ThreadSnapshot) -> float:
    names = {signal.name for signal in signals}
    agreement = min(1.0, max(0.0, (len(names) - 1) / 4))
    completeness = 1.0 if snapshot.body and snapshot.to_addresses else 0.55 if snapshot.body else 0.3
    thread_context = 0.7 if snapshot.message_count > 1 else 0.35
    value = 0.40 * certainty + 0.25 * agreement + 0.20 * completeness + 0.10 * thread_context
    if "broadcast_context" in names and "direct_recipient" in names and "promotional_context" not in names:
        value -= 0.08
    return round(max(0.0, min(1.0, value)), 3)


def _confidence_factors(signals: list[Signal]) -> list[str]:
    names = {signal.name for signal in signals}
    factors = ["local contextual evidence was evaluated deterministically"]
    if len(names) > 1:
        factors.append("multiple independent message signals agree")
    if "broadcast_context" in names and "direct_recipient" in names:
        factors.append("delivery evidence contains mixed direct and broadcast signals")
    return factors


def _summary(category: str, signals: list[Signal]) -> str:
    if category == "action_required":
        return "This message asks you to complete or confirm a concrete next step."
    if category == "otp_verification":
        return "This is a verification or sign-in code message."
    if category == "important_keep":
        return "This appears to be a durable account or transaction record worth retaining."
    if category == "opportunity":
        return "This describes a potentially relevant opportunity without a required response."
    if category == "promotional_bulk":
        return "This has broad campaign or promotional delivery context."
    if category == "personal_conversation":
        return "This is a direct person-to-person conversation."
    if category == "notification":
        return "This is an informational status or activity update."
    return "There is not enough reliable context to determine the message's primary purpose."
