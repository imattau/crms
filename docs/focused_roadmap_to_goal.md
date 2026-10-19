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

## Focused plan from the current checkpoint (2026-10-20)

### Review of direction

CRMS remains on track in its design principles, but it is not yet on track for
the breadth of its goal: it has an inspectable knowledge/proof substrate and
bounded examples of learning and composition, not a broadly capable integrated
assistant. A 70B-class model is an interaction and task-range reference only;
no live model run or parity claim is needed.

The highest-leverage capability target remains **recombination through
self-learned rules**, checked by **reasoning**. **Dialogue and contextual user
intent are priority research areas** and should advance alongside that core,
not wait for it to finish. The immediate engineering priority is eliminating
wrong answers across turns. More corpus volume and storage migration support
the goal but cannot substitute for transfer, task completion, or safe context.

### Ordered work from here

1. **Finish the end-to-end dialogue baseline.**
   Focused fixes now ground pronoun-led answers in their source paragraph,
   preserve the latest explanation target, reject mismatched entity switches,
   and retain source-only context when its citation remains valid. The focused
   regressions pass, but the full multi-turn conversation has not yet been
   captured as one compact, reproducible clean-process transcript. Run it at a
   recorded revision with named topic switches, follow-ups, source-only
   answers, an unanswered turn, `why?`, “and Italy?”, “what did I just ask?”,
   and “the first one”. Treat any result from a truncated diagnostic run as
   inconclusive.

   **Gate:** no wrong-entity sentence is returned; a citation supports the
   exact answer shown; current topic and explanation target update separately;
   source-only evidence remains usable when valid; unresolved references
   clarify or abstain. Keep passing short follow-ups and named switches.

2. **Make turn state explicit and stable.** Only after the transcript pins a
   failure, adjust context lifecycle so topic, referents, open slots, last
   question, and last explainable answer have explicit update/clear rules.
   Preserve valid context across source-only and review-only turns, but do not
   let failed or ambiguous turns silently reuse an old answer. Add end-to-end
   coverage for elliptical topic changes, repair, correction, history, and
   ordinal references; unsupported dialogue requests should get a precise
   clarification or abstention. Refactor the long `turn()` path only where
   stages improve these tested boundaries.

   **Gate:** the same behavior survives save/reload and fresh-process runs;
   `why?` never targets a stale answer; no context update makes a factual claim
   accepted or changes its evidence status.

3. **Advance recombination and self-learning rules through chat.** Build on
   the passing contrastive procedure-learning slice. Vary learned components,
   connective rules, argument roles, order, values, and paraphrased requests;
   hold out combinations and source examples. Include a matched unsupported
   composition and a missing-middle-step case. Keep learner and validator
   independent.
   Retain each rule's examples, source lineage, holdout result, status, and
   tested scope.

   **Gate:** at least one genuinely unseen composition works through ordinary
   chat, passes an independent task validator, and survives save/reload with
   lineage intact; near-miss and unsupported cases abstain. Prefer one new
   transferred composition over more demonstrations of an existing one.

4. **Connect reasoning to those compositions and govern derived learning.**
   Route natural-language questions to proof paths; test joins, cycles,
   explicit integrity constraints, contradictions, missing premises, proof
   explanations, and incomplete search. Develop write-back as proposal →
   independent verification → derived record, with source lineage and
   dependency invalidation. Keep derived items separate and lower-trust than
   taught/source evidence; no autonomous promotion until drift and correction
   propagation are measured.

   **Gate:** every positive conclusion has an independently verified proof;
   cycle, conflict, and search limits are not rendered as unqualified truth;
   changing a dependency marks derived records stale; chat and engine outcomes
   agree. A derived case cannot validate itself.

5. **Advance dialogue intent and the move-learning pilot in parallel.**
   Evaluate explicit topic, referent, open-question/slot, task-phase, user-act,
   and task-intent state on conversation-held-out flows. Continue dialogue-move
   induction as research using Codex-attributed labels and a source-disjoint
   pilot. Compare with the scripted baseline on task progress, inappropriate
   actions, coverage, abstention, and annotation effort; label agreement alone
   is not correctness.

   **Gate:** explicit state fixes the pinned failures without changing facts.
   A learned move policy gets runtime authority only if it improves held-out
   task progress or reduces unhelpful turns without increasing inappropriate
   actions; otherwise keep it as a research result.

6. **Broaden math, coding, translation, and creative work through natural
   language.** Grow one bounded task family at a time, with held-out requests,
   negative cases, a domain validator, provenance, and multi-turn repair.
   Prioritize combinations across learned components. Separate factual claims
   from invented fiction and evaluate creative quality independently from
   factuality.

   **Gate:** each task family is demonstrated through chat on held-out wording,
   with correctness, coverage, abstention, completeness, and cost reported.

7. **Finish portable distribution and run a release-shaped evaluation.**
   Complete the one-file SQLite build/copy/query/learn/export/reload contract
   for searchable source text, rules, knowledge, and provenance, while keeping
   original ingestion files optional at inference. Evaluate a clean copy on a
   fixed cross-domain suite; report task breadth, wrong answers, abstentions,
   dialogue progress, proof/source validity, latency, memory, and package size.

   **Gate:** the copied model works without its original source files and
   preserves semantics and lineage after supported learning/export/reload.
   Publish remaining coverage limits. Keep the overall goal in progress until
   a diverse task distribution demonstrates broad natural-language coverage,
   reliable dialogue, and correct composition.

### Execution rules

- Preserve each reported failure as a full-turn regression before changing
  behavior, and record the tested commit/tree identity.
- Keep training/induction and held-out sources disjoint. Report coverage,
  correctness, wrong answers, abstention, completeness, provenance, and
  resource costs separately.
- Do not let retrieval scores, fluent wording, corpus size, or self-generated
  outputs authorize facts or rules.
- Work in small reviewable slices; run the focused runtime check and nearby
  regressions, then commit only the intended files. Preserve concurrent and
  user-owned changes.

### Immediate checkpoint

The next work should stay on the integration path, not widen into another
standalone corpus scan:

1. **Close the observed dialogue coverage gaps.** The new 30-turn transcript
   (`v1_427`) and focused regressions pass their safety checks: topic switches
   do not leak Colosseum/Eiffel evidence, `why?` follows the latest answer,
   and history updates across abstention. Through the same transcript, fix
   only demonstrated gaps: recovery to a source-indexed entity after an
   unrelated abstention; paragraph-local linking of “Eiffel Tower” to “the
   tower” when the named subject is explicit; and possessive follow-up
   resolution such as “What is its capital?”. Extend the same multi-turn test
   with save/reload and a negative case that tries to transfer an antecedent
   across paragraphs.
2. **Advance recombination and self-learning rule transfer.** Use ordinary chat to
   test a genuinely unseen composition from learned components, plus a
   contrastive near-miss and missing-step case. Verify the result with an
   independent task check and preserve rule examples, holdout boundary, and
   lineage. Do not count more demonstrations of an existing composition as
   transfer. Keep this core capability active alongside the dialogue work.
3. **Strengthen reasoning on the composition path.** Reuse the unseen
   compositions to exercise proof and task validators, then target explicit
   integrity constraints, contradiction handling, missing premises, and
   incomplete-search reporting. Preserve independence between the learner and
   validator; a derivation cannot validate itself.
4. **Keep role/type corpus discovery exploratory until it earns a gate.**
   The `v1_335` diagnostic now describes its metric as typed support after
   page-title disambiguation; it does not claim to apply a separate
   predicate-head/type filter. The 20-window run yields seven one-pair
   hypotheses and none at the two-pair threshold after disambiguating
   `Benguela` city from `Benguela Province`. This removes the observed strong
   false candidate, but it does not license any relation alignment. The next
   useful evidence is independent held-out precision on cited positive and
   negative examples, including valid cases such as `capital of`.

**Near-term completion condition:** the clean-process dialogue suite has no
wrong-entity answers or stale explanations, its known coverage gaps are
measured, and one held-out recombination works through chat with independent
validation and recoverable lineage. Continue the contextual-intent and
dialogue-move pilot as a priority research track; compare it with the explicit
baseline before granting it runtime authority. Do not declare the broader goal
complete at this checkpoint.
