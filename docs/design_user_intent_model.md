# Design: contextual user intent

**Status:** research design with a narrow runtime baseline. User intent is part of the CRMS model
capability, and it must be interpreted from the current utterance together with explicit discourse
context. CRMS has hand-checked contextual rules and a portable dialogue-frame resolver, but it does
not yet have an induced, independently validated user-intent model. The resolver supports exact
surface patterns with typed context and predecessor conditions; this is a routing seam, not general
contextual intent understanding. Reusable, reviewed frames belong in the distributable model, while
live discourse context and turn-level hypotheses belong in session state.

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
unsupported turns have no hypothesis. `/intent` exposes the last hypothesis, active task label, and
recent bounded intent trace without adding diagnostics to ordinary answers. Selected task goals are
retained in inspectable session state; ambiguous or unlicensed hypotheses cannot replace the
active goal. Social turns preserve it, while an explicit end-interaction or `/reset` clears it. This
is a context predicate for licensed frames, not broad task-slot understanding or authorization to
act. The trace and last hypothesis are saved in dialogue-state format 16 and validated when reloaded.
`experiments/v1_386_session_intent_context.py` checks that the active-task predicate actually
licenses a matching portable frame, survives reload, remains bounded, and clears on explicit end
or reset; `experiments/v1_365_contextual_clarification_intent.py` checks the existing clarification
behavior.

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
slot is persisted in dialogue-state format 16 and rejects unknown slot values on load. The exact
assistant clarification prompt is retained as a bounded QUD with a `detail` or `yes-no` answer kind
and an expected-slot type such as `location`, `party_size`, `date_time`, `seating`, or `cuisine`.
Typed slots are exposed to portable intent frames through predicates such as
`awaiting_slot_location`; format 14 QUD state migrates by deriving its slot from the saved prompt.
A short reply is interpreted against that question and recorded in the intent trace. For the
bounded task slots (location, party size, date/time, seating, cuisine, and restaurant choice), its
user-provided value and the prompting question are retained in session state, displayed by `/intent`,
and kept out of factual knowledge. Direct questions such as “What time did I give you?” can recall
that session value together with the prompt that elicited it; a missing value abstains without
falling through to factual retrieval. This is session context, not learned intent knowledge or
robust slot extraction from arbitrary turns, and it does not support free-form source summaries.
Yes/no answers have a separate `awaiting_yes_no_answer` predicate and are not treated as action
confirmations. The sequence and reload checks are in
[`v1_375_contextual_elaboration_slot.py`](../experiments/v1_375_contextual_elaboration_slot.py)
and [`v1_388_open_dialogue_question_state.py`](../experiments/v1_388_open_dialogue_question_state.py).

### Corpus coverage diagnostic

The current rules were measured against the prepared Taskmaster-1 `restaurant-table` user-turn
sample (6,227 utterances) with a fresh, empty dialogue state for each turn. Before direct-question
handling, they emitted a hypothesis for 816 turns (13.1%), with 489 selected intents (7.9%). Adding
bounded wh-question, yes/no-question, and modal-request frames raised this to 1,560 hypotheses
(25.1%) and 1,233 selected intents (19.8%). Current hypothesis coverage is 25.1% on train, 26.9%
on dev, and 22.3% on test; selected-intent coverage is 19.9%, 20.0%, and 18.5% respectively. The
current decisions include seek-information questions and modal requests, in addition to social
phrases and ambiguous bare yes/no turns.

This is a **coverage diagnostic, not an accuracy result**. A 40-conversation train-only feasibility
batch has since received one AI annotation pass (563 user turns and 650 assistant turns). The labels
are provisional and have no independent second-rater review; fresh state also deliberately removes
the context that the proposed model must use. The coverage increase
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
The single-AI-label pass enables a limited development comparison, but it does not satisfy the
independent review gate. Running
[`v1_385_provisional_dialogue_label_comparison.py`](../experiments/v1_385_provisional_dialogue_label_comparison.py)
on that batch gave the context-free baseline hypotheses on 137/563 turns (24.3%) and selected
intents on 125/563 (22.2%). Within the hypothesized turns, act labels matched the AI annotations
on 86.1% and task-intent labels on 74.5%. These are **label-agreement diagnostics, not accuracy**;
the batch has one AI annotator, and shared biases between annotation and hand-built rules may inflate
agreement. Coverage was especially low for annotated `provide-constraint` turns (3/104, 2.9%) and
`make-reservation` turns (7/63, 11.1%). This points to missing contextual slot and task-phase
handling, rather than a need to add more factual knowledge.

An additional analysis of exact repeated wording found 19 normalized user surfaces repeated across
conversations; eight had different annotated act/intent pairs. The combination of `context_state`
and `predecessor_act` separated six of those eight surface ambiguities. Two remained conflicted;
for example, “yes” and a location response such as “San Francisco, California” can share the same
coarse `awaiting-user-detail` plus `clarification-request` context while carrying different task
intents. This small, AI-labeled sample is directional evidence only. It suggests that the next
context representation needs the pending question or expected slot, not only a phase label and
previous act. The report is reproducible with
[`v1_387_contextual_intent_ambiguity.py`](../experiments/v1_387_contextual_intent_ambiguity.py).

The next evaluation should compare context-free and context-aware decisions on the same held-out
conversations, with the pending question, expected slot, and active task represented explicitly.
The first context-feature diagnostic over the same 563 turns used lexical cues from the latest
assistant question and recent user statements. On the eight repeated surfaces with conflicting
act/intent labels, coarse `context_state + predecessor_act` partitioned six consistently; the new
`active task + expected slot` signature also partitioned six, with one fewer row left in conflicted
contexts (9 rather than 10). The two unresolved surfaces remained `yes` and `San Francisco,
California`. This is a small descriptive result, not evidence that the feature set improves runtime
accuracy. It supports representing the current question's expected slot and the active goal as
separate typed context, while showing that keyword cues and the single-rater labels are too weak to
license routing. The diagnostic is reproducible with
[`v1_390_contextual_intent_task_slot_diagnostic.py`](../experiments/v1_390_contextual_intent_task_slot_diagnostic.py).

The AI labels can guide candidate development and label-conditioned evaluation; report that
comparison as agreement with the annotator, and do not treat it as independent correctness evidence.

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
provenance/status of the last answer. Open assistant questions now retain an expected-slot type
(such as location, party size, date/time, seating, topic, or confirmation); the dialogue intent
resolver exposes it as a context predicate. This is session context for interpreting replies, not
knowledge about the world. Store reusable intent frames and their evidence in
the SQLite model database. Keep a user's current slot values and unresolved intent hypotheses in
session dialogue state. User-provided values remain user claims or task parameters; they do not
become accepted world facts by default.

### Distributable model boundary

Portable SQLite model v5 accepts an optional versioned `dialogue` memory, validates its
built-in-policy and learned-frame sections, and preserves it through install and repack. A first
resolver is now wired into `crms_conversation.py`: it matches exact normalized surface forms,
requires all declared context predicates and any predecessor condition, and accepts only frames
licensed as built-in policy or held-out validated. A frame may select an inspectable intent without
triggering an action; runtime routes remain restricted to existing social, acknowledgement,
reaction, and elaboration handlers. Answer-clarification frames must require an explicit open
question context. Train-only, candidate, and rejected frames are inert; a context mismatch falls
through to the prior chat path. Selected portable-frame hypotheses expose the frame ID and source
citations. `crms_dialogue_intent.py` rejects unknown context predicates, route/intent mismatches,
clarification answers without an open question, malformed evidence metadata, and overlapping
train/holdout conversation IDs. Legacy model versions remain readable.

This is a narrow runtime seam, not learned dialogue competence: there is no frame induction yet,
surface patterns are exact phrases rather than slot-generalizing templates, and task-oriented
slots beyond existing dialogue state are not supported. Most ordinary intent recognition still
uses the hand-checked rules in `crms_conversation.py`. The 40-conversation feasibility batch has
Codex-authored labels, which the project owner has authorized for candidate induction and
label-conditioned experiments. No independent second annotation exists, so agreement with these
labels is not an accuracy or appropriateness claim. If two licensed portable frames match the same
utterance and context
but select different routes, CRMS now records an ambiguous hypothesis, asks the user to choose
between the two routes, and executes only the selected route. The short yes/no choice retains the
matched-frame evidence and never changes factual knowledge. This handles an explicit model conflict;
it does not resolve general paraphrase or task-slot ambiguity.

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

Next, migrate bounded hand-checked seed frames into the separate built-in-policy section only where
their behavior is reproduced; never silently merge product policy with corpus-induced frames.
Expand matching to typed slots only with ambiguity and adversarial tests. Candidate induction may
use the authorized AI-labeled training batch; keep resulting frames `candidate` or `train-only`
until conversation-held-out evidence and the separate policy gate support licensing. Agreement
with labels from the same annotator is not independent validation. Packaging and runtime coverage
are checked by [`v1_383_dialogue_model_memory_packaging.py`](../experiments/v1_383_dialogue_model_memory_packaging.py)
and [`v1_384_contextual_dialogue_frame_resolution.py`](../experiments/v1_384_contextual_dialogue_frame_resolution.py).

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

Taskmaster does not provide these labels. The current feasibility batch has one AI-authored label
per turn, while the designated second-rater and adjudication fields remain blank. Treat those labels
as provisional error-analysis targets; do not calculate inter-rater agreement or use them as held-out
validation evidence. Train or induce on train conversations only; use dev to select frame/context
policies; hold test conversations untouched until evaluation. For licensed dialogue frames, retain
independent annotator labels and adjudication. To test transfer, repeat on another independently
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

1. Finalize the annotation schema; use AI labels for early error analysis and obtain independent
   review before treating the feasibility batch as an evaluation set.
2. Measure the current scripted baseline on independently reviewed examples. The existing
   single-AI comparison is development evidence only.
3. Induce user act/intent frames from train examples and learn context predicates only where the
   labels support them.
4. Compare lexical-only and contextual models on held-out conversations.
5. Integrate only intents that improve task progress without increasing unsupported claims or
   mistaken actions; keep unlicensed turns on the existing honest fallback.

The current corpus preparation emits `user_turns_to_label.csv` alongside the assistant move sheet.
The full prepared pilot remains in `/tmp/crms_taskmaster_pilot`. A separate 40-conversation batch in
`/tmp/crms_dialogue_feasibility_v1` now contains one AI label per user and assistant turn. The AI
annotator identity is recorded in each row; second-rater and adjudication fields remain empty, so
all quality claims remain open.

`experiments/v1_366_dialogue_annotation_evaluation.py` checks split integrity, label values, audit
coverage, raw agreement, Cohen's kappa, and adjudication of disagreements. On the feasibility batch,
all primary fields are filled but the evaluator correctly reports `incomplete`: its selected audit
conversations have no independent second labels. The evaluator supports `--strict` to prevent
incomplete annotations from being reported as a completed evaluation, and `--self-test` for the agreement formula,
split-leakage checks, and required label provenance.

`experiments/v1_382_dialogue_feasibility_batch.py` selects whole conversations from train only,
copies their cited transcripts, and deterministically assigns 20% of selected conversations for
independent double labeling. The 40-conversation batch contains 563 user turns and 650 assistant
turns. Its current primary labels are Codex-authored; the designated reliability audit remains
incomplete. The comparison in `v1_385_provisional_dialogue_label_comparison.py` reports label
agreement and coverage only, not accuracy. Candidate frames may be induced from training
conversations. Do not use dev/test conversations for induction or mark frames held-out validated
from agreement with the same annotator's labels.
