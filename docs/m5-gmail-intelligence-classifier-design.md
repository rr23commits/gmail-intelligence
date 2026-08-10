# M5 Gmail Intelligence Classifier Design

## Status and scope

This is a design document only. It replaces the proposed M5 taxonomy and
classifier approach; it does not change the current M3 classifier, database,
API, sync flow, or UI.

M5 is local-user and Gmail-account scoped. It classifies an account-scoped
thread from its newest relevant message and thread context. Category, priority,
and confidence are separate outputs. Every output must be traceable to named
evidence and a classifier version.

M5 V1 uses no hosted LLM, paid API, or remote semantic service. Its semantic
assessment boundary remains pluggable for a future local model, but V1 is a
local, deterministic, explainable, and testable assessor.

## Final categories

Each thread has exactly one primary category. Financial, calendar, deadline,
and security facts are signals; they are not categories except where the
primary purpose is an OTP/verification event.

| Category | Primary user outcome |
|---|---|
| `action_required` | The user needs to respond, decide, confirm, submit, approve, or complete a concrete task. |
| `opportunity` | The message offers a potentially useful job, academic, grant, event, or business opportunity, without an immediate required response. |
| `important_keep` | The message is a record the user is likely to retain: statement, receipt, policy, contract, account record, or consequential update. |
| `personal_conversation` | A direct human conversation or relationship message that is not better represented by an explicit task. |
| `notification` | An informational event/status update, including social and product notifications, that does not require retention or action. |
| `otp_verification` | A one-time passcode, login confirmation, recovery, or verification message. |
| `promotional_bulk` | A broad campaign, newsletter, discount, marketing mail, or repeated automated outreach. |
| `unclear` | The primary user outcome cannot be established with sufficient evidence. |

### Contextual distinctions

The resolver identifies the *purpose for this recipient*, not just words or
entities in the message.

| Context | Result |
|---|---|
| Broad hackathon campaign with mass CTA and no recipient-specific next step | `promotional_bulk` |
| Hackathon invitation/eligibility message addressed to the user, no required confirmation | `opportunity` |
| Hackathon acceptance asking the user to confirm/register/respond | `action_required` |
| Bank statement or transaction record | `important_keep` |
| Bank OTP or sign-in verification code | `otp_verification` |
| Bank offer, card promotion, or marketing campaign | `promotional_bulk` |

Category tie-breaker order is driven by primary purpose: OTP/verification,
then explicit required action, then record retention, then a targeted
opportunity, then a direct conversation, then notification/bulk, otherwise
unclear. The resolver records competing evidence and the tie-breaker used.

## Pipeline

```text
Thread snapshot
  -> content normalization
  -> deterministic structured-signal extraction
  -> local contextual assessment
  -> preference/policy resolution
  -> category resolution
  -> priority scoring
  -> confidence calibration
  -> explanation and versioned persistence
```

1. **Thread snapshot**: load the account-scoped thread, newest relevant
   message, useful prior messages, Gmail labels, and account context.
2. **Normalization**: remove HTML boilerplate, quoted replies, tracking text,
   unsubscribe blocks, and signatures before assessment. Raw stored mail is not
   modified.
3. **Structured-signal extraction**: parse headers, recipients, timestamps,
   dates, attachments, labels, thread state, sender/domain, and repeated
   template patterns. This produces evidence, never a category by itself.
4. **Local contextual assessment**: combine normalized message structure and
   signals into typed facts: intended recipient, requested action, response
   expectation, record-retention value, verification purpose, opportunity
   relevance, broadcast likelihood, and event/risk details.
5. **Preference/policy resolution**: apply scoped user and account preferences
   plus M6-derived adjustments to ranking/visibility—not to facts.
6. **Decision**: resolve category, priority, confidence, and explanation from
   the same evidence package.

## V1 local contextual assessment

V1 is a composable local rules-and-parsers implementation, not a bag of
keywords. It evaluates evidence combinations and document structure:

- sender/domain and Gmail list/bulk metadata;
- direct `To` versus mailing-list/CC delivery;
- message-template repetition and unsubscribe/marketing structure;
- parsed action framing: actor, requested task, required confirmation, and
  whether a reply is owed;
- parsed authentication framing: code shape, expiry, login/recovery/account
  context, and sender identity;
- parsed record framing: statement/receipt/document structure, dates, account
  identifiers, transaction-like rows, and attachment metadata;
- parsed opportunity framing: eligibility, role/event/application details,
  personalized fit, deadline, and whether the recipient must act now;
- thread state: prior messages, user-last-replied, and whether another person
  is awaiting a response.

Vocabulary and parser patterns can support extraction, but no isolated token
may directly decide the category. For example, “hackathon” is only an event
entity; broadcast structure, recipient relevance, and requested next step
determine its category. Every detector returns typed evidence, a confidence,
and a short evidence span/field reference.

The semantic-assessment interface accepts the normalized thread and returns
this typed evidence package. A future local model may implement that same
interface, but must emit the same evidence contract. Hosted providers are out
of scope for M5.

## Signals and features

All features are named, typed, scoped, and evidence-backed. Missing is
represented as missing, never as false.

### Content and contextual signals

- Primary purpose: required action, opportunity, record, conversation,
  notification, verification, or promotion.
- Requested action, actor, response expectation, and confirmation requirement.
- Recipient relevance: direct, personalized, group/list, or broadcast.
- Verification/authentication context: code, expiry, login/recovery event, and
  sender trust.
- Record-retention indicators: statement/receipt/document structure, account
  event, durable reference, and transaction/account metadata.
- Opportunity details: role/event/application, eligibility, personalization,
  deadline, and next step.
- Bulk/promotional indicators: campaign layout, unsubscribe/footer, list
  delivery, repeated template, discount/marketing framing, and recipient
  non-specificity.
- Person/conversation indicators: human sender, prior thread context, direct
  correspondence, relationship strength, and reply owed.

### Timing, risk, and event signals

- Parsed deadline/event time, timezone, proximity, and parsing certainty.
- Calendar/invitation evidence and availability coordination.
- Financial/account event, security risk, expiry, or consequence of inaction.
- Recency and staleness.

These signals influence category resolution where context requires it and
priority in every category. They do not create standalone financial, calendar,
or time-sensitive categories.

### Gmail/thread signals

- Inbox, unread, important/starred, sent, and Gmail category labels.
- Direct recipient/CC/list recipient and recipient count.
- Thread message count, newest-message age, user-last-replied, and reply owed.
- Attachment presence/type, duplicate/template frequency, and prior activity.

### Relationship, preference, and feedback signals

- Sender/domain interaction history and explicit sender priority/mute.
- Account role via account-scoped preferences only.
- Category/topic/entity preference, digest preference, and learned M6 bias with
  sample count and decay.

## Priority score

Priority answers “how soon should the user see or act on this?” It is
independent of category and is a bounded, explainable sum:

| Component | Range | Evidence |
|---|---:|---|
| Actionability | 0–35 | Required task, decision, confirmation, reply owed, and directness. |
| Time sensitivity | 0–25 | Deadline/event proximity, expiry, and consequence of delay. |
| Sender/relationship relevance | 0–15 | Interaction history and explicit sender preference. |
| Directness/thread state | 0–10 | Direct recipient, unread/inbox, and pending conversation state. |
| Risk/impact | 0–10 | Security, account, financial, legal, or material-work impact. |
| Preference adjustment | -20–+15 | Explicit account/user/topic/sender policy. |
| Suppressions | -25–0 | Bulk evidence, repetition, staleness, or mute rules. |

`priority = clamp(round(sum(components)), 0, 100)`.

Suggested bands: 80–100 urgent, 60–79 important, 35–59 review, and 0–34 low
priority. `otp_verification` can score high for short expiry but is not
automatically high without an expiry/directness/risk signal. `important_keep`
can score low while still remaining a retained record.

## Confidence

Confidence measures confidence in the selected category and evidence, not
importance. It is persisted as 0.000–1.000.

```text
confidence = 0.40 local contextual-assessment certainty
           + 0.25 agreement across independent extractors
           + 0.20 input completeness/normalization quality
           + 0.10 thread corroboration
           + 0.05 relevant user-feedback agreement
```

Each term is normalized to 0–1. Clamp the result to 0–1 and reduce it for
conflicting evidence, body content dominated by boilerplate, or stale context.
Low confidence routes to `unclear` when no category has adequate evidence; it
must never be converted into urgency.

## Explanations

Explanations are built after the decision from recorded evidence using local
templates. They contain no hidden reasoning and make no claims without a
signal. The M5 migration should evolve `Classification.explanation` to:

```json
{
  "summary": "Confirmation is requested before Friday.",
  "category": {"selected": "action_required", "tie_breaker": "explicit_confirmation"},
  "reasons": [
    {"signal": "confirmation_required", "label": "A confirmation is requested", "points": 28},
    {"signal": "deadline", "label": "Deadline is Friday", "points": 20}
  ],
  "priority_breakdown": {"actionability": 28, "time_sensitivity": 20},
  "confidence": {"value": 0.86, "factors": ["recipient and action evidence agree"]},
  "policy": {"sender_boost": 5},
  "classifier_version": "m5.0"
}
```

Evidence labels quote only the minimum useful content and are safe for the
local UI.

## Preferences in the pipeline

Preferences are resolved after facts are extracted and before ranking. They
can change priority, visibility, digests, and recommendations; they cannot
alter semantic facts or inflate confidence.

Precedence: account-specific explicit preference > user explicit preference >
M6 learned preference > product default. A mute always wins.

The existing `feedback_events` table is the append-only source of preference
history. M5 should initially derive an effective scoped profile from those
events. If sync-time reads require it, a future dedicated migration can add a
materialized `intelligence_preference_profiles` projection with `user_id` and
optional `gmail_account_id`; it must contain no OAuth data.

## M6 feedback loop

M6 records append-only `feedback_events` such as:

- `category_corrected`
- `priority_adjusted`
- `marked_important` / `marked_not_important`
- `dismissed_as_bulk`
- `snoozed`
- `sender_preference_changed`
- `explanation_disputed`

The original classification remains historical. An immediate user correction
creates a new classification revision and marks the prior one non-current.
For future mail, a feedback projector updates account-scoped effective
preferences and bounded, decaying feature biases. For example, repeated bulk
dismissals lower similar sender/template priority; repeated sender promotion
raises relationship relevance. A minimum sample count prevents a few events
from dominating direct action, expiry, or risk evidence.

M6 does not perform cross-user training without a separate privacy design.

## Existing-schema fit and implementation boundaries

- Reuse `gmail_messages` and `gmail_threads` for the account-scoped input.
- Reuse versioned `classifications` for M5 decisions, with `source` identifying
  the local assessor and `classifier_version` identifying the release.
- Reuse `feedback_events` for immutable feedback history.
- Use `recommendations` only after classification; it cannot influence the
  category decision.
- Preserve the existing compound account/user foreign keys for every query and
  future table.

M5 implementation should add small pure components for normalization,
structured extraction, local contextual assessment, preference resolution,
category resolution, scoring, confidence, explanation, and persistence. Each
component is independently testable with redacted fixtures.

## Acceptance and evaluation plan

Create an account-scoped, redacted fixture set covering all contextual pairs:
hackathon promotion/opportunity/acceptance, bank statement/OTP/promotion,
verification codes, newsletters, job alerts, social notifications, direct
reply requests, deadlines, calendar items, receipts, and ambiguous messages.

Track category precision/recall, urgent-item recall, priority ranking quality,
confidence calibration, explanation evidence coverage, and feedback reversal
rate. Compare M5 with M3 without overwriting M3 history. Roll out per account,
retain classifier versions, and preserve a fallback to the last version.
