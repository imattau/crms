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

## Where the project is now

CRMS has a useful foundation: searchable source text can be packaged with a
portable SQLite model; facts and rules can be stored and cited; bounded
inference can return verified proofs; exact math and several learned
transformation and code paths compose; and question handling has improved on
controlled held-out sets. These are component results, not a general assistant
evaluation.

The largest remaining gaps are end-to-end breadth and reliability. Natural
language still misses many paraphrases and can select a wrong sentence; dialogue
context can bind to the wrong entity; self-learning from derived outputs is not
yet a governed general loop; rule induction and recombination have only bounded
coverage; reasoning has defined search and integrity limits; math, coding,
translation, and creative writing remain narrow; and user-intent/dialogue-move
learning remains research. The current comparison document accurately says
that broad capability parity is not supported.

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

### Stage 0 — Establish the project scorecard

**Do first.** Gather the existing experiments, user-driven chat failures, and
design-specific benchmarks into a small, pinned capability suite. Run each
case through the user-facing chat path as well as the component API where
appropriate. Keep test corpora separate from training or induction data.

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
test and a current result; known failures remain in the suite. No change is
accepted solely because a hand-picked demo improved.

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

## Immediate next work

1. Finish the current dialogue topic-anchor regression and review the existing
   uncommitted dialogue changes without folding unrelated edits together.
2. Add the user's cross-topic, source-only, multi-part, and answer-explanation
   cases to the pinned chat-level scorecard.
3. Run the scorecard on the current committed revision and record the actual
   baseline before the next behavior change.
4. Choose the next recombination/self-learning-rule experiment from a held-out
   combination that exercises a rule component and a genuinely new composition.
5. Continue reasoning work against the gap list and benchmark, especially
   natural-language routing, integrity behavior, and verified explanations.
