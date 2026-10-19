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
Recent dialogue tests improve single-topic pronoun grounding and explicit topic
switches, but a driven chat still exposed two answer-selection/context gaps:
`Who designed the Sydney Opera House?` can prefer a less relevant sentence
about when it opened over the nearby “Jorn Utzon designed it” sentence, and
source-only answers do not always leave usable context for “and Italy?” or
“and the Colosseum?”. A separate Eiffel/Colosseum test showed why an `It ...`
sentence must be bound to the nearest suitable antecedent, not whichever entity
makes the sentence answerable. These failures are now the first user-facing
gate. Keep the overall goal in progress.

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

1. **Answer-bearing retrieval:** add a fixed chat regression for the Sydney
   Opera House example alongside direct-entity, wrong-paragraph, and missing-
   relation negatives. Correct selection must preserve the source sentence and
   citation, and must abstain if the only named-entity sentence does not answer
   the question. Keep lexical retrieval, relation fit, entity identity, and
   answer-type checks separately observable.
2. **Context after source-only answers:** replay “What is the capital of
   France?” followed by “and Italy?”, plus an explicit topic switch and `why?`.
   Retain only entities and answers actually shown to the user. An unsupported
   follow-up must not borrow a prior answer or explain an unrelated turn.
3. **Independent dialogue set:** add author-held-out transcripts and varied
   paragraph/entity layouts for pronouns, multiple entities, repairs, history,
   and ordinal references. Keep current curated transcripts as regression
   controls, not the generalization score.
4. **Source-derived procedure transfer:** expand proposal quality and source
   independence before adding more hand labels. Keep quoted, negated,
   contrastive, metalinguistic, and unrelated prose as negative controls. Make
   labeler effort and the distinction between source evidence and supervision
   visible.
5. **Unseen composition plus proof checks:** join a learned procedure with a
   verified reasoning step in ordinary chat. Check missing premises, explicit
   negatives, conflicts, cycles/integrity violations, and budget exhaustion;
   keep derived write-back review-only until correction and invalidation pass.

**Checkpoint (2026-10-20):** the answer-selection slice now passes six focused
chat experiments, including the Sydney Opera House designer sentence, wrong
paragraph/entity negatives, an action-missing abstention, date answer selection,
and source-only topic retention after an unsupported follow-up. This closes
only that narrow regression set. General relation entailment, author-held-out
dialogue, source-only learning of action wording, and broad temporal phrasing
remain open.

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
