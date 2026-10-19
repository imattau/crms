# Focused roadmap from current CRMS to its goal

**Reviewed:** 2026-10-20
**Status:** direction is aligned; capability breadth is not yet on track for the
overall goal. CRMS has inspectable foundations and narrow end-to-end wins, but
does not yet behave like a broadly capable assistant.

## Overall review and immediate direction

CRMS is still pursuing the right goal. Its distinctive strengths—explicit
knowledge, traceable evidence, bounded procedures, independently checked
reasoning, and correction—are visible in the code and in focused runtime
experiments. The work has not drifted into a different product.

The gap is breadth and integration. Current results establish selected
capabilities on controlled examples; they do not establish reliable performance
across ordinary requests or long conversations. The 70B-class comparison is a
useful product reference, but CRMS should be judged against a versioned task
scorecard, not against a few impressive demonstrations. Retrieval coverage,
labeler agreement, and passing component scripts must remain distinct from
end-to-end answer quality.

The next work should follow this critical path:

1. **Make the evaluation trustworthy and current.** Pin a clean code snapshot,
   corpus and transcript splits, expected answers, abstentions, and independent
   checks. Re-run the compact chat scorecard against that snapshot. Keep results
   from uncommitted trees clearly marked as working-tree diagnostics.
2. **Close dialogue grounding failures before adding dialogue features.** Extend
   the Eiffel Tower/Colosseum regression across paragraph layouts, intervening
   turns, entity changes, source-only answers, and save/reload. Fail any
   confidently wrong referent or stale explanation; ask or abstain when the
   context does not license a referent. The current authored transcript passes
   are useful starting controls, not broad dialogue evidence.
3. **Prove one source-disjoint learned recombination end to end.** This is the
   highest-leverage capability experiment: source text and examples should
   license components, a held-out source and unseen composition should transfer
   through chat, and an independent checker should validate the output. Keep
   teacher-assisted connective labels explicit where prose alone does not
   license them.
4. **Join that slice to verified reasoning and governed derivation.** Route the
   same user request through the chat interface, preserve proof/output checks,
   expose missing premises and incomplete search, and keep derived knowledge
   review-only with lineage until correction and invalidation work.
5. **Advance contextual intent alongside the above.** Improve task/subgoal
   tracking on held-out conversations; treat intent as a revisable hypothesis
   from the utterance and explicit state. Keep dialogue-move induction inert
   until it beats the scripted baseline on held-out outcomes.
6. **Expand domains and finish portable SQLite distribution only behind shared
   gates.** Validate one bounded slice each for math, coding, translation and
   creative work. Then prove a copied model works without its ingestion files,
   including learning, reload, evidence lookup and the same scorecard.

This means the project is **on track in architectural direction, but not yet on
track to claim the capability goal**. Continue focused runtime validation and
commit only intended files. Do not expand corpus size, domain count, or
dialogue machinery unless it improves a measured scorecard result or closes a
named capability gate.

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

## Execution sequence from the current snapshot

The priority list above describes the enduring work areas. This sequence says
what to do next and what evidence unlocks the following step. Keep dialogue and
intent research active alongside the learning work; do not postpone them until
reasoning is “finished.”

### Immediate work queue (reviewed 2026-10-20)

Work these packets in order. Keep each packet small enough to produce a
reproducible chat-level result before moving to the next one. The dialogue
research track stays active, but it should not displace the main capability
test: learning and recombining procedures that generalize beyond their
examples.

1. **Freeze a dialogue/intent evaluation slice before changing its rules.**
   Preserve the passing Eiffel Tower/Colosseum topic-switch cases and the
   source-only follow-up cases as regression controls. Add a small, fixed set
   of complete multi-turn examples covering topic switches, pronoun anchors,
   context after unanswered/source-only turns, `why?`, clarification, and
   save/reload. For contextual intent, use the prepared second-domain
   movie-ticket Taskmaster sample rather than extending restaurant-specific
   patterns first. Codex may label a bounded sample, with exact transcript
   spans and primary-labeler provenance; reserve conversations for test and
   report agreement, coverage, and errors separately. Do not call agreement
   accuracy or generalize from this pilot to open-domain dialogue.

   The context-free baseline and the first transcript-context replay are now
   recorded in [`design_user_intent_model.md`](design_user_intent_model.md).
   The current runtime has a bounded explicit-task goal rule and typed replies
   for parameters, choices, and confirmations. On four development dialogues,
   context replay jointly matched Codex act/task labels on 17/37 turns. On six
   test dialogues held back until the code freeze, it matched 22/68; the
   context-free comparison matched 15/68. Hypothesis coverage increased from
   39.7% to 66.2%, while agreement among hypotheses fell from 55.6% to 48.9%.
   These are one-labeler diagnostics from a transcript classifier replay, not
   chat completion or accuracy. The other 12 dialogues were exploratory during
   development and are not held-out evidence. Keep the six final dialogues
   frozen; do not tune from their disagreements.

   This completes the baseline setup and gives a bounded task-goal slice, but
   it does not close the broader dialogue reliability milestone. Keep intent
   labels inspectable and provisional, preserve the existing topic-switch and
   source-only follow-up regressions, and run the replay only when making a
   measured dialogue change. Continue dialogue research in parallel with the
   main recombination and reasoning work.

   **Exit:** a frozen clean-process replay establishes the current baseline;
   no confidently wrong referent, stale explanation, or context loss is
   accepted. The movie-ticket sample reports what the intent model covers and
   where it abstains before any rule is tuned from it.

2. **Run the source-disjoint recombination experiment.** Choose one compact,
   useful procedure family. Keep source text, extracted examples, connective or
   instruction labels, induced rule, and validator outcomes as separate
   artifacts. Use complete-document holdout, unseen compositions, independent
   wording, near misses, and an independent output checker. The current
   phrase-grid and the revised `stable unique → sort → reverse` result are
   controls, not the
   target evidence: the former is synthetic; the latter still depends on
   teacher-authored connective evidence and sparse operation examples.

   **Exit:** at least one held-out composition succeeds through ordinary chat,
   a fresh process, and reload; an independently implemented checker accepts
   it; unsupported or incomplete compositions abstain; provenance identifies
   every source and teacher/labeler contribution. If prose does not license the
   connective, record that boundary instead of implying autonomous
   self-learning.

3. **Join that learned composition to verified reasoning and governed
   derivation.** Route the same request through chat and the engine. Verify the
   output independently; exercise missing, conflicting, cyclic, and
   budget-limited premises. If the result is proposed for reuse, store it as a
   derived record with lineage and review status. Test correction and
   dependency invalidation before retrieval can rely on it.

   **Exit:** chat and engine agree; each positive has an accepted proof or
   independent task check; no incomplete search becomes a positive result;
   corrections make every dependent derivation discoverable and unusable until
   revalidated.

4. **Use results, not aspiration, to choose the next breadth slice.** Once
   packets 1–3 have stable gates, improve the largest measured loss in
   answer-bearing retrieval, paraphrase coverage, dialogue completion, or a
   bounded math/code/translation/creative task. Add one slice at a time with a
   held-out chat set and domain-appropriate validator. Defer SQLite contract
   completion until the records and write-back lifecycle exercised by those
   paths are stable; then prove build/copy/learn/reload without source files.

   **Exit:** new breadth improves held-out useful coverage without increasing
   wrong answers or hiding abstentions, and works in the portable model copy.

**Decision rule:** prefer the next task that removes a measured user-visible
failure or unlocks a held-out recombination result. Do not spend a cycle on a
new feature, larger corpus, or storage migration without a named benchmark
failure or an exit gate it enables. Recheck the overall goal after each packet:
CRMS is on track only when the same ordinary-language scorecard shows growing
held-out task coverage, controlled errors, useful multi-turn continuity, and
portable verified learning. A larger experiment count alone is not progress.

### Milestone A — Close the known chat correctness gaps

Use the recent multi-topic transcript and source-only follow-ups as the fixed
starting set. The 30-turn Eiffel Tower/Colosseum diagnostic now passes its
reported topic-switch and stale-explanation cases, but it is only a
two-paragraph fixture. Preserve those fixes, then vary document structure,
entity names, intervening turns, and follow-up wording to find the boundary.
Add any reproduced wrong-entity answer, lost valid context, or stale `why?`
target as a regression. Separate turn classification, referent resolution,
answering, and context update only where that makes regressions easier to
prevent. Preserve a complete transcript and expected answer/abstention for
every case.

**Exit evidence:** fresh-process replays preserve the current regression wins
across varied documents and entity names, with no confident wrong-entity
answers or stale explanations; ambiguous references ask or abstain; valid
source-only context survives the follow-up; citations refer to displayed
evidence. The gate must be broader than the current Rome/Paris fixture.

### Milestone B — Demonstrate source-disjoint rule learning and recombination

Treat `v1_433` as a useful vertical slice, not as proof of source-driven
learning: it has three narrow numeric examples, one example per operation,
Codex-authored contrast/connective evidence, and four held-out lists. Expand
one useful procedure family with multiple independently sourced examples per
component. Keep the source sentence, executable example, proposed instruction
mapping, teacher/labeler input, induced rule, and validator result as distinct
records. A citation to code is evidence for the code behavior; it does not by
itself establish that prose licenses an instruction.

Hold out complete documents and at least one composition. Vary natural-language
requests, component order, input values, and near-miss instructions. Include
wrong outputs, missing steps, unsupported operations, and conflicting examples.
Run the experiment through chat, verify outputs with an independent checker,
then save, reload, and repeat it in a clean process. Track coverage, correct,
wrong, abstained, provenance retained, and teacher effort separately.

**Exit evidence:** the held-out source and unseen composition pass through chat
and reload with correct independently checked outputs and complete lineage;
unsupported operations abstain; no generated output validates the rule that
generated it. If source text cannot support instruction alignment without
hand-authored connective evidence, record that boundary and test a clearly
scoped teacher-assisted route instead of claiming autonomous induction.

### Milestone C — Join learned procedures to verified reasoning

Choose a single composition family from Milestone B and pass it through the
natural-language router, rule/proof selection, output validation, explanation,
and optional derived-case proposal. Include complete, missing, contradictory,
cyclic, and budget-limited cases. Keep derivations review-only with lineage;
test correction and invalidation before allowing reuse. This is the point where
recombination and reasoning become one demonstrated capability rather than
separate engine experiments.

**Exit evidence:** chat and direct-engine outcomes agree; every positive result
has an independently verified proof or task result; incomplete searches never
become positive answers; corrections identify dependent proposals; derived
knowledge cannot outrank conflicting taught/source evidence.

### Milestone D — Grow contextual dialogue and intent with task evidence

In parallel with B and C, extend the multi-turn benchmark beyond simple factual
follow-ups. Include topic switches, ambiguous references, user corrections,
clarification cycles, “what did I ask?”, multiple open choices, and the same
utterance under different context. Keep intent as a confidence-bearing,
revisable hypothesis from the utterance plus explicit discourse state. Use it to
route, clarify, or repair; it must not create facts or authorize unsupported
actions. Compare any learned dialogue moves with the explicit baseline on held-
out conversations and record label provenance and domain policy.

**Exit evidence:** held-out multi-turn task completion improves over the
current baseline without increasing wrong referents, stale context, or
inappropriate actions. Dialogue-move induction remains experimental unless it
beats the baseline on those measures.

### Milestone E — Expand one bounded slice per domain

Only after the shared gates above are stable, choose one user-useful task slice
each for math, coding, translation, and creative writing. Define the supported
request forms, independent checker, evidence/provenance policy, negative cases,
and repair flow before implementation. Test each through ordinary CRMS
language, then test cross-domain composition only after the component slices
pass independently. The current arithmetic, list transforms, grounded
translation, and story grammar are starting points, not domain-completion
claims.

**Exit evidence:** each slice reports held-out coverage, correct/wrong/abstained,
completeness, provenance, repair success, and cost through chat. Creative work
also gets human ratings for coherence and requested constraints; template
validity alone is insufficient.

### Milestone F — Freeze the portable model contract and compare capabilities

Once the records needed by A–E are explicit and stable, finish the SQLite
schema and migration path. Copy a built model to a clean location, remove
access to ingestion files, query it, learn through supported paths, export or
reload it, and query again. Run the same versioned chat scorecard against that
copy. Compare task range and interaction qualitatively with the 70B-class
reference, and publish resource use and unsupported cases.

**Exit evidence:** the clean copy preserves searchable source text, facts,
rules, procedures, dialogue state where appropriate, and lineage across build,
learn, reload, and query. Distribution is complete only when this works without
the original source files. Capability comparison must report measured CRMS
results and must not imply parity from selected examples.

### Review cadence and scope control

At each milestone review, update the benchmark report and roadmap from actual
runtime evidence. Select the next implementation task by expected reduction in
wrong answers or increase in held-out useful coverage, while preserving the
recombination, self-learning-rule, reasoning, and dialogue priorities. Do not
add corpus volume, domains, UI polish, or storage migration just to show
activity; each must unlock or measure a capability. Keep one end-to-end
vertical slice usable before starting another, and retain all failed probes as
negative controls.

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

`v1_433_document_sourced_procedure_composition.py` is a stepping stone: the
revised `stable unique → sort → reverse` artifact passes four held-out lists
through chat and a fresh process, and ablation confirms that every stage affects
the tested outputs. Sort and reverse have cited code pairs; stable-unique
examples are Codex-labeled and linked to Python dictionary-ordering semantics.
The contrast examples, instruction mappings, and sequence connective remain
teacher-attributed. The test still lacks complete-document holdout and does not
meet the source-disjoint transfer gate.

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
