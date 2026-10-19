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

### Overall alignment

The project is still aimed at the right goal, but it has a trustworthy,
inspectable substrate rather than a broad integrated assistant. The 70B-class
reference is useful for identifying the experience gap; no live model run is
needed to plan against it. Progress should mean more held-out tasks completed
through ordinary language without increasing unsupported answers or losing
lineage.

The central capability bet remains **recombination and self-learning rules**:
CRMS must combine learned pieces in cases it was not directly shown. Reasoning
must verify those compositions and remain reachable from chat. **Dialogue and
contextual intent are a priority research area**, not a final polish phase; the
conversation state and its regressions can be improved now, while corpus-induced
moves remain an experiment. SQLite distribution is enabling infrastructure,
not an end goal. Increasing corpus size cannot compensate for weak retrieval,
language transfer, or answer selection.

### Execution sequence

#### Next work cycles

The sequence below is the near-term queue. Keep each cycle small enough to
review, reproduce, and commit independently. Dialogue stays active alongside
the core capability work; it is not deferred until the end.

**Current next slice — make topic switches safe across source-only turns.**
The latest user-driven chat review shows that short follow-ups and explicitly
named topic changes work in the tested corpus, but a pronoun-led source sentence
can still bind to the wrong entity after a switch. Source-only answers also
need to preserve usable context without leaving `why?` attached to an older
answer. Treat this as a correctness issue before adding more dialogue coverage.

1. Freeze the full Rome/Paris and Eiffel Tower/Colosseum transcripts as
   end-to-end regressions, including the known-good follow-ups and named
   switches.
2. Bind pronoun-led evidence to the active entity using local discourse
   evidence (such as its paragraph or explicit entity anchor); if ownership is
   ambiguous, ask or abstain instead of choosing whichever entity happens to
   have a supported answer.
3. Separate context retention from answer status. Preserve source-only topic
   context while its citations are valid; update or clear the explanation
   target on every turn so `why?` never explains a previous topic after a new
   unresolved turn.
4. Add the reported elliptical switches (“and Italy?”, “and the Colosseum?”),
   question-history requests (“what did I just ask?”), and ordinal references
   (“the first one”) as explicit probes. Implement only the smallest behavior
   supported by the discourse state; otherwise clarify or abstain.
5. Keep the code-structure review findings separate from behavior fixes.
   Refactor `turn()` or the resolver only when the regression boundary yields
   clearer, independently testable stages without changing established
   routing behavior.

**Gate:** the complete transcript passes through a fresh chat process; no
pronoun-led evidence is attributed to a different active entity; a source-only
answer remains followable while its evidence is available; and `why?` targets
the latest answer or says there is no current answer to explain. Existing
short follow-ups, named switches, and abstentions remain intact. Record the
tested commit and do not infer broad dialogue competence from these cases.

**Cycle 1 — Re-pin the integrated baseline and close one user-visible failure.**
Run the selected scorecard from a clean scratch location on a recorded commit,
then add the newest user-reported dialogue transcripts to it. First verify
that the direct-search intent frame added in `6d35723` reaches useful retrieval
and cited answers through ordinary chat. In the same cycle, lock the
Colosseum/Eiffel topic-switch case, source-only referent retention, and `why?`
targeting as full-turn regressions. Fix only reproduced failures.

**Gate:** the natural-language request reaches the intended evidence route;
the multi-turn regression has no wrong-entity answer or stale explanation;
all previously passing short follow-ups and named topic switches remain green.
The result report names the tested commit and separates answer quality from
intent-label agreement.

**Cycle 2 — Demonstrate learned recombination beyond the demonstrations.**
Use a small source-disjoint matrix of learned components, connective rules,
argument roles, operation order, and values. Drive it through chat, including
contrastive requests, missing middle steps, and paraphrased instructions. Keep
the validator independent of the learner and preserve each rule's examples,
holdout split, status, and lineage. Prefer one new composition that transfers
over adding several more examples of an existing composition.

**Gate:** at least one genuinely unseen composition succeeds through chat and
passes the independent validator; a matched unsupported composition abstains;
the learned rule and its lineage survive save/reload. A direct engine-only
pass does not meet this gate.

**Cycle 3 — Govern derivation and connect reasoning to the same interaction.**
Extend proposal-only derived cases through verification, provenance, and
dependency invalidation. In parallel, use chat regressions for relation
routing, cycles/integrity constraints, conflict, missing-premise prompts, and
proof explanations. Keep derived knowledge lower-trust and separate from
taught/source evidence; do not enable autonomous promotion in this cycle.

**Gate:** tampered or unsupported conclusions are refused; a correction to a
premise marks its dependent derivations stale; chat and direct proof results
agree; no incomplete search or conflict is rendered as an unqualified answer.

**Continuing lane — Dialogue and contextual intent.** Keep improving the
bounded explicit discourse state while the cycles above run. Test topic,
referent, open-slot, task-phase, user-act, and task-intent updates on
conversation-held-out flows. Continue the dialogue-move induction pilot as a
research lane, and only grant it runtime authority if it improves task
progress or reduces unhelpful turns without increasing inappropriate moves.

**Bounded enabling lane — Portable SQLite model.** Finish the build/copy/
query/learn/export/reload contract as a time-boxed infrastructure task. Do not
hold capability experiments hostage to the entire JSON migration: use the
current supported storage path for experiments and schedule migration work
when it directly blocks distribution or persistence validation.

1. **Pin a trustworthy end-to-end baseline.** Keep the scorecard small enough
   to run routinely and include fixed positives and negatives for source
   selection, paraphrases, multipart requests, multi-turn context, reasoning,
   recombination, and domain tasks. Record commit/tree identity and separate
   coverage, wrong answers, abstention, completeness, citation/proof validity,
   and resource cost. Preserve the full transcript for every dialogue failure.

   **Gate:** every planned change names the probe it should improve and the
   negative controls it must preserve; reports are reproducible from a clean
   scratch environment.

2. **Complete the portable knowledge foundation.** Finish the one-file SQLite
   model contract: searchable source text, knowledge, rules, provenance, and
   supported learned records travel together; original source files are not
   required at inference. Verify transactional updates, compatibility paths,
   export/reload, and a clean-location query. Keep read-only distributable data
   separate from writable user learning where needed. Keep this bounded to the
   distribution and persistence contract; it must not displace the capability
   work that follows.

   **Gate:** a clean copy works without ingestion files, and supported learning
   can be saved/exported/reloaded without changing provenance or semantics.

3. **Finish the highest-risk chat correctness slice.** Exercise full sessions
   with topic changes, unresolved pronouns, source-only evidence, failed and
   review-only answers, and `why?`. Context updates must distinguish “no
   answer” from “no valid current topic”; pronoun-led source sentences must be
   tied to the active entity or abstain. Then cover multi-part omissions and
   unrelated pending candidates. Retain the successful short follow-ups and
   named switches as controls.

   **Gate:** the complete transcript passes through a fresh chat process; no
   wrong-entity answer or stale explanation is emitted, and source evidence is
   clearly distinguished from accepted knowledge.

4. **Prove recombination and learned-rule transfer.** Build a source-disjoint
   grid that varies components, connective rules, argument roles, order, and
   values. Test unseen combinations and contrastive near-misses through the
   natural-language interface. Keep candidate discovery, review, holdout
   validation, and licensing distinct. Preserve examples, split, status, and
   lineage for every induced rule.

   **Gate:** a learned rule supports at least one genuinely unseen composition
   through chat, contrastive and unsupported-middle-step cases abstain, and an
   independent task/proof validator accepts the output. Save/reload preserves
   the same rule status and lineage. This milestone takes precedence over
   adding more demos of already-supported combinations.

5. **Govern derivation-based self-learning and strengthen reasoning.** Keep
   write-back as proposal → independent verification → derived record. Test
   deduplication, retrieval value, dependency invalidation, correction
   propagation, and trust weighting. In parallel, close reasoning gaps in
   natural-language routing, cycle/integrity checks, conflict semantics,
   missing-premise prompts, incomplete search, and proof explanations. Keep
   taught evidence, source evidence, induced rules, and derived cases separate.

   **Gate:** no derived record validates itself; changed premises stale their
   dependents; verified chat conclusions agree with direct engine calls; and
   cycles, conflicts, or search limits are never reported as unqualified
   truth/falsehood. Retain only stages that reduce errors or improve a measured
   user outcome.

6. **Advance contextual intent and dialogue alongside the core work.** First
   model the current topic, referents, open question/slot, task phase, user act,
   and task intent as bounded explicit state. Test topic switches, repairs,
   corrections, clarification, and multi-turn tasks on held-out conversations.
   Continue one source-disjoint dialogue-move pilot with Codex-attributed
   primary labels. Compare with deterministic handlers on task progress,
   inappropriate actions, coverage, abstention, and annotation cost. Label
   agreement is not accuracy; do not grant candidate frames runtime authority
   based on surface frequency alone.

   **Gate:** explicit state prevents the locked topic/stale-answer failures and
   intent never mutates factual knowledge. A learned move/intent policy ships
   only if held-out conversations improve task progress or reduce unhelpful
   turns without increasing inappropriate actions. Otherwise keep it as a
   research result and continue improving the explicit baseline.

7. **Broaden math, coding, translation, and creative work through the shared
   natural-language interface.** Grow one bounded request family at a time.
   Each needs independently held-out wording, negative cases, a domain-specific
   validator, provenance, and multi-turn repair. Prioritize cross-component
   compositions. Mark generated fiction separately from evidence-backed
   claims; score creative coherence and revision separately from factuality.

   **Gate:** capability is demonstrated in chat on held-out requests, not only
   by a typed command or curated demo; report accuracy, abstention, and
   incomplete work for each domain.

8. **Run release-shaped evaluation.** Run the fixed cross-domain suite against
   the portable model from a clean location. Report package size, latency,
   memory, and per-capability quality, including accuracy, wrong answers,
   abstention, completeness, dialogue task progress, and proof/source validity.

   **Gate:** fixed negatives pass and remaining coverage limits are explicit.
   Compare breadth and interaction qualitatively with the 70B-class reference;
   do not claim parity unless representative evidence supports it.

### Working rules

- Inspect existing user-owned changes before touching them; preserve unrelated
  files and scratch state.
- Keep each implementation slice reviewable, run its focused runtime checks,
  then the relevant regressions, and commit the slice when stable.
- Add every discovered failure to the fixed suite before changing behavior.
- Do not use more data, candidate counts, or fluent wording as a substitute for
  held-out transfer, task validation, or evidence.
- Keep the overall goal in progress until a defined, diverse task distribution
  demonstrates broad natural-language coverage, reliable interaction, and
  correct composition across knowledge, rules, reasoning, and dialogue.
