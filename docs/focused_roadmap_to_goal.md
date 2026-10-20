# Focused roadmap from current CRMS to its goal

**Reviewed:** 2026-10-20, against the current checkout and recorded runtime
evidence through `v1_543`.
**Status:** active execution plan. The broad capability goal is not yet
demonstrated.

## Destination

Build a lightweight, distributable language system that can handle a broad
range of ordinary requests, maintain useful context across turns, combine
knowledge, learned procedures and reasoning, and improve from use. Answers and
artifacts should remain inspectable, correctable, and clear about what is
known, inferred, uncertain, or unsupported. Coding, math, translation,
creative work, and other domains should share the natural-language interface.
Strong 70B-class models are qualitative references for task breadth and
interaction quality, not parity targets or required live comparators.

## Current assessment

CRMS has substantial building blocks: searchable source text, provenance-rich
knowledge and procedures, review-gated learning, bounded proof-checked
reasoning, contextual dialogue state, feedback and correction paths, and a
portable SQLite model. Controlled end-to-end experiments show that reviewed
source claims and rules can be used in chat, that proof-selected results can
feed a learned procedure, and that some learned behavior survives copying the
model and removing original source files.

The architecture remains aligned with the goal; the capability claim is not
earned yet. Most positive evidence is still synthetic, narrowly framed,
hand-mapped, Codex-labeled, or orchestrated by experiments. The principal gap
is transfer across the complete user path: ordinary language must select and
combine the right evidence, rules, procedures, and checks on a held-out task.
`v1_540` found expected text for all 30 canonical questions in a 1,200-document
synthetic corpus, but only 4 of 14 wording probes received source-backed
answers; 6 answer-expected probes remained incomplete. This is useful scale
and retrieval evidence, not broad language understanding.

The `v1_541` runtime slice now answers a bounded `Where does ENTITY VERB?`
question from an explicit subject, matching verb form, and cited locative
phrase. Wrong entities, object-position mentions, unlicensed verb synonyms,
and multiple locations are controlled; multiple cited locations are reported
together rather than ranked. The new case and four adjacent natural-language
and dialogue suites pass. This is a narrow source-grounded route, not evidence
of general predicate or location understanding.

The `v1_542` dialogue check fixes one user-visible history mismatch: after a
pronoun follow-up, “What did I just ask?” now recalls the user's original
wording, not the internally resolved entity-filled query. Explanation requests
such as “Why?” are skipped when selecting the last substantive question. The
new fresh-CLI regression and the 30-turn dialogue, paragraph-grounding, and
source-topic controls pass. This improves one history operation; history,
ordinal references, and open-ended continuity still need broader held-out
conversation evaluation.

The `v1_543` integration applies the existing reviewed relation-learning path
to a real chat gap from the broad-corpus audit: “Where does the Serein River
run?” can use a source sentence saying it “flows through” a city after two
independent source-backed examples explicitly align `runs` with `flow through`.
One example alone does not license the expansion; the held-out entity/source
is cited, and alignment sources are shown in fresh chat. A separate unrelated
verb still abstains. This demonstrates a small learned-language-plus-evidence
composition through chat and save/reload, but the examples and task are
controlled, the supervision is manually supplied, and this is not learned
source-rule discovery or broad paraphrase transfer.

Recombination, self-learning rules, reasoning, and dialogue are the central
research priorities. Dialogue safety is also a release gate for every
chat-facing change. Source-derived rule discovery should proceed in parallel
as a measured research lane, but it should not block recombination with
already reviewed components. Automatic reuse of derived knowledge remains
gated on independent verification and correction propagation.

## Focused execution sequence

### 1. Freeze the end-to-end baseline and preserve dialogue safety

Create a compact, versioned scorecard of complete tasks and conversations,
then run it in clean processes against the current checkout before changing
behavior. Include the known Eiffel Tower/Colosseum pronoun switch,
source-only context retention, failed-turn context loss, stale `why?`, history
recall, ordinal references, Marie Curie/Einstein retrieval confusion,
compound-question omissions, and current where-question wording gaps. Add
independently authored conversations with varied paragraph layouts, topic
switches, ambiguous references, repairs, and same utterances under different
contexts. Keep the user-edited `experiments/reports/large_corpus_chat_audit.json`
untouched; direct new runs to a fresh report path.

Track task completion, correctness, omitted parts, wrong referents, evidence
validity, clarification, abstention, repair, context persistence, latency, and
reload separately. Intent-label agreement is diagnostic only. Contextual
intent may route, clarify, or repair; it may not add facts or authorize an
unsupported answer. Keep all known failures as permanent controls and rerun
the fixed dialogue suite after chat changes.

**Gate:** fixed cases pass in clean processes; no confident wrong referent or
unsupported factual answer; unresolved ambiguity prompts a focused question or
abstention; source-only evidence remains usable in relevant follow-ups; and
explanations refer to the current answer. Any unresolved safety failure is
fixed before widening the chat surface.

### 2. Make recombination plus reasoning work through ordinary chat

This is the primary capability milestone. Use independently reviewed facts,
rules, and procedures to build held-out tasks that require at least two
distinct operations, such as selecting entities with a verified relation,
aggregating or transforming the selected results with a learned procedure,
and explaining the result with its evidence or proof. Test at least two task
families so one narrow route cannot stand in for general composition. Vary
wording, entities, values, evidence order and layout, and operation order.
Keep discovery, connective supervision, learned components, and output
checking visible in provenance.

Run the tasks through normal chat and a fresh process. Use an independent
oracle or checker, and include missing premises, explicit negatives,
conflicts, cycles, invalid or incomplete proofs, unsupported operations,
partial multi-part requests, and tampered outputs. The experiment harness may
prepare examples and check results; it must not choose the answer or compose
the steps on behalf of chat.

**Gate:** frozen, held-out tasks complete through chat and reload in at least
two task families; independent checks accept valid outputs and reject invalid
ones; incomplete, contradictory, or unsupported cases do not become confident
positives. Report completion, errors, omissions, abstention, proof/evidence
validity, and cost separately. If only the harness can connect the steps, the
gate remains open.

### 3. Establish source-derived rule transfer in parallel

Treat rule discovery as a bounded learning research track that can supply
future recombination. Freeze the candidate method before evaluating it on
untouched complete source units and a publisher not used for development.
Review proposals and sampled non-proposals. Preserve subject and object roles,
polarity, conditions, scope, contrast, qualifiers, and separate citations for
claims and supporting context. Candidates remain review-only until accepted
through existing learning gates. Record labeler identity, useful proposals,
false proposals, missed claims, abstentions, review effort, and source
diversity. Codex labels are explicit supervision, not independent validation.

**Gate:** source-disjoint evaluation shows useful reviewable claims with
measured error and review burden, and downstream held-out checks show that
accepted rules transfer. Candidate count, corpus size, and retrieval yield do
not pass this gate. Do not block the recombination milestone on this track;
use reviewed components until new rules qualify.

### 4. Close the self-learning loop under correction controls

After the composition gate, let independently verified outputs create
lineage-bearing derived proposals. Keep derived cases separate from taught and
source-backed knowledge, with lower trust until revalidated. Test duplicate
suppression, conflict handling, retrieval weighting, stale lineage,
correction propagation, invalidation, restart, and bounded store growth.
Inject an incorrect derivation and prove it cannot validate its generating
rule or amplify through reuse. Keep write-back review-gated until these
controls pass.

**Gate:** correcting any premise, source, or rule identifies and disables all
dependent derived cases until independently revalidated; invalid proofs or
lineage cannot support answers; provenance and trust survive save, reload, and
model copy; storage growth follows a measured policy.

### 5. Improve dialogue and contextual intent from measured failures

Continue dialogue as a priority research area, but compare each addition with
the explicit baseline on complete held-out conversations. Keep discourse
state bounded and inspectable: active task and subgoal, topic and referents,
open questions or choices, prior move, unresolved ambiguity, and answer under
discussion. Separate act classification, referent resolution, evidence
lookup, response, and context update so one failed answer does not erase valid
context or explain a stale result. Test topic change, source-only evidence,
clarification, repair, history, and reload together.

Treat induced dialogue moves as a research experiment, not a prerequisite for
basic safe interaction. Corpus labels may be proposed by Codex but remain
traceable and reviewable. Compare move frames and contextual intent with
hand-checked baselines on held-out conversations; do not promote them based on
label agreement alone.

**Gate:** new dialogue behavior improves held-out task completion without
raising wrong bindings, stale context, unsupported claims, or inappropriate
moves. Ambiguous context is clarified or safely declined.

### 6. Expand task breadth one validated domain slice at a time

Add bounded coding, math, translation, and creative tasks through the same
natural-language interface. Choose slices from observed scorecard failures.
For each slice, define held-out requests, negative cases, independent
validation or a clear quality rubric, evidence policy, and repair behavior
before implementation. Validate each domain alone before testing cross-domain
compositions. For creative work, score constraint-following and coherence
separately from factual grounding.

**Gate:** each slice demonstrates useful held-out completion through chat,
with correctness or quality, omissions, unsupported outputs, provenance,
repair success, abstention, and runtime reported. A worked example does not
establish domain competence.

### 7. Validate SQLite as the complete distributable model

Once knowledge, rule, and correction lifecycles are stable, copy the model to
a clean location where original source files are unavailable. From the copy
alone, query and cite searchable source text, learn and review, recombine,
reason, explain, correct, save/reload, and run the shared scorecard. Check that
source text, accepted knowledge, procedures, citations, licensing metadata,
and correction lineage survive. Record model size, compatibility, migration,
and runtime. Academic paper platforms and other imports must preserve source
and licensing metadata.

**Gate:** all tested behavior depends only on the copied SQLite model and
runtime; original documents are not required for distribution; evidence and
corrections remain inspectable after reload.

## Immediate execution card

1. Replay the known full-turn dialogue failures on clean sessions and update
   the scorecard with current outcomes; preserve the synthetic audit report.
2. Freeze held-out composition/reasoning tasks and independent checkers before
   tuning. Start with reviewed components and at least two task families.
3. Keep dialogue regressions running for each chat change, and repair any
   reproduced high-severity context or grounding failure before merging it.
4. Run the frozen source-rule transfer study in parallel, keeping all
   candidates review-only.
5. Promote derived write-back only after the composition and correction gates
   pass; widen domains and validate the copied model after the reusable path
   is stable.

For each change: tie it to a reproduced failure or named gate; preserve the
case before tuning; change the smallest responsible seam; run targeted runtime
checks and relevant cross-capability controls; record limitations; and commit
only the intended project files. Preserve user-owned data and report the
provenance of authored, Codex-labeled, hand-coded, and independently checked
results separately.

## Related project documents

- [Current development plan](current_development_plan.md) — active work queue
  and recent implementation history.
- [Natural-language handling](design_natural_language_handling.md) and
  [chat UX](design_chat_ux.md) — routing and response design.
- [Dialogue design](design_conversation.md), [dialogue moves](design_dialogue_moves.md),
  and [contextual intent](design_user_intent_model.md) — dialogue research.
- [Learning dynamics](design_learning_dynamics.md) — governed derivation and
  correction.
- [Evidence independence and transfer](design_evidence_independence_and_transfer.md)
  — source-disjoint validation.
- [Domain expansion](design_domain_expansion.md) — coding, math, translation,
  and creative task slices.
- [70B-class capability comparison](capability_comparison_70b.md) — qualitative
  breadth and interaction reference.
