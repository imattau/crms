# Focused roadmap from current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** direction is aligned; capability breadth is not yet on track for the
overall goal. CRMS has inspectable foundations and narrow end-to-end wins, but
does not yet behave like a broadly capable assistant.

## Goal

Build a lightweight, distributable language system that can handle a broad
range of ordinary requests, continue across turns, recombine knowledge and
learned procedures, and improve from evidence and use. It should make its
answers and artifacts inspectable, correctable, and clear about uncertainty.
The 70B-class comparison is a reference for interaction and task range, not an
architecture target or a claim of parity; no live 70B run is required.

## Where the project stands

- **Strong base:** searchable source text; explicit facts, procedures, and
  provenance; bounded inference with independent proof checks; portable SQLite
  packaging in selected paths; held-out demonstrations of natural-language
  transfer, procedure composition, and cross-domain composition.
- **Recombination is promising but narrow:** one teacher-guided procedure can
  transfer and compose through chat; one three-step composition has fixture
  document holdout. These do not yet establish broad, naturally sourced rule
  learning. The current cited-doctest path validates a small code subset, but
  does not establish that source text alone teaches a procedure.
- **Reasoning is a real capability with integration gaps:** graph proofs,
  recursion, bounded search, and proof verification have strong experiments.
  Natural-language routing, integrity/conflict coverage, and governed
  derivation/write-back remain incomplete.
- **Dialogue and intent have an explicit baseline:** topic tracking,
  clarification, follow-ups, and a small contextual intent hypothesis are
  tested. This is not general intent understanding; dialogue-move induction
  remains research. The recent multi-turn tests cover a small authored corpus,
  not open-ended conversation.
- **Language and domains remain uneven:** large-corpus canonical retrieval is
  much stronger than paraphrase coverage; answer-bearing sentence selection
  still needs measurement. Math, coding, translation, and creative work each
  cover bounded tasks, not broad competence.
- **Distribution is unfinished:** the target is one SQLite model containing
  searchable source text and learned knowledge without requiring original
  ingestion files at inference. Migration and the full build/copy/learn/export/
  reload contract are not complete.

The evidence is in [benchmark baselines](benchmark_baselines.md), which reports
component results rather than one overall assistant score. Keep the project
goal marked in progress.

## Priority order

1. **Protect end-to-end correctness and evaluation.** Keep a fixed regression
   suite across real chat flows. Track wrong answers, abstentions, omissions,
   coverage, evidence quality, and cost separately. A fluent or retrieved
   sentence is not enough to count as an answer.
2. **Make recombination and self-learning rules the central capability test.**
   Move from fixture demonstrations to source-disjoint examples, varied
   wording, held-out components and unseen combinations, with an independent
   validator and recoverable lineage.
3. **Connect reasoning to those compositions.** Route requests through chat to
   verified proof or task checks; handle missing premises, conflicts, cycles,
   integrity constraints, and incomplete search honestly.
4. **Advance dialogue and contextual user intent in parallel.** Treat intent
   as a revisable hypothesis from utterance plus explicit discourse context.
   Measure task progress and harmful misinterpretations; keep learned dialogue
   moves non-authoritative until they beat the explicit baseline.
5. **Broaden domains through shared natural language.** Grow math, coding,
   translation, and creative tasks one bounded, validated slice at a time.
6. **Complete the distributable model and release evaluation.** Preserve
   searchable source text, knowledge, rules, and provenance in a copied SQLite
   model; evaluate that clean copy across the fixed task suite.

## Execution plan

### 0. Keep one authoritative evaluation contract

Maintain locked chat-level probes for natural-language paraphrases, wrong
source selection, multi-part omissions, unsupported requests, recombination,
proof integrity, topic switches, clarification/repair, contextual intent, and
each task domain. Preserve the full conversation and tree/commit identity for
reported failures. Hold out whole source documents or conversations. Use
human-written ideal answers and negatives; Codex may provide primary dialogue
labels, but report agreement with that labeler rather than independent
accuracy.

**Gate:** every roadmap claim points to a reproducible experiment and recent
result; known failures remain visible; acceptance is judged through chat, with
component tests used to locate causes.

### 1. Finish the active evidence and dialogue reliability slices

The doctest citation-span change now returns the full prompt-plus-output block
from both in-memory and SQLite retrieval. `v1_432` checks exact citation
resolution, including CRLF text and whitespace-only blank lines. Its
Python/NumPy citation checks and the adjacent `v1_430`/`v1_431` rule-transfer
experiments pass. This verifies retrieval and citation boundaries only; it
does not establish source-only induction or broad coding skill.

Keep the multi-turn topic-switch, paragraph-grounding, source-only follow-up,
clarification, history, and save/reload probes locked. Add a regression only
for a reproduced gap. In particular, do not let pronoun-led sentences bind to
an old topic, let a failed turn explain stale content, or discard valid
source-only context. Keep cited evidence distinct from accepted facts.

**Gate:** clean-process chat tests show no wrong-entity answer or stale
explanation; citations support the answer shown; unresolved follow-ups clarify
or abstain. The corpus and transcript scope is stated honestly.

### 2. Prove transferable recombination and learned rules

Build on `v1_424` and `v1_431` without treating fixture results as broad
transfer. Teach a small set of components and connectives from naturally
occurring, cited examples. Hold out complete sources and combinations. Vary
roles, ordering, values, and request wording; include contrast cases, near
misses, missing steps, and unsupported compositions. Record source IDs,
example lineage, validation split, and the rule's tested scope. Test the full
path through chat and generated artifacts.

Keep source demonstration, teacher attribution, rule induction, and output
validation separate. A citation proving an input/output pair does not by
itself prove that the source licenses the natural-language instruction. Use
an independent validator; neither generated outputs nor derived cases can
validate their own rule.

**Gate:** source-disjoint held-out examples and unseen compositions succeed
through chat with independently checked outputs; unsupported combinations
abstain; provenance survives reload. Report coverage and errors, not just
passing examples.

Design detail: [learning dynamics](design_learning_dynamics.md) and
[evidence independence and transfer](design_evidence_independence_and_transfer.md).

### 3. Connect reasoning and add governed derivation

Choose one composition family and trace it from the user's natural-language
request through rule selection, proof/task validation, and concise explanation.
Test positive proof, missing premise, contradictory or negative evidence,
cycle/integrity violation, and search-budget exhaustion. Keep `unknown`,
`false under an explicit scope`, `conflict`, `missing premise`, and `incomplete`
distinct.

Then add derivation as an opt-in proposal flow: retrieve → compose → verify
independently → propose with full lineage. Keep derived records separate and
lower trust than taught/source evidence. Test corrections, stale dependency
invalidation, duplicates, and growth before considering automatic promotion.

**Gate:** chat and direct engine results agree; every positive proof/output
passes an independent check; corrections make dependent proposals reviewable;
no incomplete search becomes a confident conclusion.

### 4. Develop dialogue and contextual intent as a parallel research track

Keep a compact, typed discourse state for current topic/referents, open
question or choice, task phase/goal, last move, and the answer under
discussion. Add fields only to address measured failures. Test identical
short utterances in different contexts, topic changes, repairs, corrections,
history, and ambiguous or misleading context. Intent hypotheses may route or
ask clarifying questions; they must not create facts or authorize unsupported
actions.

In parallel, run the bounded corpus-based dialogue-move pilot in
`design_dialogue_moves.md`. Keep utterance citations, corpus/domain policy,
Codex label provenance, and context license explicit. Compare with the current
scripted baseline on task progress, inappropriate moves, coverage, abstention,
and labeling effort. Do not promote candidate frames based on surface
frequency or label agreement alone.

**Gate:** explicit context improves held-out multi-turn task completion without
wrong referents or stale updates. A learned move policy reaches runtime only
if it improves held-out outcomes without raising inappropriate actions.

Design detail: [contextual user intent](design_user_intent_model.md),
[dialogue moves](design_dialogue_moves.md), and
[conversation handling](design_conversation.md).

### 5. Expand math, coding, translation, and creative work

For each domain, select one useful slice with ordinary-language requests,
held-out wording, negative cases, a task-specific validator, provenance, and
multi-turn repair. Examples include exact arithmetic/composition, bounded
code generation with execution or property checks, translation with slot and
meaning checks, and creative writing with a clear boundary between invented
content and factual claims. Compose across domains only after each component
passes separately.

**Gate:** each slice demonstrates correctness, coverage, abstention,
completeness, provenance, and cost through chat. A feature checklist alone is
not evidence of domain competence.

Design detail: [domain expansion](design_domain_expansion.md).

### 6. Complete distribution and evaluate the goal

Finish the SQLite model contract for source text, facts, rules, learned
procedures, dialogue frames, and provenance. Build, copy to a clean location,
query without original files, learn through supported paths, export/reload,
and query again. Preserve compatibility imports/exports during migration and
make updates transactional.

Run the fixed scorecard on the clean distributable model. Compare its task
range and interaction qualitatively with the documented [70B-class
reference](capability_comparison_70b.md); report resource use and the remaining
gaps. No live 70B model run is needed unless a specific unresolved question
requires one.

**Goal gate:** broad held-out task coverage and reliable multi-turn interaction
are demonstrated without sacrificing correctness, evidence, repairability, or
resource constraints. Until then, keep the overall goal in progress and state
the limits plainly.

Design detail: [SQLite memory](sqlite_memory_design.md),
[natural-language handling](design_natural_language_handling.md),
[natural-language replies](design_natural_language_replies.md), and
[chat UX](design_chat_ux.md).

## Working rules

- Keep recombination, self-learning rules, and reasoning central; corpus growth
  is useful only when it improves a measured capability.
- Dialogue and contextual user intent remain priority research, not polish to
  defer until the reasoning work is finished.
- Change one capability boundary at a time; run focused runtime checks and
  nearby regressions after implementation work.
- Keep source text, accepted facts, taught examples, induced rules, derived
  proposals, and session context distinguishable in storage and replies.
- Require held-out evidence and an independent check before claiming transfer
  or correctness. Commit only intended files and preserve concurrent changes.
