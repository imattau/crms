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
unsupported turns have no hypothesis. `/intent` exposes the last hypothesis on demand in the
interactive chat without adding diagnostics to ordinary answers. The last hypothesis is saved in
the versioned dialogue state and validated when reloaded, so the diagnostic survives a restart.
Regression coverage is in
`experiments/v1_365_contextual_clarification_intent.py`.

The elaboration baseline recognizes a small set of equivalent content-free forms, including
“Could you tell me more?”, “Can you say more?”, and “Could you elaborate?”. These use the same
context policy as “Tell me more”: continue the current grounded topic, or ask which accepted entity
to expand on when no topic is active. Requests that name their own topic and ordinary information
requests remain content turns. This remains a hand-checked phrase family, not learned paraphrase
coverage; see [`v1_378_contextual_elaboration_paraphrases.py`](../experiments/v1_378_contextual_elaboration_paraphrases.py).

The runtime now also retains one typed open dialogue slot:
`pending_dialogue_slot = "elaboration_topic"`. If “tell me more” has no current topic, CRMS asks
which entity with accepted facts to elaborate on. A bare entity name is then classified as an answer
to that question and routed to the accepted-fact overview; an unmatched name gets a clarification,
not a corpus lookup. A new question supersedes the slot, and “never mind” cancels it. This bounded
slot is persisted in dialogue-state format 11 and rejects unknown slot values on load. It is session
context, not learned intent knowledge, and it does not support free-form source summaries. The
sequence and reload checks are in
[`v1_375_contextual_elaboration_slot.py`](../experiments/v1_375_contextual_elaboration_slot.py).

### Corpus coverage diagnostic

The current rules were measured against the prepared Taskmaster-1 `restaurant-table` user-turn
sample (6,227 utterances) with a fresh, empty dialogue state for each turn. Before direct-question
handling, they emitted a hypothesis for 816 turns (13.1%), with 489 selected intents (7.9%). Adding
bounded wh-question, yes/no-question, and modal-request frames raised this to 1,560 hypotheses
(25.1%) and 1,233 selected intents (19.8%). Current hypothesis coverage is 25.1% on train, 26.9%
on dev, and 22.3% on test; selected-intent coverage is 19.9%, 20.0%, and 18.5% respectively. The
current decisions include seek-information questions and modal requests, in addition to social
phrases and ambiguous bare yes/no turns.

This is a **coverage diagnostic, not an accuracy result**. The pilot labels are still blank, and
fresh state deliberately removes the context that the proposed model must use. The coverage increase
shows that ordinary questions and requests were missing from the earlier baseline; it does not show
that the new labels are correct. Turns with no hypothesis include ordinary task content; short slot
answers such as a cuisine, party size, or time can only be interpreted as a task-intent continuation
in context. The remaining 74.9% with no hypothesis is not an error rate. Test-split figures are
not a held-out quality score because there are no adjudicated labels.

The same diagnostic gives a structural measure of that missing context: 2,220 of the 4,667 turns
with no hypothesis (47.6%) immediately follow a final assistant transcript line containing a
question mark. Among unclassified replies of three or fewer word-like tokens, this is 542 of 1,137
(47.7%); on test it is 233 of 450 unclassified turns (51.8%). This does not prove those replies
answer the preceding question or identify their correct task intent. It does show that many cases
the baseline leaves open have visible conversational context that a next model can use and that an
evaluation should preserve.

The diagnostic is reproducible with
[`v1_373_taskmaster_intent_baseline_coverage.py`](../experiments/v1_373_taskmaster_intent_baseline_coverage.py).
It reports coverage by split and the preceding-question cue, without exposing utterance text or
claiming correctness.
Next evaluation requires human annotations and should compare context-free and context-aware
decisions on the same held-out conversations.

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

Treat intent as a model capability, not as a one-off chat heuristic or a property of the current
utterance alone. The reusable part belongs in the distributable CRMS model: reviewed intent frames,
their context and predecessor conditions, and the evidence and evaluation status that license
them. The active conversation supplies the changing context. At each turn CRMS forms a bounded
hypothesis about the user's immediate goal, updates or retains it as new turns arrive, and keeps
multiple readings when the evidence does not distinguish them. The hypothesis is contextual and
revisable; it is not a permanent profile or an assertion that CRMS knows the user's hidden mental
state.

This separates three things that must not be conflated:

| Component | Lifetime | Example |
|---|---|---|
| Intent model | Shared/distributable; learned and reviewed | A correction frame is licensed when it refers to a prior answer |
| Discourse context | Current session; bounded and inspectable | The last answer, open clarification, active topic, and unresolved slots |
| Intent hypothesis | Current turn or unresolved exchange; revisable | “The user may be correcting the entity; another reading is a topic change” |

Intent can guide routing, clarification, and task continuity. It cannot authorize a side effect, turn
a user statement into accepted knowledge, or strengthen the evidence for a factual answer. When a
new turn conflicts with the current hypothesis, CRMS should revise or ask; it should not silently
reinterpret earlier user statements as facts.

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

The record is a per-turn decision over the current discourse state, not a user-level identity label.
Retain alternatives and the context predicates that would distinguish them; do not force a single
intent when the context is insufficient.

The minimum context state should remain bounded and typed: recent acts, the current question under
discussion, the active task/topic, open required slots, pending clarification or offer, and the
provenance/status of the last answer. A first typed open slot now supports an elaboration topic; the
general task-slot inventory remains future work. Store reusable intent frames and their evidence in
the SQLite model database. Keep a user's current slot values and unresolved intent hypotheses in
session dialogue state. User-provided values remain user claims or task parameters; they do not
become accepted world facts by default.

### Distributable model boundary

This boundary is designed but not implemented. The portable package currently includes `knowledge`,
`rules`, `math`, and `translations`; it has no dialogue-intent memory. Runtime intent patterns still
live in `crms_conversation.py`, and the present hypotheses identify themselves as
`hand_checked_runtime_rule`. Do not describe these patterns as learned or as part of a portable
model until they are moved behind a package-backed interface.

Once a frame has independent human-reviewed training and held-out labels, store it in a versioned
`dialogue` memory inside the portable SQLite model. Keep the record explicit and auditable:

- stable frame ID, dialogue act, task intent, and realization or match pattern;
- named slots and typed context/predecessor predicates;
- exact utterance citations, source-document identities, labeler and adjudication provenance;
- train/holdout split IDs, coverage and error measures, and review/license status;
- the domain and corpus policy for which the frame is approved.

Only frames marked licensed after the held-out gate may select an intent or route a turn. A proposed
frame remains inspectable but cannot affect chat behavior. The live discourse context and current
intent hypotheses remain in per-user dialogue state; they must never be copied into the shared
model as user facts. This separates reusable conversational knowledge from the temporary context
that makes a short answer such as “yes” interpretable.

The implementation should add the `dialogue` package memory and a loader/validator first, with
round-trip and legacy-model tests. Then migrate the bounded hand-checked seed frames into an
explicitly labeled built-in policy section or keep them as a compatibility fallback; never silently
merge built-in product policy with corpus-induced frames. Replace the corresponding hard-coded
patterns only after the package-backed resolver matches the current regression behavior. Do not
start induction until independently labeled examples exist: the Taskmaster annotation sheets are
currently blank, so self-labeled predictions cannot serve as validation evidence.

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

To make a first human pass manageable, `experiments/v1_382_dialogue_feasibility_batch.py` selects
whole conversations from train only, copies their cited transcripts, and deterministically assigns
20% of the selected conversations for independent double labeling. The current 40-conversation
batch contains 563 user turns and 650 assistant turns; its label cells remain blank. This creates a
feasible annotation artifact, not an accuracy result. Run the evaluator after labels are entered,
and do not train or tune on the double-label audit or held-out dev/test conversations.
