# CRMS goal execution plan

**Reviewed:** 2026-10-20
**Status:** execution plan; the capability goal remains unmet.

## Destination

CRMS aims to become a lightweight, distributable language system that can
handle a broad range of ordinary requests, continue across turns, recombine
knowledge and procedures, and improve from evidence and use. Its answers and
artifacts should remain inspectable, correctable, and clear about what is
known, inferred, uncertain, or unsupported. Coding, math, translation,
creative work, and other domains should use the same natural-language
interface. Strong 70B-class models are a reference for task breadth and user
interaction, not a parity claim or a required live comparator.

## Project review

CRMS has a strong foundation for explicit memory and accountability: searchable
source text, provenance-bearing facts and procedures, bounded inference with
proof checks, review paths, correction hooks, and a portable SQLite model
format. Controlled experiments show useful language transfer, multi-step
procedure composition, proof-backed reasoning, exact math/code operations,
translation, and dialogue state.

The project is **architecturally aligned, but not yet on track to claim its
capability goal**. The main gap is generalization across the full path from
ordinary user language to a correct, useful, checkable result. Strong results
still rely heavily on controlled fixtures, hand-authored rules, or Codex labels.
The latest dialogue test transfer was materially weaker than development
(12/46 vs. 64/131 joint act/task-intent label agreement); this is a label
diagnostic, not task accuracy, but it shows that current intent handling does
not transfer reliably. Source-derived rule discovery has promising narrow
signals, but no convincing precision/coverage result across source-disjoint
documents and publishers. Verified reasoning is ahead of natural-language
routing and broad rule learning. The single-file SQLite distribution goal is
not yet validated across the complete learning and correction lifecycle.

Recent regressions and component passes should be kept as controls, not
combined into an overall success percentage. In particular, passing scripted
dialogue cases does not establish conversational competence; a retrieval hit
does not establish that the answer addresses the question; and a verified
proof over an authored graph does not establish autonomous rule learning.

## Operating principles

1. **Evaluate user tasks end to end.** Keep versioned, frozen, source-disjoint
   sets with positive and negative cases. Report coverage, correct answers,
   wrong answers, omissions, abstentions, clarification, task completion,
   evidence/proof quality, repair success, runtime, and storage separately.
2. **Keep evidence and control separate.** Intent may route, clarify, or repair;
   it cannot add facts or authorize an unsupported action. Derived knowledge
   cannot validate the rules that produced it.
3. **Make learning attributable.** Record source, extraction, labels, review,
   accepted rule, holdout result, and independent validation as separate
   events. Codex may label, but its labels are supervision, not independent
   validation.
4. **Promote only what transfers.** A component advances only after it works
   through ordinary chat, fresh-process reload, and an independent checker on
   examples disjoint from teaching. Keep failed cases frozen as regressions.
5. **Let measured failures set scope.** Add state, rules, or domain breadth only
   to address a reproduced user-task failure or to clear a named gate.

## Critical path

Dialogue and contextual intent are measured throughout. The capability work
below is sequential: each stage must clear its gate before the next stage
expands. If a gate fails, repair or redesign that stage instead of adding
surface area.

### 1. Establish the shared end-to-end baseline and protect dialogue safety

Build one compact scorecard spanning factual questions, paraphrases,
multi-part requests, unsupported/conflicting claims, topic changes, source-only
answers, pronouns, clarification and repair, history, and ordinal references.
Use independently authored transcripts and varied source layouts alongside
fixed regressions. Include the reported Eiffel Tower/Colosseum referent case,
source-only context carryover, unanswered turns, and `why?` after topic
changes. Test clean-process and save/reload behavior.

Model intent as a contextual, revisable hypothesis over the utterance and
explicit state: task and subgoal, active topic/referents, open question or
choice, previous move, and the answer under discussion. Keep state bounded and
inspectable. Resolve only when context and evidence support it; otherwise ask
a targeted clarification. Dialogue-move induction remains research until it
beats the explicit baseline on held-out task outcomes.

**Gate:** no confident wrong referent on the frozen dialogue set; correct
follow-ups or focused clarifications; evidence supports each factual answer;
report completion, omissions, abstentions, clarification, and label
agreement separately. Do not interpret single-annotator intent agreement as
accuracy.

### 2. Prove useful source-driven rule discovery

Use complete documents and corpora with actual overlap in relation and
wording. Freeze a candidate generator before labeling; evaluate proposals and
non-proposals on document- and publisher-disjoint splits. Include active and
passive forms, role reversals, quoted, negated, contrastive, conditional,
metalinguistic, unrelated, and misleading passages. Candidates must carry
citations, remain inert until accepted, and expose the source and labeler
contributions.

Measure proposal precision, useful coverage, false proposals, review burden,
and labeling effort. Structured fields may suggest hypotheses but cannot be
treated as semantic truth. If the current alignment lead has negligible yield
or requires hand-coded field-to-relation truth, change the discovery method
before expanding extraction machinery.

**Gate:** a frozen method finds useful candidates on held-out documents and a
second publisher with measured precision and review effort; negative controls
do not become positive rules. Codex review may establish a labeled diagnostic,
not independent validation.

### 3. Demonstrate recombination through chat

Compose independently supported rules and procedures into genuinely unseen
multi-step requests. Vary wording, values, and operation order. Keep the
component examples, connective evidence, induced rule, and output validator
distinct. Include unsupported operations, missing steps, contradictions,
near misses, and incomplete instructions. Run the request through ordinary
chat and a fresh process; check output with an independent oracle.

**Gate:** at least one source-disjoint unseen composition succeeds through
chat and reload; the independent checker accepts valid outputs and rejects
invalid ones; unsupported or incomplete requests abstain. Report teacher and
labeler effort. Supervised phrase alignment must not be described as
autonomous learning from documents.

### 4. Join recombination to verified reasoning and governed derivation

Route the same natural-language task through rule selection, reasoning, and
the relevant proof or task-specific checker. Cover positive results, missing
premises, explicit negatives, conflicts, cycles/integrity failures, and search
limits. Keep `unknown`, false, conflict, missing premise, and incomplete
search distinct in both engine and reply.

Treat practice/write-back as a gated proposal: retrieve → compose → verify
independently → propose with lineage. Derived cases remain lower-trust and
review-only until correction, dependency invalidation, duplicate control, and
store-growth limits work. A correction to a source or rule must identify
dependents and prevent their use until revalidated.

**Gate:** chat and engine agree; every positive is independently verified;
incomplete search cannot yield a positive; corrections disable dependent
derivations; no derived result certifies its own generating rule.

### 5. Improve contextual intent and task completion

Use the shared scorecard to compare the contextual model against the explicit
baseline on held-out conversations, including identical utterances under
different contexts, topic switches, confirmation, interruption, correction,
and repair. Assess task completion and inappropriate actions in addition to
label agreement. Add or induce dialogue moves only when the state and baseline
can be evaluated; keep corpus policy, citations, and Codex labeling visible.

**Gate:** contextual intent improves held-out task completion without
increasing wrong referents, stale context, or inappropriate moves. Learned
moves remain experimental unless they improve the explicit baseline.

### 6. Expand domain breadth through the validated interface

Add math, coding, translation, and creative work one bounded task at a time.
Before implementation, define held-out user requests, negative cases,
independent validation or a human quality rubric, evidence policy, and repair
flow. Validate each domain alone before cross-domain composition. Score
creative coherence and constraint following separately from factual grounding.

**Gate:** each domain reports held-out coverage, correctness, wrong outputs,
abstentions, completeness, provenance, repair success, and cost through chat.
Expansion must not conceal abstentions or increase confident errors.

### 7. Verify the distributable SQLite model end to end

Once record and correction lifecycles are stable, package searchable source
text, accepted knowledge, rules/procedures, and provenance in the distributable
SQLite model. Copy it to a clean location with original source files
unavailable; query, inspect evidence, learn through supported paths, correct,
save/reload, and rerun the fixed scorecard using the copy alone.

**Gate:** copied model supports every tested path without the source files.
Report size, runtime, compatibility, migration behavior, and unsupported
cases. Keep source acquisition and packaging policy explicit, including
academic-paper sources.

## Immediate work queue

1. Freeze the latest dialogue and factual controls, then create an independent
   multi-turn transcript/layout set. Evaluate it once before changing
   dialogue behavior; prioritize wrong referents, topic-switch context loss,
   and completion over more intent features.
2. Run the source-rule discovery study with a frozen method, real
   relation/wording overlap, disjoint documents/publishers, and blind
   candidate plus non-candidate labeling. Decide whether the current alignment
   lead merits promotion or redesign.
3. Use the discovery result to pick one unseen recombination task, and join it
   to proof/output verification, correction, and derived-case invalidation.
   Keep existing synthetic integration cases as regression controls.

Do not enlarge the corpus, add a new dialogue mechanism, expand domain
coverage, or migrate the model store unless it clears one of these gates.
Dialogue measurement runs alongside the learning/reasoning path, not after it.

## Reassessment rule

After each gate, review whether the evidence moved CRMS toward broad,
natural-language task completion while preserving inspectability and
correctability. If only fixture count, corpus size, or component pass count
increased, the project has not advanced its goal. Update this plan from the
observed failure, keep the result and code snapshot reproducible, and choose
the smallest next experiment that can distinguish progress from overfitting.

For detailed implementation history and experiment records, see
[`current_development_plan.md`](current_development_plan.md),
[`focused_roadmap_to_goal.md`](focused_roadmap_to_goal.md), and
[`benchmark_baselines.md`](benchmark_baselines.md). The comparative target is
documented in [`capability_comparison_70b.md`](capability_comparison_70b.md).
