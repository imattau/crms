# CRMS focused development plan

**Reviewed:** 2026-10-20  
**Purpose:** The short execution plan from the current codebase to the project
goal. The [focused roadmap](focused_roadmap_to_goal.md) and linked design notes
hold the detailed rationale and prior results.

## Destination

CRMS should handle a broad range of ordinary language requests, carry useful
context across turns, recombine learned knowledge and procedures, and improve
from evidence and use. Answers and generated artifacts should remain inspectable,
correctable, and honest about uncertainty. The 70B-class comparison is a
reference for task range and interaction quality, not a claim of parity or an
architecture requirement.

## Current assessment

CRMS has working foundations: searchable source text, cited evidence, explicit
facts and procedures, bounded proof search with independent verification,
SQLite-backed model paths, and narrow runtime demonstrations of transfer,
composition, contextual intent, and topic tracking. These are real capabilities
but remain uneven and mostly demonstrated on controlled examples.

The main gap is integration and generalization. Source-disjoint rule learning,
unseen procedure composition, governed write-back, broad conversational
reliability, and the complete portable-model contract are not yet established.
Recent dialogue tests demonstrate that a named topic can anchor an `it`
follow-up in a fixture; they do not yet settle the reported wrong-entity answer
across varied documents, turn sequences, and persistence. Keep the overall goal
in progress.

## Execution order

### 1. Lock a trustworthy end-to-end scorecard

Keep a small versioned set of complete chat transcripts and task cases covering
direct questions, paraphrases, unsupported or conflicting claims, multi-part
requests, topic switches and pronouns, clarification and repair, procedure
composition, reasoning, and the existing domain slices. Hold out complete
documents and conversations. Record expected answer, acceptable abstention,
evidence requirements, and an independent checker for each case. Report correct,
wrong, omitted, abstained, coverage, latency, and provenance separately.

**Gate:** a clean process can replay the frozen set; every known failure remains
visible; component tests cannot substitute for chat outcomes.

### 2. Close dialogue grounding and context failures

First reproduce the Colosseum/Eiffel Tower failure in the current runtime. Keep
the current-topic pronoun binding as a regression, then vary paragraph layout,
entity names, intervening turns, source-only answers, unanswered turns,
`why?`, clarification, and save/reload. Preserve valid context after a source-only
answer, but do not let stale or weak context silently select an entity. Ambiguity
must lead to a clarification or abstention. Track user intent as a provisional
hypothesis from the utterance and explicit dialogue state; it may route or ask,
but cannot create facts or authorize unsupported actions.

**Gate:** no confident wrong-entity answers or stale explanations on the held-out
dialogue set; valid source-only context survives; ambiguous references are
resolved explicitly or left unanswered. Keep dialogue-move induction
experimental until it improves held-out task completion over the current
explicit baseline.

### 3. Prove source-disjoint procedure learning and recombination

This is the main capability test. Extend the `v1_433` procedure-composition
slice without using its held-out cases to design the learner. Keep source text,
extracted examples, teacher/labeler contributions, induced rules, and validation
results distinct. Hold out complete documents, wording, component examples, and
at least one composition. Include reordered steps, near misses, missing or
unsupported steps, wrong outputs, and conflicts. Run requests through ordinary
chat and a fresh process; verify generated results with an independent checker;
preserve complete source and rule lineage through reload.

If prose establishes an operation but not its connective or ordering, mark that
part as teacher-assisted. Do not present teacher-guided composition as
source-only self-learning.

**Gate:** a genuinely unseen, source-disjoint composition succeeds through chat
and reload; the independent checker accepts valid outputs and rejects invalid
ones; unsupported compositions abstain; provenance identifies every source and
supervision contribution.

### 4. Join recombination to verified reasoning and controlled derivation

Pass the successful composition from step 3 through the natural-language
router, rule selection, independent validation, and explanation. Exercise
complete, missing, conflicting, cyclic, and budget-limited cases. Then test
derived-case proposals as a separate, review-only path with provenance,
dependency tracking, correction, and invalidation. Derived records must not
override conflicting taught or source-backed knowledge.

**Gate:** chat and engine agree; every positive has a verified proof or
task-specific check; incomplete search cannot yield a positive; corrections
make affected derivations unusable until reviewed or revalidated.

### 5. Improve contextual dialogue and intent alongside steps 3–4

Keep a compact, inspectable discourse state for active topic, referents, open
questions or choices, task goal and phase, and the answer being discussed. Add
state only to fix a measured error. Evaluate the same short utterance in
different contexts, corrections, multi-step tasks, topic changes, and
clarification cycles. The movie-ticket transcript slice is a bounded intent
diagnostic; its agreement with Codex labels is not independent accuracy.

**Gate:** held-out task completion improves without more wrong referents, stale
context, or inappropriate actions. Learned conversational moves stay inert
unless they beat the explicit baseline on held-out outcomes.

### 6. Grow domain breadth one validated slice at a time

Use the shared language and validation path to strengthen one bounded task each
in math, coding, translation, and creative work. Define scope, held-out wording,
negative cases, checker or human rubric, evidence policy, and repair flow first.
Only test cross-domain composition after the individual slices work.

**Gate:** report held-out coverage, correctness, omissions, abstentions,
provenance, repair success, and cost through chat. For creative work, measure
coherence and constraint satisfaction separately from factual grounding.

### 7. Finish the distributable SQLite model and re-evaluate

Once the records and write-back lifecycle above are stable, complete the model
build/copy/learn/reload contract. The copied SQLite model must contain searchable
source text, learned knowledge, rules, procedures, and provenance, and operate
without original ingestion files. Run the same scorecard on that copy.

**Gate:** answers, evidence lookup, learning, corrections, and reload behave as
expected on a clean copy without source files. Publish resource use and
unsupported cases alongside capability results.

## Working cadence and decision rule

Work in small packets. Before changing a behavior, keep or add the smallest
reproducible failing chat transcript; after changing it, run that transcript,
nearby regressions, and the relevant fresh-process or reload path. Record what
passed and what did not in the benchmark report. Commit only intended files.

Choose the next packet by the largest measured user-visible failure or the
nearest gate for held-out recombination and reasoning. Dialogue and contextual
intent remain active priorities. Do not expand the corpus, add domains, or
migrate more storage unless the work improves a measured outcome or enables a
specific gate. Reassess the overall goal after each packet; passing more scripts
or adding more data alone does not establish progress.
