# Design: contextual user intent

**Status:** research design. CRMS does not yet have a learned user-intent model. The current
`crms_conversation.py` recognizes a small set of anchored, content-free phrases; `CRMSDialogue`
tracks recent entities and question/clarification state. These mechanisms do not constitute general
contextual intent understanding.

## Current contextual baseline

`respond()` now attaches an inspectable `intent_hypothesis` to turns handled by its small set of
explicit rules. It distinguishes a bare yes/no response while an answer-choice clarification is open
from an unanchored yes/no response; separates an acknowledgement from a confirmation; and records
when a candidate phrase or correction resolves the choice. With multiple supported candidates,
“yes” or “no” leaves the choice pending and explains that a specific candidate is needed; without
an open yes/no question, CRMS asks what the user is responding to rather than sending the token to
retrieval. It also distinguishes an explanation follow-up after a grounded answer from an unanchored
“why?”, and conditions “tell me more” on a current topic. The hypothesis records its act, task intent
(when known), decision, matched frame, context predicates, alternatives, selected value, and that the
basis is a hand-checked runtime rule. It is inspectable but not learned or corpus-licensed;
unsupported turns have no hypothesis. Regression coverage is in
`experiments/v1_365_contextual_clarification_intent.py`.

## Why intent belongs in the model

The same words can request different things depending on the exchange. “Yes” may confirm a time,
accept an offered action, or answer a yes/no question. “What about Friday?” may change a booking
constraint or start a new topic. A turn classifier that sees only the current string will miss this
difference.

CRMS should model at least two distinct judgments:

1. **Dialogue act:** what the utterance does now: answer a clarification, correct an answer, ask a
   question, provide a detail, or close contact.
2. **Task intent:** what immediate user goal it advances: obtain information, make or change a
   reservation, resolve an ambiguity, correct an outcome, or continue a topic.

Neither label is the truth of a world claim. A user can ask a question while giving a false premise;
intent recognition must never turn that premise into a fact.

## Explicit contextual representation

Represent a user-intent hypothesis as an inspectable record, not a latent state:

| Field | Meaning |
|---|---|
| `intent_id` | Stable label such as `provide_constraint` or `correct_result` |
| `act_id` | Turn function such as `provide_information` or `correction` |
| `matched_frame` | Learned or reviewed phrase pattern and its bound slots |
| `context_predicates` | Conditions over visible dialogue state: open question, missing slot, pending choice, prior answer, task status |
| `predecessor_act` | Required or supporting prior user/system act |
| `alternatives` | Other licensed readings and the evidence that supports them |
| `decision` | `selected`, `ambiguous`, or `unlicensed` |
| `evidence_refs` | Cited training utterances, label provenance, and review status |

The minimum context state should remain bounded and typed: recent acts, the current question under
discussion, the active task/topic, open required slots, pending clarification or offer, and the
provenance/status of the last answer. Store the reusable intent frames and their evidence in the
SQLite model database. Keep a user's current slot values and unresolved intent hypotheses in
session dialogue state. User-provided values remain user claims or task parameters; they do not
become accepted world facts by default.

## Runtime decision policy

1. Match candidate frames against the current utterance and recent context.
2. Check each frame's explicit context and predecessor predicates.
3. Retain alternatives with their support; do not collapse a tie into a guess.
4. If exactly one licensed intent remains, route it to a capability that already exists.
5. If the intent is ambiguous, ask the smallest question that separates the live candidates.
6. If no intent is licensed, use the ordinary question/abstention path and preserve the user's
   wording for a useful clarification.

Intent controls routing and what clarification is needed. It cannot make a fact answerable, promote
quoted evidence into accepted knowledge, suspend or teach a rule, or trigger an irreversible action.
Actions such as booking or changing stored knowledge still require their existing explicit
confirmation gates.

## Learning and evidence

Use the two Taskmaster sheets in the dialogue pilot:

- Assistant move annotations provide evidence about the response patterns and transitions that
  follow a user act.
- User-turn annotations separately label dialogue act, contextual task intent, context state, and
  preceding assistant act.

The labels are human-reviewed measurements, not labels already present in Taskmaster. Train or
induce on train conversations only; use dev to select frame/context policies; hold test conversations
untouched until evaluation. Keep both annotators' labels and disagreements. Do not use a model's own
predictions as their validation evidence. To test transfer, repeat on another independently
collected corpus and report domain shift rather than pooling the corpora blindly.

## Evaluation and capability comparison

Compare three systems on the same conversation-held-out examples:

1. Current phrase-level CRMS handlers, as the deterministic baseline.
2. A contextual CRMS intent model using learned/reviewed frames and explicit discourse state.
3. A strong instruction-model comparator given the same visible context and task tools.

Measure act accuracy and task-intent macro-F1 separately; slot accuracy; ambiguous-intent
clarification precision; unnecessary clarification rate; wrong-action rate; task completion;
correction recovery; and evidence/provenance violations. Include context ablations (utterance only,
utterance plus preceding turn, full bounded state) to show whether context actually helps. Report
confidence or alternative-set coverage and abstention, not accuracy alone. The strong model is a
capability comparator, not a label oracle.

## Implementation sequence

1. Finalize the annotation schema and label a feasibility batch with independent review.
2. Measure the current scripted baseline on those adjudicated examples.
3. Induce user act/intent frames from train examples and learn context predicates only where the
   labels support them.
4. Compare lexical-only and contextual models on held-out conversations.
5. Integrate only intents that improve task progress without increasing unsupported claims or
   mistaken actions; keep unlicensed turns on the existing honest fallback.

The current corpus preparation now emits `user_turns_to_label.csv` alongside the assistant move
sheet. Both are in `/tmp/crms_taskmaster_pilot` in the current development environment; no labels
have yet been supplied, so all quality claims remain open.

`experiments/v1_366_dialogue_annotation_evaluation.py` checks split integrity, label values, audit
coverage, raw agreement, Cohen's kappa, and adjudication of disagreements. On the current pack it
reports `awaiting_annotations`, 6,227 user turns, 7,312 assistant turns, and no agreement score; an
empty sheet is not evidence of agreement. It supports `--strict` to prevent incomplete annotations
from being reported as a completed evaluation, and `--self-test` for the agreement formula,
split-leakage checks, and required label provenance.
