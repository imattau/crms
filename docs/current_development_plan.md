# CRMS focused development plan

**Reviewed:** 2026-10-20
**Status:** direction is sound; the capability goal remains unmet.
**Purpose:** set the next execution order. The [focused roadmap](focused_roadmap_to_goal.md)
and linked design documents retain supporting detail and prior experiments.

## Destination

CRMS aims to become a lightweight, distributable language system that can
understand and complete a broad range of ordinary requests, continue across
turns, recombine knowledge and procedures, and improve from evidence and use.
Answers and generated artifacts should be inspectable, correctable, and honest
about uncertainty. The natural-language interface should support coding, math,
translation, creative work, and other domains. Strong 70B-class instruction
models are a reference for breadth and interaction, not a parity claim or an
architecture requirement.

## Overall review

The project has substantial foundations: searchable source text; explicit,
cited facts and procedures; bounded proof search and verification; SQLite-backed
model paths; and narrow demonstrations of language transfer, procedure
composition, contextual intent, and dialogue continuity. These results are
useful but mostly controlled, authored slices.

The central gap is generalization and integration. Procedure wording and
connectives still rely on teacher-attributed labels; source-driven rule
discovery has not demonstrated reliable proposal precision on complete,
held-out documents. Recombination works for bounded taught components but has
not yet shown a broad path from source material through learning, novel
composition, independent checking, and governed write-back. Reasoning is
stronger in the engine than in natural-language coverage; dialogue and intent
remain context-sensitive and narrowly evaluated. A copied model has not yet
been shown to support the full learning and correction lifecycle without its
original source files.

Recent work closes specific dialogue and retrieval regressions, including
topic-bound source follow-ups and an Eiffel Tower/Colosseum pronoun case. The
passing `v1_413`, `v1_419`, `v1_426`, `v1_427`, and `v1_442` cases are controlled
regressions, not independent evidence of broad dialogue reliability. Likewise,
the `v1_441` unique→sort recombination path is an end-to-end, teacher-attributed
demonstration, not autonomous rule learning. See the detailed roadmap for the
full evidence and limits. Keep the overall goal in progress.

## Execution order

Run the first three packets as the active program. Dialogue and contextual
intent evaluation continue alongside them, but do not let isolated UX fixes
displace the recombination, self-learning, and reasoning gates.

The current procedure engine now has a strict document-disjoint scaffold
proposal mode (`CRMSModel.propose_procedure_scaffolds` with
`require_source_disjoint=True`). It can validate structural reuse across
reviewed phrase rules when example sources, instruction sources, and labeler
IDs are complete. It does not extract or understand procedure wording from raw
prose, and distinct document IDs do not establish independent publishers.

### 1. Lock the evaluation contract and dialogue safety baseline

Maintain a versioned, clean-process chat scorecard with complete transcripts
and source documents held out where applicable. Cover answer selection,
paraphrases, multi-part requests, unsupported and conflicting claims,
topic changes, pronouns, source-only answers, clarification and repair,
history questions, procedure composition, and reasoning. Record expected
answer, acceptable abstention, evidence/proof requirements, and an independent
checker or human rubric. Report correct, wrong, omitted, abstained,
clarified, citation-supported, and completed outcomes separately.

Use the latest user-reported dialogue failures as regression cases, especially
cross-topic pronouns, source-only context, `why?`, interruptions, history, and
ordinal references. Test complete turns and save/reload in fresh processes.
Keep valid visible context through source-only answers and recoverable
abstentions; a pronoun-led sentence must be locally grounded to its entity.
Intent is contextual and revisable: it may route, clarify, or repair, but cannot
create facts or authorize unsupported actions. Keep learned dialogue moves as
a research track until they outperform the explicit baseline on held-out
conversations.

**Exit:** fixed failures remain visible and pass; held-out conversations show
no confident wrong referent or unsupported relation. Ambiguity is clarified or
declined. Attribute who authored cases and labels; Codex-authored cases are not
independent human evaluation.

### 2. Demonstrate source-derived rule learning, then unseen recombination

This is the main capability gate. Begin with the existing procedure path, but
test whether CRMS can propose operation and connective rules from source text
without bespoke phrase extractors for each selected passage. Use complete
documents and source-disjoint holdouts. Include unrelated, quoted, negated,
contrastive, conditional, metalinguistic, and misleading passages. Keep source
evidence, extracted candidate, teacher/labeler decision, accepted rule,
composition, and independent validation as distinct records with provenance.
Measure proposal precision, useful coverage, review burden, and labeler effort.

Compose held-out procedures from independently supported components, vary
request wording and input values, and include reordered steps, missing steps,
near misses, and unsupported operations. Run each task through ordinary chat
and a fresh process; check outputs with an independent oracle. Codex may label
proposals, but that contribution must be explicit and cannot count as
independent validation. Do not call cue matching or supervised alignment
autonomous learning.

**Exit:** a genuinely unseen, source-disjoint composition succeeds through
chat and reload; the independent checker accepts valid results and rejects
invalid ones; unsupported cases abstain; provenance separates evidence from
supervision; and measured proposal precision and review effort justify further
automation.

### 3. Join recombination to verified reasoning and governed derivation

Route the same natural-language task through chat, rule/procedure selection,
and the appropriate independent checker or proof verifier. Cover supported
conclusions, missing premises, explicit negatives, conflicts, cycles or
integrity violations, and search exhaustion. Keep unknown, negative,
contradiction, incomplete search, and missing support distinct.

Only then exercise the feedback loop: retrieve → compose → verify → propose a
derived case. Derived cases remain lower-trust and reviewable, retain complete
lineage, and cannot validate the rules that produced them. Test correction,
dependency invalidation, duplicate control, and growth policy before allowing
accepted derived knowledge to influence ordinary retrieval.

**Exit:** chat and engine agree; every positive has a verified proof or
task-specific check; incomplete search cannot produce a positive; and source
corrections make dependent derivations unusable until revalidated.

### 4. Improve contextual intent against the dialogue baseline

Represent task goal, active subgoal, topic/referents, open questions or choices,
and recent answer state explicitly and compactly. Add state only to address a
measured failure. Test identical utterances in different contexts, topic
changes, corrections, interruptions, confirmation, and repair. Measure intent
classification, safe context resolution, inappropriate moves, and successful
task completion separately. Continue the dialogue-move induction pilot as
research with cited utterances, source/domain policy, held-out conversations,
and explicit Codex labeling provenance.

**Exit:** intent improves held-out task completion without increasing wrong
referents, stale context, or inappropriate moves. Learned dialogue moves beat
the explicit baseline before becoming a product path.

### 5. Expand task range one validated domain at a time

Use the shared natural-language and validation path to strengthen one bounded
task in math, coding, translation, then creative work. Define held-out wording,
negative cases, independent checker or human rubric, evidence policy, and
repair flow before implementation. Test cross-domain composition only after
individual slices pass. For creative work, score coherence and constraint
satisfaction separately from factual grounding.

**Exit:** each slice reports held-out coverage, correctness, omissions,
abstentions, provenance, repair success, and cost through chat. Select each
next slice from measured user loss, not convenience.

### 6. Complete the portable SQLite model contract

Once knowledge, rule, provenance, correction, and derivation records stabilize,
verify that one distributable SQLite model contains searchable source text,
accepted knowledge, rules/procedures, and provenance. Build and copy it to a
clean location; make original ingestion files unavailable; then query, learn,
correct, save/reload, and replay the scorecard against the copy.

**Exit:** the copy supports the tested answer, evidence, learning, correction,
and reload paths without source files. Report model size, runtime, and limits.

## Immediate work packets

1. **Source-rule generalization probe:** use the strict source-disjoint scaffold
   path in `v1_446` as the validation baseline, then choose a small, licensed
   corpus with complete documents and held-out publishers. Freeze candidate
   labels and negative passages before implementing any prose extractor.
   Measure which operation structure transfers, where Codex labels are
   required, proposal precision, and review time. Decide from this result
   whether a production review path is justified; do not expand the corpus for
   its own sake.
2. **Unseen recombination through reasoning:** define one task whose procedure
   has a missing-premise, conflict/negative, and invalid-output control. Make
   the procedure choice, proof/check, chat wording, and provenance observable
   end to end. This is the nearest test of whether the existing components
   compose into a trustworthy capability.
3. **Dialogue transfer set:** add independently authored full transcripts for
   topic switches, interruption/correction, `why?`, “what did I just ask?” and
   ordinal references. Include the user-reported wrong-referent patterns and
   varied paragraph layouts. Keep this evaluation active while packets 1–2
   proceed; fix confident errors before adding learned dialogue moves.

Do not add large corpora, more chat templates, a domain, or a storage migration
unless it unblocks one of these gates or improves a measured scorecard outcome.

## Working cadence and decision rule

For each packet, retain the smallest failing transcript or task as a regression,
then run it with nearby negative cases through chat, fresh-process persistence,
and the relevant independent checker. Record exact code snapshot, corpus,
authoring/labeling source, outcomes, and remaining failure modes. Commit only
intended project files. Keep user-owned worktree changes out of the packet
unless they are specifically being evaluated and the scope is clear.

Choose the next change by reduction in confident errors, increase in held-out
useful coverage, or removal of a named integration blocker. Passing more
scripts, ingesting more text, or producing more rules alone is not evidence of
progress. Reassess after every packet whether evidence has moved CRMS closer to
its destination and state plainly what remains unproven.
