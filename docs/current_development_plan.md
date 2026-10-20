# CRMS development plan

**Reviewed:** 2026-10-20
**Status:** architecture is aligned; the overall capability goal remains unmet.

For the concise, decision-oriented path from the current state to the project
goal, see the [goal execution plan](goal_execution_plan.md). This document
retains the fuller implementation history and experiment detail.

## Destination

Build a lightweight, distributable language system that can understand and
complete a broad range of ordinary requests, carry useful context across
turns, recombine knowledge and procedures, and improve from evidence and use.
Its answers and generated work should be inspectable, correctable, and honest
about uncertainty. The natural-language interface should eventually support
coding, math, translation, creative work, and other domains.

Strong 70B-class instruction models are a reference for task range and user
interaction, not a parity claim or a required architecture. No live 70B run is
needed to develop against that reference.

## Where the project stands

CRMS has searchable source text, explicit facts and procedures, provenance,
bounded inference with proof checks, SQLite model paths, and narrow demonstrations
of procedure composition, language transfer, contextual intent, and dialogue
continuity. The recent six-seed phrase experiment composes 21 held-out
action/object/direction combinations, but uses synthetic Codex-authored wording
and labels. It demonstrates controlled transfer, not learning from source text.

The main gap is generalization through the whole system. Source-driven rule
discovery has not yet shown reliable precision on complete held-out documents;
recombination is not yet broadly learned; reasoning is stronger in the engine
than in natural-language coverage; and dialogue/intent evidence remains narrow.
The project has not shown that a copied SQLite model can support its full
learning and correction lifecycle without the original source files.

The code snapshot at `69158a4` passed a 17-diagnostic cross-domain regression
replay covering language, recombination, reasoning, dialogue, translation,
math/code, and creative revision. A later 18-diagnostic replay including
`v1_452` also passed after the variable-width direction-role extension. These
replays use separate fixtures and scoring, so their pass counts are regression
results, not unified capability scores. The current `v1_452` run passes 8/11
held-out positive request forms, with no generated outputs for three
unsupported-direction controls; wording and labels are Codex-authored, so this
is a bounded transfer result, not an independent language benchmark. The
`v1_450` role-compatible candidate probe surfaced a false created/praised match;
the later evidence-gate fix excludes role types contradicted by explicit
negatives and types carrying qualifiers. This improves a named safety gate but
does not establish source-derived rule precision. The latest integration probe,
`v1_451`, joins held-out rule validation, verified chat reasoning, procedure
execution, and premise-correction invalidation for one controlled synthetic
task. It still relies on an authored graph and Codex-labeled procedure
examples, so it does not close the generalization gap.

On 2026-10-20, a fresh CLI replay against a temporary copy of the academic
portable model reproduced a wrong-source answer to “What topics do these papers
cover?” after a recent-paper list. The new `v1_453` path answers from the
visible paper list with cited abstract sentences and asks for context if no
list is open. The expanded 19-diagnostic cross-domain replay passed in 14.46
seconds. This closes one extractive follow-up failure; it does not solve
cross-paper synthesis or general plain-language explanation. The fallback now
states when no verified rewrite is licensed and gives the user the teaching
path; `v1_455` checks both this abstention and a learned rewrite. A combined
23-diagnostic replay including the plain-rewrite checks passed in 17.07
seconds. `v1_454` confirms that two pending source candidates do not interrupt
an unrelated accepted answer, remain explicitly reviewable, and survive
restart; interruption behavior across every long-conversation pattern remains
unverified. These passes are separate regression checks, not a representative
user-task score.

The overall direction is sound, but CRMS is not yet on track to claim its
capability destination. Progress now depends on integrated, held-out outcomes,
not more isolated demonstrations or a larger corpus.

## Execution plan

Follow the critical path below. Keep dialogue and contextual intent evaluation
active alongside it; expand domains and finalize distribution after the core
learning lifecycle has stronger evidence.

### 1. Lock the end-to-end evaluation and dialogue safety baseline

Maintain a compact, versioned chat scorecard with full transcripts, source
layouts, frozen expected outcomes, negative controls, and fresh-process
replays. Include ordinary questions, paraphrases, multi-part requests,
unsupported/conflicting claims, topic changes, source-only answers,
pronouns, clarification/repair, history, and ordinal references. Report correct,
wrong, omitted, abstained, clarified, cited/proof-supported, and completed
outcomes separately.

Preserve the reported Eiffel Tower/Colosseum topic-switch failure and source-only
context failures as fixed regressions. Current focused scripts cover many of
these cases, but their authored transcripts do not establish broad dialogue
reliability. Add independently authored conversations with varied paragraph
layouts and more entities. Context changes should not silently bind an
ambiguous pronoun to whichever entity happens to have a matching fact. Intent
may route, clarify, or repair; it cannot establish facts or authorize
unsupported actions. The fresh-process `v1_449` regression covers a subtle
integration boundary: the dialogue layer retains the correct topic, but the
final quoted-evidence gate must receive the exact paragraph that binds a
pronoun to its named antecedent. A pronoun-only paragraph remains an abstention.

`v1_462` now measures transcript-context intent on three newly reserved
restaurant-table test conversations, disjoint from 700 IDs already present in
the prepared local Taskmaster/dialogue CSV inventory. All 27 cited spans
verified. Contextual replay covered 15/27 turns and matched both single-Codex
act/intent labels on 7/27 (25.9%); context-free classification matched 6/27
(22.2%). This adds only one
joint match despite four additional hypotheses, and the labels are not
independent ground truth. Treat the weak transfer result as evidence to keep
the dialogue gate open, not as task accuracy. The next evaluation must score
end-to-end completion on independently authored transcripts with frozen
expected outcomes; do not tune against the now-inspected Taskmaster rows.

The first inspection-driven repair is recorded in `v1_463`: explicit booking
imperatives now precede generic imperative classification, and booking-name
questions expose a typed contextual slot so “Put it under Frank” is treated as
the answer while unrelated requests still interrupt. The chat-path and nearby
task-goal/confirmation regressions pass. This closes a narrow precedence bug;
the Taskmaster transfer result remains frozen at its pre-change score.

**Gate:** fixed regressions pass in a clean process; unresolved referents are
clarified or declined; no confident wrong referent appears in the held-out
conversation set. Record transcript authorship and labeling provenance.

The movie-ticket development replay also exposed an intent precedence error:
“No. Just get three tickets for the next showing” was consumed as an answer to
the open choice rather than a new imperative. `v1_466` recognizes this
rejection-plus-request form while keeping a bare “No” ambiguous and a negative
preference detail attached to the choice. On the same 37-turn dev slice, joint
single-Codex act/intent agreement moved from 18/37 to 19/37 with transcript
context and from 6/37 to 7/37 without it. This is a development-set diagnostic,
not independent accuracy or task-completion evidence; the transfer gate stays
open.

### 2. Learn rules from sources and prove unseen recombination

Make this the main capability experiment. Use complete source documents with
document- and publisher-disjoint holdouts. Test whether CRMS can propose
operation, ordering, and connective rules from source material without bespoke
extractors for each passage. Include quoted, negated, contrastive, conditional,
metalinguistic, unrelated, and misleading text. Keep source evidence,
extracted candidate, teacher/labeler decision, accepted rule, and validation
result as distinct provenance-bearing records.

Compose independently supported components into instructions not seen during
teaching. Vary wording, values, and order; include missing-step, unsupported
operation, and near-miss controls. Run through ordinary chat and a fresh
process, and check results with an independent oracle. Measure proposal
precision, useful coverage, review burden, and labeler effort. Codex may label
proposals, but Codex labels are not independent validation. Do not describe cue
matching or teacher-assisted alignment as autonomous learning.

The new role-compatible predicate probe is deliberately a report-only
discovery aid. Its runtime fixture shows both a plausible created/made
candidate and a false created/praised candidate from shared entity types.
That result supports investigating broader candidate generation, while
confirming that type compatibility must never teach an alignment on its own.
The probe is not evidence of source-disjoint rule learning; that gate still
requires complete held-out documents and direct semantic validation.

**Gate:** at least one genuinely unseen, source-disjoint composition succeeds
through chat and reload; an independent checker accepts valid results and
rejects invalid ones; unsupported cases abstain; provenance makes supervision
visible; measured precision and review burden justify continuing.

### 3. Join recombination to verified reasoning and governed derivation

Route the same natural-language task through procedure/rule selection and the
relevant proof verifier or task-specific checker. Cover supported results,
missing premises, explicit negatives, contradictions, cycles/integrity
violations, and exhausted search. Keep unknown, false, conflicting, incomplete,
and unsupported distinct in the engine and chat.

Then exercise the feedback loop as a gated proposal: retrieve → compose → verify
independently → propose a derived case. Derived cases retain full lineage, stay
lower trust than taught/source-backed knowledge, and cannot validate the rules
that produced them. Test source correction, dependency invalidation, duplicate
control, and store-growth policy before derived cases affect ordinary
retrieval.

The first cross-component integration now has a controlled end-to-end probe:
`v1_451` learns and source-holdout-validates a typed three-premise rule, asks
runtime questions through natural-language chat, independently verifies the
positive proofs, passes only proof-backed result IDs into a separately learned
list procedure, checks the generated code against an independent oracle, and
invalidates a practiced conclusion after premise correction. This closes the
integration seam for one synthetic task. The procedure mapping is
Codex-labeled, the graph is authored, and the experiment orchestrates the
stages; source-derived rule learning and user-level task planning remain open.

`v1_456_source_frames_to_reasoned_procedure.py` advances the seam: repeated
parent/ancestor facts are extracted from exact source sentences and reviewed
separately on training and document-held-out corpora; a parent-chain rule is
then validated on the held-out facts, accepted, independently proof-checked on
new runtime premises, and routed through a fresh chat process. Only proof-backed
record IDs feed a separately learned unique-then-reverse procedure, checked by
an independent output oracle. The probe also covers an explicit-negative
conflict, an open-world unknown, and invalidation after premise correction.
All source passages are Codex-authored fixtures and frame review is explicit;
the procedure examples and instruction alignment are Codex-labeled. This
demonstrates the mechanics of source-frame → rule → verified reasoning →
procedure composition, not learning from natural corpora or broad planning.

While building this probe, the passive-role regression in `v1_245` became
visible: a learned active frame could misparse “Archive was created by Cal” as
“Archive was → create → by Cal.” Active-frame matching now rejects explicit
be-verb/by-phrase passive clauses. The exact cited question route still returns
the correctly role-reversed claim for review, while corpus-frame discovery does
not generalize from the passive-only pattern. `v1_243` and the updated
`v1_245` check these boundaries.

**Gate:** chat and engine agree; every positive has a verified proof or
task-specific check; incomplete search cannot produce a positive; correcting a
source makes dependent derivations unavailable until revalidated.

### 4. Improve contextual intent and dialogue against the baseline

Model user intent as a contextual, revisable hypothesis over the utterance and
explicit dialogue state: task/subgoal, active topic and referents, open
questions/options, prior move, and the answer or claim under discussion. Add
state only to solve a measured failure. Test the same wording in different
contexts, topic changes, interruption, correction, confirmation, and repair.
Measure intent classification, safe context resolution, inappropriate moves,
and task completion separately.

Continue dialogue-move induction as research, not a product dependency. Use
cited utterances, an explicit corpus/domain policy, held-out conversations, and
visible Codex labeling provenance. Compare learned moves with the explicit
baseline before promoting them.

**Gate:** intent improves held-out task completion without increasing wrong
referents, stale context, or inappropriate actions. Learned moves must beat the
explicit baseline on held-out outcomes.

### 5. Expand task range one validated domain at a time

Use the shared natural-language and validation path to advance bounded tasks in
math, coding, translation, and creative work. Define held-out requests, negative
cases, an independent checker or human rubric, evidence policy, and repair flow
before each implementation. First validate each slice alone; test cross-domain
composition afterwards. Score creative coherence and instruction constraints
separately from factual grounding.

**Gate:** each domain reports held-out coverage, correct/wrong/abstained,
completeness, provenance, repair success, and cost through chat. Choose the next
slice from measured user loss, not convenience.

### 6. Verify the distributable SQLite model contract

After knowledge, rules, provenance, correction, and derivation records
stabilize, verify a single distributable SQLite model containing searchable
source text, accepted knowledge, rules/procedures, and provenance. Copy it to a
clean location, make original source files unavailable, and exercise query,
evidence lookup, supported learning, correction, save/reload, and scorecard
replay against the copy.

**Gate:** the copy supports all tested paths without the original documents.
Report size, runtime, compatibility requirements, and unsupported cases.

## Immediate work queue

1. **Generalize dialogue behavior beyond the passing fixtures.** Add
   independently authored multi-turn conversations over real source text with
   topic switches, pending review, unsupported turns, corrections, “why?”,
   history, plural/ordinal references, and save/reload. Include requests to
   explain a result more simply and distinguish a grounded extract from an
   actual explanation. Measure wrong referents, irrelevant evidence, omissions,
   clarification, and completion separately. `v1_465` now freezes the reported
   stale-`why?` sequence: an unsupported Colosseum switch after an Eiffel source
   answer must not explain the Eiffel answer, while a supported switch must
   explain only the Colosseum evidence. This is a regression control, not a
   conversation benchmark.
2. **Prove source-derived rules and recombination beyond hand-labeled phrases.**
   The map-free `v1_464` full SimpleWiki scan surfaced useful relation wording
   alongside substantial parser and role noise; keep all candidates
   report-only.
   Next reduce those errors and validate on publisher-held-out material before
   building a learner. Use complete documents with document- and
   publisher-held-out splits. Freeze
   positive, quoted, negated, contrastive, conditional, metalinguistic, and
   unrelated passages before implementing extraction. Track proposal
   precision, useful coverage, false proposals, review burden, and Codex label
   contribution. Then compose the learned components through ordinary chat,
   reload, and an independent oracle. The current 8/11 `v1_452` result is a
   useful syntax-transfer baseline; keep expanding it only where held-out
   errors show a concrete loss.
3. **Extend the reasoning/recombination integration with real source evidence.**
   Reuse the `v1_451` synthetic vertical slice as a regression control, then
   replace authored premises with source-grounded cases and independently
   validated procedures. Include missing premises, explicit negatives,
   conflicts, cycles/integrity violations, incomplete search, bad generated
   output, correction, and derived-case invalidation. Keep provenance and
   teacher/labeler work separate from what CRMS learned.

Dialogue evaluation runs alongside packets 2 and 3. Do not add a domain, grow
the corpus, migrate storage, or add a new dialogue mechanism unless it unblocks
one of these gates or improves a measured scorecard result.

After these gates, choose the next math, coding, translation, or creative slice
from measured user-task loss; then validate the copied SQLite model against the
same end-to-end scorecard with original source files unavailable. Keep
contextual intent evaluation active throughout, but add state only to address a
reproduced dialogue failure. Keep dialogue-move induction experimental until
it improves held-out outcomes over the explicit baseline.

## Working rule

For each packet, keep the smallest failure as a regression, run nearby negative
cases through chat and a fresh process, and use the relevant independent
checker. Record the code snapshot, data split, corpus, authorship/labeling,
outcomes, runtime, and remaining failure modes. Choose the next change by
reducing confident errors, improving held-out useful coverage, or removing a
named integration blocker. Reassess after each gate whether evidence moved
CRMS closer to its destination; passing more scripts or ingesting more text
alone does not count.

The detailed [focused roadmap](focused_roadmap_to_goal.md) retains the supporting
experiment history and design rationale. See also [the 70B-class capability
comparison](capability_comparison_70b.md), [learning dynamics](design_learning_dynamics.md),
[evidence independence and transfer](design_evidence_independence_and_transfer.md),
[contextual intent](design_user_intent_model.md), and [domain expansion](design_domain_expansion.md).
