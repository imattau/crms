# Focused roadmap from the current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** execution plan; the capability goal remains unmet.

## Destination

CRMS aims to be a lightweight, distributable language system that can handle
broad ordinary requests, continue across turns, combine learned knowledge and
procedures, reason over evidence, and improve from use. Its answers and
artifacts must remain inspectable and correctable, with clear limits on what is
known, inferred, uncertain, or unsupported. Coding, math, translation,
creative work, and other domains should use the same natural-language
interface. Strong 70B-class models are a reference for task breadth and
interaction quality, not a parity claim or a required live comparator.

## Where the project is now

CRMS has substantial foundations: searchable source text, provenance-bearing
knowledge and procedures, review-gated learning, bounded proof-checked
reasoning, contextual dialogue state, and a portable SQLite model format.
Controlled end-to-end slices show that source-backed rules can be accepted,
held-out checked, recombined into procedures, used in chat, and carried into a
copied model. Reasoning also has controlled paths through chat, independent
proof verification, correction, and invalidation of derived results.

The missing evidence is generalization across the complete user path. Current
successes rely on small or synthetic fixtures, hand-coded extraction/mapping,
Codex-provided labels, and deliberately orchestrated experiments. The latest
arXiv audit found 8 full papers among 1,697 records and no useful procedure
candidates in those papers; that index is unsuitable for the tested grammar,
not evidence against academic sources in general. A read-only scan of 415
NumPy and 100 pandas callable API docstrings now shows the grammar can find
candidate material in relevant reference text, but its 327 candidate spans
are not yet useful-rule evidence: repeated boilerplate dominates, and a
source replay exposed lost subject and condition information. The source
learning route has corpus-fit evidence but still needs labeled proposal and
non-proposal review, better role/context preservation, and a frozen,
source-disjoint transfer test.
Dialogue has targeted fixes for topic switches, source-only context, and
pronoun grounding, but its independent transfer results remain weak and do
not establish reliable conversation. Recombination and reasoning work, but
not yet as a broadly learned capability. Self-learning by write-back is
designed and partly prototyped, but must remain governed until independent
verification and correction propagation are demonstrated together.

**Assessment:** the architecture is pointed toward the goal; the capability
claim is not yet earned. The next work should improve held-out chat outcomes,
not increase experiment, corpus, or feature counts by themselves.

## Execution principles

1. Measure complete tasks through ordinary chat and a fresh process. Keep
   answer quality, evidence/proof validity, abstention, clarification,
   task completion, runtime, and storage as separate measures.
2. Freeze test material before tuning. Split by source document, publisher, or
   complete conversation as appropriate. Keep negative cases and known
   failures as permanent controls.
3. Treat intent as contextual and revisable. It may route, clarify, and repair;
   it cannot add facts or authorize unsupported actions.
4. Keep Codex labels and teacher examples explicit. They are supervision, not
   independent validation. Preserve citations, labels, review decisions, and
   correction lineage.
5. Recombination, self-learning rules, reasoning, and dialogue remain the
   central work. Add domains or storage features only when they clear a gate
   below or address a measured user-facing failure.

## Focused path

Dialogue evaluation runs alongside the capability path and is a release gate
for every chat-facing change. The remaining phases are sequential: a failed
gate calls for redesign of that mechanism before widening scope.

### 1. Lock the shared chat evaluation and dialogue safety baseline

Preserve the current targeted regressions for topic switching, source-only
answers, paragraph/entity grounding, unanswered turns, stale `why?`, history,
ordinal references, corrections, and save/reload. Add a compact set of
independently authored multi-turn transcripts with varied paragraph layouts,
competing entities, and follow-up wording. Include the reported Eiffel
Tower/Colosseum sequence and “and Italy?” after source-only evidence. Score
wrong referents, irrelevant evidence, correct resolution, clarification,
abstention, omission, and task completion separately. Keep intent label
agreement separate from task success.

**Exit:** fixed regressions pass in clean processes; the held-out set has no
confident wrong referent; unresolved context leads to a focused clarification
or abstention; every factual answer is supported by the evidence shown. If the
gate fails, fix context lifetime and source/entity grounding before adding
intent classes or learned dialogue moves.

### 2. Establish whether source-derived rules transfer

Use complete technical references or another corpus that contains enough
instances of the target construction. Do not use the current arXiv index as a
positive set for the tested “subject will predicate” grammar. Freeze the
candidate method before labeling; split discovery and holdout by document and
publisher. Label both proposals and sampled non-proposals. Include role
reversals, negation, quotation, contrast, conditions, scope, and misleading
near misses. Keep each candidate cited, review-only, and unable to alter the
rule store until accepted through existing gates. Record labeler identity,
teacher effort, precision, useful yield, missed cases, and review burden.

The `v1_474` audit establishes candidate yield in two installed API-reference
collections: NumPy produced 303 candidates from 13,391 sentences, and pandas
produced 24 from 5,384. This is corpus fit, not precision or transfer. A
source-backed `/suggest-procedure-phrases` replay hid the candidate subject;
review of its cited `numpy.add` sentence showed the candidate had dropped
`out` and the conditional location. Repeated NumPy boilerplate accounts for
168 of its candidates, and the spot-check found other incomplete spans around
qualifiers and inline code. Preserve these as failure cases. Before changing
the frozen grammar, review a fixed sample of proposals and non-proposals and
decide whether its current representation can retain a usable, licensed
operation claim. If not, redesign role, condition, and markup extraction as a
general boundary model, then reserve new documents for confirmation.

That review is now done in `v1_475`: in a deterministic but non-probability
sample from the same two package corpora, all 20 candidate field sets needed
their source sentences to restore a role, condition, qualifier, contrast, or
markup boundary; all 20 sampled no-candidate sentences described plausible
API behavior outside the current subject grammar. This is unblinded Codex
error analysis, not a precision/recall estimate, and the source-cited review
path still prevents these candidates from becoming accepted knowledge. Keep
these cases as development controls; the current clause-aware redesign is
described below, and confirmation must use untouched API units and a new
publisher.

The clause-aware redesign is now implemented as a review-only proposal path
and exercised by `v1_476`. Its 19 cited fixtures cover full subjects,
conditions, contrast, list items, parenthesized values, literals, polarity,
quotation, denial, uncertainty, one-word predicates, and a fresh chat replay;
candidates remain review-only. The full-package replay `v1_477` finds 657
sentences across 250 NumPy API units and 217 across 60 pandas units, compared
with 303/177 and 24/16 in `v1_474`; NumPy has 279 normalized candidate
patterns. A re-run of six topic-switch, source-only,
paragraph-grounding, multi-turn, cross-paragraph, and unsupported-switch
dialogue controls passed 6/6; this is regression coverage, not dialogue
transfer evidence. The source counts are yield only: the replay
still exposes malformed boundaries in complex parameter and conditional
prose, and the frozen sample was used during redesign. Do not call the yield
increase improved precision or transfer. The next gate is a predeclared
review of a frozen sample from `v1_477`, followed by a publisher- and
API-unit-held-out confirmation that was not used to revise the parser. Codex
labels are supervision, not independent validation.

Use the existing excerpt and real-source acceptance experiments as regression
controls, not as a corpus-level result. If a suitable corpus does not contain
enough examples, change the learning signal or narrow the claim; do not add
phrase-specific rules to make the study pass.

**Exit:** the frozen method produces useful, source-supported proposals on
held-out documents and a held-out publisher, with negative controls measured
and review effort reported. If it fails, redesign candidate discovery before
promoting autonomous rule learning.

### 3. Prove recombination through reasoning in ordinary chat

This is the main capability milestone. Learn or accept components separately,
then ask a genuinely unseen multi-step request in ordinary language. Route it
through retrieval, rule/procedure selection, reasoning, and the appropriate
proof or task-specific checker. Run it after fresh-process reload. Keep source
evidence, learned components, connective supervision, derived rule, proof, and
output validator distinct in provenance. Exercise changed wording, values,
and operation order, plus unsupported operations, missing steps, explicit
negatives, conflicts, cycles/integrity failures, and search limits.

**Exit:** at least one source-disjoint composition succeeds through chat and
reload; an independent checker accepts valid results and rejects invalid
ones; incomplete, contradictory, or unsupported requests do not produce a
confident positive. Report which steps were learned, hand-coded, or labeled.
If only the experiment orchestrator can compose the steps, the gate remains
open.

### 4. Close the self-learning loop under correction controls

Only after phase 3, enable derived outputs as proposals: retrieve → compose →
verify independently → propose with lineage. Keep derived knowledge separate
from taught/source-backed knowledge and lower-trust until revalidated. Test
source and rule corrections, dependent-case invalidation, conflicts, duplicate
suppression, retrieval weighting, abstention on invalid lineage, and storage
growth. A derived result must never validate its own generating rule.

**Exit:** correcting a source or rule identifies and disables all affected
derivations until they pass verification again; no invalid or incomplete proof
can be reused; growth and trust policies have measured limits. Until then,
write-back remains review-gated rather than automatic.

### 5. Validate dialogue intent and moves against task outcomes

Model user intent as a contextual hypothesis over the utterance and explicit,
bounded discourse state: active task/subgoal, current topic and referents,
open question or choice, previous move, and unresolved ambiguity. Compare it
with the explicit baseline on held-out conversations, including the same
utterance under different contexts. Continue the dialogue-move research as a
separate experiment: cited corpus examples and Codex labels can suggest frames,
but the context and product-policy gates must remain explicit.

**Exit:** contextual intent improves held-out task completion without raising
wrong referents, stale context, or inappropriate moves. Learned dialogue
moves enter runtime only if they improve the explicit baseline on held-out
outcomes; label agreement alone is insufficient.

### 6. Expand task breadth one validated slice at a time

Use the same natural-language interface for one bounded task at a time in
coding, math, translation, and creative work. Choose the first task from
measured user-facing failures. Define held-out requests, negative cases,
independent validation, evidence policy, and repair behavior before
implementation. Validate each domain alone before cross-domain compositions;
evaluate creative coherence and constraint-following separately from factual
grounding.

**Exit:** each slice reports held-out coverage, correct and wrong results,
abstentions, completeness, provenance, repair success, and cost through chat.
Do not infer domain breadth from a single worked example or component pass.

### 7. Verify the distributable model as the complete runtime

When record and correction lifecycles are stable, package searchable source
text, accepted knowledge, rules/procedures, and provenance in the SQLite model.
Copy it to a clean location with original source files unavailable. Query it,
inspect citations, learn and correct through supported paths, save/reload, and
rerun the shared scorecard using the copy alone. Record size, compatibility,
migration behavior, and unsupported cases.

**Exit:** the copied model supports the tested chat, retrieval, learning,
reasoning, correction, and reload paths without original files. Keep source
acquisition and licensing metadata with imported documents, including
academic-paper sources.

## Immediate sequence

1. Freeze the shared scorecard and independently authored dialogue holdout.
   Replay all fixed topic-switch, source-only-context, stale-`why?`, history,
   ordinal, repair, and save/reload transcripts. Fix only reproduced safety
   failures, then report task completion, wrong referents, clarification,
   omissions, and abstention separately. Dialogue is a parallel research and
   release gate for every chat-facing change.
2. Freeze the `v1_477` clause-aware parser and review a predeclared sample of
   candidate and non-candidate sentences. Use Codex labels as explicitly
   identified supervision; preserve the exact source sentence and boundary
   errors. Do not tune on confirmation data. Confirm on untouched API units
   and a new publisher, measuring useful proposal precision, missed useful
   claims, review effort, and source coverage. If this gate fails, revise the
   boundary representation and reserve a new confirmation set. The `v1_473`
   arXiv result remains a negative control for this specific grammar.
3. If source learning transfers, use reviewed components to build one unseen
   natural-language recombination task through chat and fresh-process reload.
   Independently check the result and its proof; include missing-premise,
   conflict, negative, unsupported, and incomplete-search cases. Keep the
   connective supervision and any hand-coded mappings visible.
4. After that composition passes, test derived-case proposals, correction
   propagation, invalidation, duplicate control, trust weighting, and growth
   limits. Keep write-back review-gated until those controls pass.
5. Continue dialogue-intent and move research against held-out task outcomes.
   Only then select a bounded math, coding, translation, or creative task by
   measured loss; finish with the copied SQLite-model scorecard using no source
   files. Do not expand corpus or domain breadth just to increase activity.

Do not expand the corpus, add a dialogue mechanism, widen domains, or migrate
the runtime store merely to show activity. After each gate, ask whether
held-out useful task completion improved without added confident errors. If
not, retain the failure, state what it falsifies, and redesign the smallest
part of the path that caused it.

## Detailed references

- [Goal execution plan](goal_execution_plan.md)
- [Current development history](current_development_plan.md)
- [Benchmark baselines](benchmark_baselines.md)
- [Learning dynamics](design_learning_dynamics.md)
- [Evidence independence and transfer](design_evidence_independence_and_transfer.md)
- [Natural-language handling](design_natural_language_handling.md)
- [Contextual user intent](design_user_intent_model.md)
- [Dialogue moves](design_dialogue_moves.md)
- [SQLite memory](sqlite_memory_design.md)
- [70B-class capability comparison](capability_comparison_70b.md)
