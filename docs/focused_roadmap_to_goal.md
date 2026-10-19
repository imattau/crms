# Focused roadmap from the current CRMS to its goal

**Purpose:** turn the existing designs and measured work into one ordered plan.
This document coordinates the detailed design documents; it does not replace
them or claim that CRMS is close to broad-model capability.

## The goal

Build a lightweight, distributable language system that can understand and
complete a broad range of ordinary user requests, continue across turns,
combine knowledge and learned procedures, and improve from evidence and use.
Its answers and artifacts should remain inspectable, correctable, and explicit
about uncertainty. The system may use different mechanisms for different
tasks, but it must not present unsupported text as verified knowledge.

The 70B-class comparison is a capability reference, not an architecture target
or parity claim. Progress means improved task coverage and interaction while
keeping correctness, abstention, source support, proof integrity, and resource
use measurable.

## Current checkpoint (2026-10-20)

CRMS has a useful foundation: searchable source text and reviewed language
alignments can be packaged in a portable SQLite model; facts and rules can be
stored and cited; bounded inference returns independently verified proofs;
learned transformations compose across bounded list, math, and code tasks; and
some question handling transfers on controlled held-out sets. The 2026-10-20
working-tree scorecard records selected passes, but it is a component
scorecard—not a general assistant evaluation. The 1,200-document audit has
strong canonical retrieval and weak paraphrase coverage, and dialogue-move
candidate transfer is still a label-agreement diagnostic, not a learned policy.

The project is past the “build a baseline” stage. It is now in the harder
integration stage: make independently useful capabilities compose through the
chat path, preserve their evidence and state, and measure them on held-out
inputs. Portable distribution has an important end-to-end proof for a reviewed
predicate alignment and embedded text, but SQLite migration and learned-memory
coverage are not complete.

The largest remaining gaps are end-to-end breadth and reliability. Natural
language still misses paraphrases and can select related but non-answering
sentences. Recent topic-anchor tests address a reported cross-topic pronoun
failure, but the whole multi-turn path still needs a pinned regression suite.
Recombination and learned-rule transfer have promising bounded demonstrations,
not broad compositional coverage. Derivation/practice exists in bounded forms,
but there is no general governed write-back loop. Reasoning has strong graph
tests but remaining integration and integrity edges. Math, coding, translation,
and creative writing are narrow. User-intent modeling has an explicit state
baseline and research data; dialogue-move candidates have not earned runtime
authority. Broad-model parity remains unsupported.

## Priority order

1. **Trustworthy end-to-end behavior and an authoritative evaluation set.**
2. **Recombination and self-learning rules**, with derivation learning gated by
   verification and provenance.
3. **Reasoning**, including integrity, natural-language routing, and honest
   partial results.
4. **Dialogue and contextual user intent**, tested as a first-class capability
   and not reduced to fact volume.
5. **Domain breadth** in math, coding, translation, and creative tasks through
   shared natural-language interfaces and verifiable task contracts.
6. **Scale and release quality:** portable storage, source-text distribution,
   repeatable evaluation, and deployment costs.

These are priorities, not isolated silos. The evaluation and storage work
supports every later stage. Dialogue and the domain work can progress in
parallel once the safety and evaluation contracts are in place.

## Staged plan and exit gates

### Stage 0 — Maintain the project scorecard

**Current status: established, needs consolidation and upkeep.** The current
scorecard is in [benchmark baselines](benchmark_baselines.md); the large-corpus
audit and the dialogue issue reports supply additional fixed probes. Keep the
user-facing chat path as the acceptance target, with component tests for fault
localization. Preserve known wrong-answer, abstention, and context-switch cases
as separate outcomes. Keep test corpora separate from training or induction
data.

The scorecard should include:

- ordinary-language understanding: canonical requests, paraphrases, inverse
  forms, multi-part requests, and unsupported requests;
- source retrieval and answers: correct sentence, wrong sentence, ambiguity,
  citation, and quoted-evidence versus accepted-fact labels;
- recombination and rule learning: held-out components and unseen combinations;
- reasoning: chains, joins, cycles, contradictions, integrity constraints,
  missing premises, budget exhaustion, proof verification, and chat routing;
- dialogue: topic changes, anaphora, clarification, correction, open questions,
  intent, and appropriate abstention;
- math, coding, translation, and creative tasks with task-specific correctness;
- repeatability, latency, memory, and package size where they affect use.

Use human-written probes alongside generated controls. Codex may produce
primary dialogue labels as authorized, but record their provenance and report
agreement with those labels—not accuracy or independent validation. Hold out
whole source documents or conversations. Keep answer accuracy, wrong answers,
abstention, coverage, completeness, provenance, and interaction quality as
separate measures.

**Exit gate:** every capability claim in the roadmap points to a reproducible
test and a current result; known failures remain in the suite. This gate is
substantially met for the current bounded components, not yet for one integrated
cross-domain assistant suite. No change is accepted solely because a hand-picked
demo improved.

### Stage 1 — Complete the portable knowledge foundation

Finish the existing SQLite migration in the direction already chosen: one
portable model database should carry searchable extracted source text and
versioned knowledge, rules, provenance, and learned records. Original source
files may be used to ingest knowledge but must not be required to distribute
or query the model. Keep JSON import/export for compatibility during migration.

Make writes transactional. Preserve source citations and distinguish taught,
accepted, induced, and derived records. Define the writable overlay policy so a
shared distributable model is not silently mutated. Ensure newly accepted or
learned knowledge can be exported back into a new model database.

**Exit gate:** a model can be built, copied to a clean location without its
input files, queried, updated through its supported learning path, exported,
reloaded, and queried again with equivalent answers, provenance, and rules.
Migration failure leaves the previous model usable.

Detailed design: [SQLite memory design](sqlite_memory_design.md).

### Stage 2 — Close the highest-risk language and dialogue failures

Use the scorecard to fix failures that can produce a confident but wrong
answer before expanding accepted wording. The next dialogue slice should cover
the recently reported cross-topic case: an unresolved “it” after switching
from Eiffel Tower to Colosseum must stay with the Colosseum, and a sentence
that cannot be tied to that entity must not be quoted as its answer.

Then address the related end-to-end behaviors: keep source-only referents when
their citations remain valid; associate “why?” with the latest answer; disclose
omitted parts of multi-part questions; separate unrelated pending review items
from a direct answer; and make retrieval return the best answer-bearing
sentence with its source. Keep the direct answer, evidence, candidate fact,
and accepted fact visibly distinct.

Refactor dialogue processing into inspectable stages only where the regression
suite demonstrates a benefit: classify the user act and intent, resolve
referents, answer or abstain, then update bounded discourse state. Treat
malformed saved state as recoverable rather than a startup failure.

**Exit gate:** all locked regressions pass through actual chat; entity switches
do not produce a wrong-entity answer; unsupported sub-questions are disclosed;
and citations point to the exact evidence shown. A new paraphrase must not
increase wrong answers without being caught by the fixed negatives.

Detailed designs: [natural-language handling](design_natural_language_handling.md),
[chat UX](design_chat_ux.md), [natural-language replies](design_natural_language_replies.md),
and [conversation](design_conversation.md).

### Stage 3 — Make recombination and learned rules the central capability test

The key question is whether CRMS can learn useful components and combine them
in combinations it was not shown directly. Expand the current bounded examples
from list procedures, math, and code into a cross-product of held-out
components, orderings, input values, and natural-language requests. Separate
component learning from connective/rule learning, and include contrastive
examples so the system learns when a rule does not apply.

For every induced rule, retain its examples, source lineage, validation split,
status, and tested scope. Validate on held-out examples and unseen compositions
before licensing the rule. Keep failed candidates reviewable; do not let a
high candidate score or repeated self-generated output promote a rule by
itself. Test unsupported middle steps, ambiguous matches, and invalid
compositions as first-class cases.

Then develop derivation-based learning as a gated extension: retrieve, compose,
verify, and only then propose a derived case for storage. Derived cases must
remain separate from taught evidence, carry complete lineage, be lower-trust
where appropriate, and become reviewable or invalid when a dependency changes.
Begin with opt-in proposal and review; automatic promotion is out of scope
until drift, correction propagation, deduplication, and storage growth have
measured controls.

**Exit gate:** on source-disjoint held-out tasks, learned rules transfer to
unseen combinations; the composed artifact or conclusion passes an independent
validator; missing/unsupported stages abstain; and all constituent lineage is
recoverable. A derived case is never treated as primary evidence for itself.

Detailed designs: [learning dynamics](design_learning_dynamics.md),
[evidence independence and transfer](design_evidence_independence_and_transfer.md),
and [domain expansion](design_domain_expansion.md).

### Stage 4 — Strengthen reasoning as a user-visible capability

Extend the existing proof engine only against explicit benchmark gaps. Keep
natural-language questions routed to the right relation and proof path. Add
integrity declarations and contradiction handling where their semantics are
explicit; never infer a relation constraint merely from its label. Distinguish
unknown, false under a declared closed-world scope, conflicting evidence,
missing premises, and incomplete search. Verify proofs before rendering an
explanation, and disclose proof-list truncation or search-budget exhaustion.

Use missing-premise results to offer a precise next step, without silently
inventing premises. Prioritize selective joins and broad graph-shape/resource
measurements before increasing bounds or adding a richer rule language.

**Exit gate:** each positive answer has an independently verified proof;
negative and conflict answers match their declared evidence semantics;
cycles and integrity violations are surfaced; budget limits never become
falsehood claims; and chat-level questions reach the same verified engine
results as direct calls.

Detailed design: reasoning sections in
[learning dynamics](design_learning_dynamics.md), plus the proof-explanation
and routing requirements in [natural-language replies](design_natural_language_replies.md).

### Stage 5 — Develop dialogue and user intent with a falsifiable pilot

Dialogue is a priority research area, but corpus-induced dialogue moves and
context-conditioned intent should earn runtime status. First stabilize the
explicit discourse record needed for referents, topic, open question/slot,
task phase, and previous move. Evaluate it on conversation-held-out flows
including topic switches, repairs, corrections, clarifications, and multi-turn
tasks.

In parallel, run one source-disjoint dialogue-move pilot in one declared domain.
Use cited utterances, Codex-attributed primary labels, and an independent
conversation-level audit only when a stronger quality claim is needed. Compare
induced moves with the explicit scripted baseline on appropriateness,
inappropriate-action rate, coverage, abstention, task progress, and annotation
cost. Do not integrate candidate frames just because they reproduce frequent
surfaces.

**Exit gate:** discourse state prevents the known topic-switch and stale-answer
failures; intent updates do not overwrite facts or unsupported slots; and any
induced move system measurably improves task progress or reduces maintenance
without increasing inappropriate moves. Otherwise keep the explicit baseline
and narrow the research claim.

Detailed designs: [contextual user intent](design_user_intent_model.md),
[explicit dialogue moves](design_dialogue_moves.md), and
[annotation protocol](dialogue_move_annotation_protocol.md).

### Stage 6 — Broaden task domains through the shared language interface

Expand math, coding, translation, and creative writing as separate, testable
domains. For each, define a natural-language request set, exact task contract,
positive and refusal cases, artifact validation, and provenance. Build broad
coverage only after each small contract works; compose domains only when both
component contracts and their combined lineage pass.

Prioritize usable slices over nominal feature checklists: exact math with more
ordinary wording; bounded code generation with execution or property checks;
translation with alignment, slot preservation, and ambiguity handling; and
creative generation with an explicit boundary between invented content and
factual claims. All should be reachable through the CRMS natural-language
interface, while still allowing typed commands for inspection and control.

**Exit gate:** each domain has independently held-out requests, a task-specific
validator, measured coverage and abstention, and no unsupported success claim.
Cross-domain requests preserve each stage's lineage and disclose incomplete
stages.

Detailed design: [domain expansion](design_domain_expansion.md).

### Stage 7 — Evaluate breadth and publish the boundary

Run the full scorecard against a fixed, diverse task distribution and the
current checked-in model. Report task-level coverage, correctness, wrong
answers, abstentions, multi-part completeness, dialogue quality, proof/source
quality, latency, memory, and model size. Compare the interaction range
qualitatively with the documented 70B-class reference; a live large-model run
is unnecessary unless it answers a specific unresolved question.

Keep the overall goal marked **in progress** unless a defined task distribution
shows substantial breadth and reliable interaction. If a domain remains
narrow, say so and continue to measure it separately. A strength in
inspectability, resource use, or correction does not compensate for missing
coverage; breadth does not compensate for wrong answers or untraceable claims.

## Ongoing rules for every stage

- Preserve failing user examples as regression cases, including the full
  conversation context that caused them.
- Change one capability boundary at a time; compare against the pinned baseline.
- Track wrong answers and harmful omissions separately from abstention and
  coverage.
- Keep generated labels, inferred rules, derived cases, taught facts, and source
  text distinguishable in storage and in the user-visible answer.
- Require citations for source claims and independent proof validation for
  derivations. A fluent explanation does not substitute for either.
- Promote an improvement only if it generalizes to held-out sources and does
  not quietly worsen the fixed negative cases.
- Do not expand corpus volume as a substitute for improving retrieval,
  recombination, reasoning, dialogue, or task execution.

## Focused execution plan from this checkpoint

Work in short, reviewable slices. Keep the current user-owned working-tree
changes intact; inspect and test them before incorporating any of them. For
each slice, add the failure or capability to the fixed scorecard, run a focused
runtime experiment, then run the relevant regression subset. Commit only the
slice's files. Avoid broad corpus expansion until the retrieval and answer
selection metrics improve.

### 1. Lock down end-to-end correctness

First turn the latest dialogue and natural-language findings into repeatable
chat-level regressions: named topic switch followed by “it”; source-only topic
switch and follow-up; “why?” after a switch or refusal; wrong-entity sentence
rejection; explicit multi-part omission; and unrelated pending review state.
Inspect the uncommitted dialogue tests and report before deciding what to keep.
The 2026-10-20 topic-anchor test is useful evidence, but does not by itself
replace a full-session test of every state transition. Add answer-bearing
sentence selection and relation-paraphrase negatives to the same scorecard.

**Gate:** known chat regressions pass in a clean scratch session; no wrong-topic
answer is emitted; unsupported subparts and source-only evidence are labeled
plainly. Update the benchmark report with working-tree identity and actual
counts.

### 2. Make recombination and learned rules the main capability bet

Extend the current held-out transfer tests around one compact, source-disjoint
task grid. Vary learned components, connective/rule structure, argument roles,
ordering, and values independently; include unseen compositions and near-miss
controls. Use the existing review → holdout validation → acceptance path for
discovered rules. Prefer experiments that demonstrate a new composition over
more examples of an already-supported one. Record coverage, precision, and
abstention separately.

**Gate:** a learned rule works on held-out components and a genuinely unseen
composition, fails its contrastive controls, and retains recoverable examples,
validation split, and lineage. A failure narrows the licensed scope rather than
lowering the acceptance threshold.

### 3. Govern derivation-based learning

Keep `practice` and derived-case storage opt-in while testing deduplication,
novelty, retrieval usefulness, dependency invalidation, correction propagation,
and bounded storage on realistic repeated tasks. Derived outputs must remain
separate from taught/source evidence and be independently reverified before
reuse. Do not auto-promote generated dialogue, facts, rules, or explanations.

**Gate:** corrections to any dependency make descendants stale or unusable;
repeated practice does not create unbounded duplicates; a derived case never
supports itself; and the measure shows a held-out benefit over re-derivation
without increasing wrong answers. Until then, retain proposal/review semantics.

### 4. Close reasoning integration gaps

Prioritize natural-language routing to verified inference, cycles and declared
integrity constraints, explicit contradiction/unknown/incomplete distinctions,
and proof explanations checked against the proof and parsed back to their
claims. Use graph-shape and budget tests to localize limits. Preserve the
existing verified graph behavior; do not raise search bounds without a measured
need.

**Gate:** chat and direct engine agree; each positive conclusion has a verified
proof; cycles or integrity violations cannot silently yield an ordinary
positive; and incomplete search is not reported as false or unknown without
qualification.

### 5. Advance dialogue and contextual intent as a measured research track

Keep explicit discourse state and deterministic handlers as the runtime
baseline while the topic-switch regressions are being closed. Continue the
source-disjoint dialogue pilot and Codex labeling under the existing annotation
protocol. Treat exact-surface frame agreement as candidate yield only; require
an independent label audit before claiming label quality, and compare any
contextual frame against the scripted baseline for task progress and
inappropriate moves. Do not let a dialogue label or user intent become a fact.

**Gate:** learned intent or moves improve held-out task completion or reduce
unhelpful turns without increasing inappropriate actions; otherwise leave them
as inspectable research artifacts and improve the explicit baseline.

### 6. Broaden domains only through validated natural-language contracts

For math, coding, translation, and creative writing, expand one bounded request
family at a time through the shared natural-language interface. Give each a
held-out set, negative cases, task-specific validator, provenance, and
multi-turn repair probes. For creative work, measure topic fit, coherence, and
revision separately from factual grounding. Compose domains only after their
individual contracts and combined lineage pass.

**Gate:** no domain is called supported based on a command-only demo; the chat
path handles held-out ordinary wording, reports limits, and passes its own
validator with measured coverage and abstention.

### 7. Reassess breadth and release readiness

After these slices produce stable results, run the maintained scorecard against
the portable model from a clean location, without source files that are meant
to be embedded. Report per-domain correctness, wrong answers, abstention,
completeness, dialogue task progress, evidence/proof integrity, latency, memory,
and package size. Compare interaction breadth qualitatively with the documented
70B-class reference; make no parity claim unless a representative evaluation
supports it.

**Release gate:** a clean install can query, learn through supported paths,
export/reload, and reproduce equivalent supported behavior with lineage; the
fixed negatives pass; and all remaining narrow areas are clearly documented.
