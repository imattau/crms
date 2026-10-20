# CRMS goal execution plan

**Reviewed:** 2026-10-20 (including the real-source learning and copied-model replay)
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
diagnostic, not task accuracy, and still warns that intent handling does not
transfer reliably. Reported topic-switch and source-only context failures now
have focused regression coverage, but independently authored conversations
and varied layouts have not established dialogue reliability. Source-derived
rule discovery has a narrow positive signal, but no convincing precision and
coverage result across source-disjoint documents and publishers. Verified
reasoning is ahead of natural-language routing and broad rule learning.
The copied SQLite model now carries one reviewed real-source phrase through
acceptance, held-out checking, fresh-process chat, and removal of original
source files; this is a useful packaging slice, not validation of the full
learning and correction lifecycle. The extended `v1_436` additionally exports
a reviewed procedure rule with its source text, then generates and executes
held-out code from a clean copied model. This closes the operation-rule
packaging seam, while candidate extraction and mapping remain cue-based and
Codex-reviewed.

Recent regressions and component passes should be kept as controls, not
combined into an overall success percentage. In particular, passing scripted
dialogue cases does not establish conversational competence; a retrieval hit
does not establish that the answer addresses the question; and a verified
proof over an authored graph does not establish autonomous rule learning.

The dialogue review that reported a pronoun-led source sentence attributed to
the wrong entity and source-only context loss has since been replayed against
focused fixes. The selected current-checkout regressions pass, including topic
switch, source-only context, persisted evidence, and stale `why?` behavior.
Treat those as repaired controls, not as proof of general dialogue competence:
history recall and numbered-result selection have targeted regression checks,
but independently authored multi-turn transfer still needs a broader held-out
evaluation. The bounded reservation draft (`v1_467`) demonstrates one request →
clarification → correction → draft → reload path, but its parser and task
route are narrow.
The map-free scan (`v1_464`) found repeated relation candidates, but most
reviewed groups were unsafe, artifacts, or false/composite. `v1_468` found no
exact endpoint-pair overlap between candidate and dominant phrase groups, so
that filter is not useful as a promotion gate. `v1_469` demonstrates one
reviewed `capital city of` phrase from SimpleWiki through acceptance, a
five-page train/one-page holdout, SQLite reload, fresh-process chat, and a
copied portable model with original files removed. The field mapping remains
hand-coded, Codex supplies review, and there is no second-publisher transfer
result. Treat this as an end-to-end integration control, not autonomous rule
learning. The `v1_436` portable procedure check likewise demonstrates a
learned rule can be distributed and used, but it does not demonstrate the
multi-step recombination, reasoning, correction, and derived-case lifecycle
in the copied model. These findings keep independent dialogue transfer and
source-rule discovery as open gates; recombination and reasoning remain the
central capability bet.

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
surface area. Dialogue safety is a release gate for every chat-facing
capability; recombination, source-derived rules, and reasoning remain the
primary capability work.

### 1. Establish the shared end-to-end baseline and close the reported dialogue failures

Build one compact scorecard spanning factual questions, paraphrases,
multi-part requests, unsupported/conflicting claims, topic changes, source-only
answers, pronouns, clarification and repair, history, and ordinal references.
Use independently authored transcripts and varied source layouts alongside
fixed regressions. Include the reported Eiffel Tower/Colosseum referent case,
source-only context carryover, unanswered turns, and `why?` after topic
changes. Test clean-process and save/reload behavior.

Freeze the reported Eiffel/Colosseum pronoun switch, source-only follow-up
after an unanswered or review-only turn, stale `why?`, “what did I just ask?”
and “the first one” as full-transcript regressions. A pronoun-led source
sentence must be linked to its entity by paragraph or explicit relation
evidence; retrieval match or recency alone cannot choose the referent. Preserve
typed visible context through recoverable source-only answers and abstentions;
expire or replace it on explicit reset, topic change, or incompatible context.
Separate act classification, referent resolution, evidence lookup, answering,
and context update so a failed turn cannot erase valid context or explain the
wrong answer. Evaluate with independently authored transcripts and varied
source layouts, not resolver-only checks.

Model intent as a contextual, revisable hypothesis over the utterance and
explicit state: task and subgoal, active topic/referents, open question or
choice, previous move, and the answer under discussion. Keep state bounded and
inspectable. Intent may route, clarify, or repair; it cannot supply facts or
authorize unsupported actions. Dialogue-move induction remains research until
it beats the explicit baseline on held-out task outcomes.

**Gate:** no confident wrong referent on fixed regressions or independent
transcripts; correct follow-ups or focused clarifications; evidence supports
each factual answer; no stale explanation after a topic switch. Report
completion, omissions, abstentions, clarification, and label agreement
separately. Do not interpret single-annotator intent agreement as accuracy. If
this gate fails, fix context lifetime and grounding before adding more intent
classes or dialogue moves.

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
treated as semantic truth. Use `v1_464` as a noise baseline: freeze the
candidate generator before labeling, sample non-proposals, and test documents
and publishers withheld from discovery. Codex can label examples, but the
labeler identity and unblinded limits must be explicit; Codex review is not
independent validation. If useful yield requires hand-coded field-to-relation
truth or fails on a second publisher, redesign rather than promote the path.

`v1_470` adds a chat-accessible, report-only procedure candidate extractor
for a bounded “function/array/result will predicate” construction. It does not
name the operation; citations, polarity, quotation, and conditions stay
visible, embedded denial/uncertainty is distinguished, and no rule is
installed. The first publisher-disjoint excerpt check (`v1_471`) exposed a
boundary bug: decimal versions such as `SemVer 2.0.0` were truncated. The
candidate grammar now preserves that qualifier and source capitalization;
`v1_470` and `v1_471` plus four adjacent learning/recombination controls pass.
This remains one selected positive excerpt, not a precision or transfer result.
Freeze this revised grammar for the next complete-document, publisher-held-out
study. Do not add phrase-specific extractors before that study.

**Gate:** a frozen method finds useful candidates on held-out documents and a
second publisher with measured precision and review effort; sampled
non-proposals and negative controls do not become positive rules. Accepted
rules preserve exact source provenance and remain review-gated until holdout
validation. This proves a useful learning input, not broad autonomous
language understanding.

### 3. Demonstrate recombination through chat and join it to verified reasoning

Compose independently supported rules and procedures into genuinely unseen
multi-step requests. Vary wording, values, and operation order. Keep the
component examples, connective evidence, induced rule, and output validator
distinct. Include unsupported operations, missing steps, contradictions,
near misses, and incomplete instructions. Run the request through ordinary
chat and a fresh process; check output with an independent oracle.

**Gate:** at least one source-disjoint unseen composition succeeds through
chat and reload; the independent checker accepts valid outputs and rejects
invalid ones; unsupported or incomplete requests abstain. Include a
proof-backed reasoning step, a missing-premise or conflict case, and a
correction that invalidates dependent derived knowledge. Report teacher and
labeler effort. Supervised phrase alignment must not be described as
autonomous learning from documents.

### 4. Govern self-learning and derived knowledge

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

This research runs alongside stages 1–4, but its changes enter the runtime
only when the dialogue gate passes. Keep the weak Taskmaster transfer results
as warnings; do not tune against inspected test rows or substitute label
agreement for task completion.

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

## Immediate work queue — execute in this order

1. **Freeze the evaluation before tuning.** Preserve current dialogue and
   learning regressions, including fixed topic-switch/source-only-context cases
   and `v1_470`/`v1_471`. Record commit, corpus, splits, and scoring rubric.
   Do not use inspected holdout rows to change the implementation.
2. **Run the decisive source-learning transfer study.** Treat
   `v1_469`/`v1_436` as integration controls and `v1_464`/`v1_468` as noisy
   baselines. Apply the frozen revised candidate generator to complete
   documents from a discovery publisher and a held-out publisher, with actual
   relation/wording overlap. Sample proposals and non-proposals; include
   polarity, quotation, contrast, role-reversal, boundary, and unrelated
   negatives. Report precision, useful yield, missed opportunities, source
   independence, and review effort. Keep proposals inert. If useful precision
   and coverage transfer, proceed to rule induction; otherwise identify the
   failing boundary, revise the method, and reserve a new publisher for
   confirmation. Do not substitute a larger scan of one corpus.
3. **Evaluate dialogue transfer in parallel.** Keep fixed pronoun/topic-switch,
   source-only-context, stale-`why?`, history, and ordinal regressions locked.
   Add independently authored transcripts and varied source layouts; score
   wrong referents, irrelevant evidence, omissions, clarification, repair, and
   task completion before changing runtime behavior. Fix reproduced failures,
   then replay fixed and held-out cases in fresh processes. This is a release
   gate for chat-facing work, not a reason to defer the source-learning study.
4. **Prove recombination with reasoning on real evidence.** After the
   source-learning gate, take separately reviewed evidence, rules, and
   procedures through an unseen multi-step request in ordinary chat and a fresh
   process. Independently verify proof and output. Include missing premises,
   explicit negatives, conflicts, cycles/integrity failures, incomplete search,
   unsupported operations, source correction, and derived-case invalidation.
   Keep `v1_451`/`v1_456` as controls, not evidence that learning is autonomous.
5. **Close the self-learning loop under governance.** Only after the composed
   path is reliable, propose verified derived cases with lineage. Test
   correction propagation, invalidation, duplicate suppression, trust weighting,
   and storage limits before allowing automatic retrieval or reuse. Derived
   cases must never validate their generating rules or evidence.
6. **Expand breadth and distribution from measured losses.** Choose one
   bounded math, coding, translation, or creative task based on the scorecard;
   validate it through the same language interface before composing domains.
   Once learning and correction records stabilize, verify a copied SQLite
   model with searchable source text and accepted knowledge/rules, with original
   documents unavailable. Measure portability, size, compatibility, and task
   outcomes.

The dialogue packet is a parallel release-quality gate; it must not displace
the learning experiment. The source-rule result decides whether CRMS advances
the learner or redesigns the evidence-extraction step. Recombination proceeds
only after that decision, while reasoning checks are built into its acceptance
criteria. Math, coding, translation, and creative tasks remain next-stage
domain slices, not current distractions.

Self-learning write-back comes later because error amplification cannot be
evaluated until independently checked recombination works. This ordering keeps
the central capability bet explicit: learn from attributable evidence, combine
what was learned through reasoning and procedures, and only then let verified
outputs become reviewable new knowledge.




Do not enlarge the corpus, add a new dialogue mechanism, expand domain
coverage, or migrate the model store unless it clears one of these gates.
Dialogue measurement runs alongside the learning/reasoning path, not after
them. After these packets pass, choose one bounded math, coding, translation,
or creative task from measured user-task loss; then verify the copied SQLite
model against the same scorecard without original source files.

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
