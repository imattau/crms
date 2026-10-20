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
The prior driven-chat report on commit `043093f` found a confident Eiffel Tower
sentence after switching to the Colosseum, plus lost source-only context. On
the current checkout, the reproductions in `v1_426`, `v1_427`, `v1_419`, and
`v1_413` keep the completion answer on the Colosseum, preserve the latest
evidence for `why?`, retain named source-only follow-ups, and resolve France →
“and Italy?” to Italy's capital. These are small authored regression fixtures,
not evidence of broad dialogue generalization. The main dialogue gate is now
held-out variation across entities, layouts, topic changes, and repairs. Keep
the overall goal in progress.

## Execution order

### 1. Freeze a trustworthy chat scorecard and failure corpus

Keep a small versioned set of complete chat transcripts and task cases covering
direct questions, paraphrases, unsupported or conflicting claims, multi-part
requests, topic switches and pronouns, clarification and repair, procedure
composition, reasoning, and the existing domain slices. Hold out complete
documents and conversations. Record expected answer, acceptable abstention,
evidence requirements, and an independent checker for each case. Report correct,
wrong, omitted, abstained, coverage, latency, and provenance separately.

**Gate:** a clean process can replay the frozen set; every known failure remains
visible; component tests cannot substitute for chat outcomes.

### 2. Fix answer selection and dialogue grounding together

Use complete document fixtures and fresh chat processes to distinguish three
questions: did retrieval find the document, did sentence selection choose a
sentence that answers the requested relation, and did dialogue bind pronouns
to the intended topic? Include competing entities, answer sentences with
object pronouns, paragraph boundaries, “built”/“designed and built”, source-only
answers, unanswered turns, “why?”, “and X?”, and save/reload. A source sentence
that does not state the requested relation must not win merely because it
shares entity words. A pronoun-led sentence needs a local, explicit antecedent
check. Keep valid visible context after source-only answers and recoverable
abstentions; expire it on reset, explicit incompatible topic change, or a clear
context failure. Preserve ambiguity as a clarification or abstention, never a
silent entity guess.

Track wrong-answer sentences, wrong referents, omissions, abstentions,
clarifications, citation support, and task completion separately. Dialogue
intent remains a contextual hypothesis used for routing and repair; it cannot
create facts or authorize unsupported actions.

**Gate:** on held-out layouts and transcripts, no confident wrong relation or
wrong referent; citations support the answer; source-only context survives;
ambiguity is clarified or declined. Test whole turns and transcripts, not only
resolver helpers. Keep learned dialogue-move induction experimental until it
beats this explicit baseline.

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

## Immediate work packets

1. **Measure dialogue generalization.** Keep the reported Eiffel Tower /
   Colosseum, source-only context, `why?`, and France → Italy sequences as
   regressions (`v1_413`, `v1_419`, `v1_426`, `v1_427`). The first new transfer
   probe is now `v1_442`: four new entity/layout cases cover adjacent topics,
   an intervening third entity, line-wrapped text, plural antecedents, topic
   switches, `why?`, reload, and unsupported actions. Add independently
   authored conversations with interruptions, corrections, history questions,
   ordinal references, and unresolved choices. Report wrong referents, wrong
   answer sentences, omissions, clarification, abstention, citation support,
   and task completion separately. A direct request now interrupts an open
   clarification rather than being consumed as its missing value, and clear
   embedded WH requests reach the normal fact-question path (`v1_444`); broaden
   these forms and exercise them in complete held-out conversations. Attribute
   labels and authoring; do not
   present the Codex-authored probe as independent human evaluation.
2. **Advance source-derived self-learning rules.** Extend beyond current
   teacher-labeled phrase and connective examples using complete-document and
   source-disjoint holdouts. Keep source evidence, extracted candidates,
   teacher/labeler decisions, accepted rules, and independent validation
   distinct. Include quoted, negated, contrastive, metalinguistic, unrelated,
   and misleading prose. Report proposal precision and labeler effort; do not
   call cue matching or supervised alignment autonomous learning.
3. **Join unseen recombination to verified reasoning.** Send a held-out
   composition through ordinary chat, procedure/rule selection, an independent
   result checker, and proof verification where applicable. Test missing
   premises, explicit negatives, conflicts, cycles/integrity violations, and
   search exhaustion. Keep derived write-back review-only, lineage-complete,
   and invalidated after source correction until its governance gates pass.
4. **Improve contextual intent and dialogue moves against the baseline.** Use
   intent only as revisable context for routing, clarification, and repair; it
   cannot create facts or authorize unsupported actions. Keep learned dialogue
   moves experimental until conversation-held-out results improve task
   completion without raising wrong-referent or inappropriate-move rates.
5. **Use the scorecard to choose one breadth slice.** After packets 1–4 have
   clean-process evidence, choose the largest measured user loss and strengthen
   one bounded task in math, coding, translation, or creative work. Define
   held-out language, negative cases, an independent checker or human rubric,
   and repair behavior before implementation. Defer broader SQLite packaging
   until record and correction lifecycles are stable; then validate a copied
   model with source files unavailable.

**Checkpoint (2026-10-20):** the answer-selection slice now passes six focused
chat experiments, including the Sydney Opera House designer sentence, wrong
paragraph/entity negatives, an action-missing abstention, date answer selection,
and source-only topic retention after an unsupported follow-up. This closes
only that narrow regression set. General relation entailment, author-held-out
dialogue, source-only learning of action wording, and broad temporal phrasing
remain open.

The first new dialogue transfer probe, `v1_442_heldout_dialogue_transfer.py`,
passes four Codex-authored source/layout cases: 20/20 supported answer or
evidence steps selected the target entity, and 4/4 unsupported closing-date
questions abstained. It covers single-paragraph adjacent entities, separate
paragraphs with an intervening third entity, line-wrapped paragraphs, and a
plural `they` antecedent, including `why?`, exact citations, and state reload.
To support it, regular do-support verb spelling retrieval now applies across
WH roles, and a pronoun-led source sentence can be shown when its nearest
explicit paragraph subject matches the query entity. The 13 focused runtime
regressions (`v1_413`, `v1_414`, `v1_419`, `v1_420`, `v1_423`, `v1_425`,
`v1_426`, `v1_427`, `v1_435`, `v1_438`, `v1_439`, `v1_440`, `v1_442`) pass.
This is controlled transfer evidence, not an independently authored dialogue
benchmark; broader verbs, varied natural dialogue, and independent labels
remain open.

The procedure track now has an additional end-to-end recombination slice:
reviewed, source-cited sort and reverse phrases plus a cited duplicate-removal
example compose through learned `then` into an unseen unique→sort chat request.
It passes an independent output oracle, fresh-process generation, model reload,
and a descending near-miss abstention. The phrase extraction and connective
labels remain Codex-authored; this is teacher-attributed recombination, not
autonomous prose learning. Adjacent source-learning/composition regressions pass
7/7 (`v1_355`, `v1_431`, `v1_433`, `v1_436_source_derived_rule_phrase_review`,
`v1_437_heldout_publisher_phrase_review`, `v1_441`, `v1_443`). The new scope
controls exposed and then closed ten authored denial, uncertainty, quotation,
metalinguistic, and direction negatives; five asserted or conditional source
clauses remain review proposals with exact conditions visible. These cases
measure regression behavior, not field precision. The next gate remains
complete-document, source-disjoint transfer with independently authored
negative passages and a measured proposal precision.

The dialogue packet also exposed a short-answer routing bug: “Tell me a joke”
was stored as the missing entity after an open pronoun clarification. Direct
imperative requests are now classified before the open-slot fallback, while
valid entity replies and explicit slot corrections retain their routes. The
same router recognizes two direct/modal embedded-WH forms and preserves the
original wording in history while sending the question to the fact path. The
new transcript regression and eight adjacent intent/dialogue scripts pass
(9/9 total). This closes only the covered interrupted-slot and embedded-WH
forms; contextual intent generalization and open-ended creative capability
remain unproven.

A further source-only probe found that a question about Python's release date
was lost when the source called Python “a programming language” and then used
“The language.” Retrieval now licenses that description only when the source
explicitly supplies the same type and its nearest named subject matches the
query. The cited answer includes both the type link and date. A Java-nearest
control abstains. The indirect “Tell me when it was...” form is also normalized
to direct WH word order before pronoun resolution. Seven focused dialogue and
retrieval experiments pass (`v1_445`, `v1_442`, `v1_426`, `v1_427`, `v1_423`,
`v1_425`, `v1_438`). This is one bounded definite-description pattern, not
general noun phrase coreference or independent natural-corpus validation.

Do not grow the corpus as a substitute for these packets: more documents cannot
repair relation selection, context updates, or a missing composition learner.
Use a larger corpus only when a defined held-out evaluation needs it and record
its source mix, licensing/provenance, size, and exact build.

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
