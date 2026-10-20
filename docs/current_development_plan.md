# CRMS development plan

**Reviewed:** 2026-10-20
**Status:** architecture is aligned; the overall capability goal remains unmet.

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
math/code, and creative revision. The replay used separate fixtures and
scoring, so 17/17 is a regression result, not a unified capability score. The
`v1_450` role-compatible candidate probe surfaced a false created/praised match;
the later evidence-gate fix excludes role types contradicted by explicit
negatives and types carrying qualifiers. This improves a named safety gate but
does not establish source-derived rule precision. The latest integration probe,
committed as `63fbd4a`, joins held-out rule validation, verified chat reasoning,
procedure execution, and premise-correction invalidation for one controlled
synthetic task. It still relies on an authored graph and Codex-labeled procedure
examples, so it does not close the generalization gap.

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

**Gate:** fixed regressions pass in a clean process; unresolved referents are
clarified or declined; no confident wrong referent appears in the held-out
conversation set. Record transcript authorship and labeling provenance.

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

1. **Dialogue safety transfer:** preserve the passing topic-anchor and
   multi-turn regressions; add independent transcripts that vary layout,
   entity count, topic switches, source-only answers, interruptions, and
   corrections. Fix confident wrong referents before broadening intent behavior.
2. **Source-derived rule-learning probe:** start with a small licensed corpus
   of complete documents and held-out publishers. Freeze positive and negative
   passages before writing extractors. Establish proposal precision and review
   effort before expanding the corpus or building a larger review workflow.
3. **Reasoned recombination task:** select one procedure composition whose
   output is independently checkable and whose conclusion also uses a verified
   rule. Add missing-premise, negative/conflict, invalid-output, cycle, and
   search-limit cases; exercise derived-case lineage and correction.

Dialogue evaluation runs alongside packets 2 and 3. Do not add a domain, grow
the corpus, migrate storage, or add a new dialogue mechanism unless it unblocks
one of these gates or improves a measured scorecard result.

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
