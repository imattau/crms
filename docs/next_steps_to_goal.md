# Focused execution plan: current CRMS to its goal

**Reviewed:** 2026-10-20  
**Status:** active plan; the capability goal remains unmet.

## Goal

Build a lightweight, distributable language system that can handle a broad
range of ordinary requests, continue across turns, combine learned knowledge
and procedures, reason over evidence, and improve from use. Its answers and
artifacts must remain inspectable, correctable, and honest about what is known,
inferred, uncertain, or unsupported. Coding, math, translation, creative work,
and other domains should use the same natural-language interface. Strong
70B-class instruction models are a qualitative reference for task breadth and
interaction, not a parity target or a required live comparator.

## Current position

CRMS already has a substantial symbolic foundation: searchable source text,
provenance-bearing facts and procedures, review-gated learning, bounded
proof-checked inference, contextual dialogue state, and a portable SQLite model.
Recent controlled slices show learned procedures can be recombined with
proof-selected facts, exact math can operate on those results, and a copied
model can carry some learned behavior. The newest count slice learns to count
proof-selected entries and checks its semantic equivalences over 23,595 small
input combinations.

These results establish mechanisms, not broad capability. The largest gap is
reliable transfer through the whole ordinary-chat path. Examples and labels
are still often synthetic or Codex-authored; source-driven rule discovery has
not yet shown reliable cross-publisher precision and coverage; dialogue intent
does not transfer reliably; and derived knowledge is not yet safe to promote
and correct at scale. A larger corpus, another isolated feature, or a passing
authored fixture does not close these gaps.

## Priorities

1. **Keep dialogue safe and useful.** Dialogue is a research priority and a
   release gate for every chat-facing change. It must preserve relevant
   context, ground referents, track the answer under discussion, and clarify
   when context does not identify one answer.
2. **Make recombination transfer.** Learn reusable operations and composition
   rules, then complete held-out user tasks by combining them through chat.
3. **Strengthen reasoning.** Route natural-language requests to proof-backed
   inference and combine conclusions with procedures without weakening proof,
   conflict, cycle, or abstention checks.
4. **Learn rules from sources.** Establish source-disjoint quality and useful
   coverage for proposed rules. Keep candidates reviewed until the evidence
   supports safe promotion.
5. **Close the governed self-learning loop.** Let verified outputs become
   lineage-bearing proposals; prove correction, invalidation, and independent
   revalidation before they influence normal retrieval.
6. **Widen domains and validate distribution.** Use the same interface for
   coding, math, translation, and creative tasks, then verify the complete
   lifecycle from a copied SQLite model with original sources absent.

The order is evidence-driven: dialogue safety runs continuously; source-rule
research runs alongside recombination; self-learning promotion depends on
independent verification and correction; domain expansion follows reusable
capability gates rather than preceding them.

## Work sequence and gates

### 1. Freeze the end-to-end chat and dialogue scorecard

Create one compact versioned packet of complete conversations and tasks. Keep
the reported Eiffel Tower/Colosseum pronoun switch, source-only context,
failed-turn context loss, stale `why?`, history recall, ordinal selection,
and save/reload cases. Add independently authored conversations with varied
paragraph layouts, topic changes, ambiguous referents, and natural follow-ups.
Include reasoning/recombination tasks and negative, missing-premise,
conflicting, cyclic, and unsupported controls. Track correct completion,
wrong answers, omissions, clarification, abstention, evidence/proof validity,
latency, and reload behavior separately. Keep intent-label agreement separate
from task success.

Use contextual intent as a revisable hypothesis over the current utterance and
explicit discourse state (active topic, referents, open questions/options,
task/subgoal, and answer under discussion). It may route, clarify, or repair;
it may not add facts or authorize unsupported actions. Codex may label examples
and review proposals, but those labels are supervision, not independent
validation.

**Gate:** fixed controls pass in a clean process; independently held-out
conversations show no confident wrong referent; ambiguous context gets a
focused clarification or abstention; every factual answer is supported by the
shown evidence or a verified proof. Repair the smallest responsible seam when
this gate fails. Do not add more intent classes to mask unresolved grounding.

### 2. Transfer recombination through ordinary chat

Build a frozen task set that combines independently supported facts/rules and
learned procedures. Vary entities, values, wording, clause order, and operation
order. Include at least two composition shapes, such as proof-based selection
followed by aggregation and a multi-step inference result consumed by a later
operation. Keep examples and labels traceable. Run the same tasks through
ordinary chat, a fresh process, and a copied model where the serialization
path applies. Check outputs with an independent oracle.

**Gate:** held-out requests complete through chat and reload; the independent
checker accepts valid results and rejects tampered or invalid results; missing,
conflicting, incomplete, cyclic, or unsupported inputs do not become confident
positives. Report completion, errors, and abstention. Authored controls alone
do not pass this gate.

### 3. Make reasoning work as a user capability

Measure natural-language routing into direct facts, rule inference, multi-hop
proofs, and reasoning-to-procedure composition. Prioritize recursion depth,
cycle/integrity constraints, conflict handling, and specific missing-premise
follow-through. Verify proofs independently before explaining them. Test
paraphrases and compound requests in the same frozen scorecard so engine
strength is not mistaken for user-facing coverage.

**Gate:** source-backed held-out tasks reach the correct proof path from
ordinary wording; proofs survive independent verification; cycles, explicit
negatives, contradictions, incomplete chains, and search limits are represented
honestly in replies. Do not trade proof validity for coverage.

### 4. Establish source-derived rule transfer

Continue the clause/context-aware candidate learner as a bounded research
track. Freeze its method before evaluation; split by complete document and
publisher; review both proposals and sampled non-proposals. Preserve subject,
role, polarity, conditions, qualifiers, contrast, and separate citations for
context. Keep candidates review-only. Record useful proposals, false
proposals, missed claims, abstentions, review effort, and label provenance.

**Gate:** a new publisher and untouched documents show useful, reviewable
claims without unacceptable boundary errors or review burden; downstream
held-out validation confirms transfer. Candidate yield alone is not a success
measure. If the representation loses claim roles or conditions, redesign that
boundary before scaling ingestion.

### 5. Govern learning from CRMS outputs

Allow a verified composition to create a derived-case proposal with complete
fact, source, rule, proof, and procedure lineage. Keep derived cases distinct
from taught/source-backed knowledge and lower-trust until independently
revalidated. Exercise duplicate suppression, stale lineage, source correction,
dependency invalidation, and store-growth limits. Inject an incorrect
derivation and prove that it cannot validate itself or amplify through reuse.

**Gate:** correcting any dependency identifies and disables every affected
derived result until revalidated; invalid proofs cannot be reused; provenance
and trust remain visible after save/reload; growth follows an explicit policy.
Until then, write-back remains a review-gated proposal.

### 6. Demonstrate generality, then validate the portable model

Choose one bounded task family at a time across coding, math, translation, or
creative work. Reuse the natural-language interface and the same end-to-end
gates: independently held-out requests, output validation, honest abstention,
repair, and recombination with learned knowledge where relevant. Expand only
when a domain clears its gate.

Then copy the SQLite model to a clean location with original source files
unavailable. From the copy alone, query, learn, review, compose, reason,
explain, correct, save/reload, and rerun the shared scorecard. Measure model
size, runtime, compatibility, searchable source text, and survival of
provenance and licensing metadata.

**Gate:** capability survives copy and reload without hidden dependence on
the original files; corrections and evidence remain inspectable; the same
frozen tasks pass. Distribution is the packaged model plus runtime, not a
requirement to ship each original source file separately.

## Operating loop

For every change: reproduce a user-visible failure or name a gate → freeze the
case before tuning → change one responsible seam → run the targeted runtime
case and relevant cross-capability controls → record what passed and what did
not → commit the implementation and update the scorecard/plan. Preserve
counterexamples. Do not add tests or corpus volume without tying them to a
measurable task or safety gate.

At each checkpoint compare CRMS qualitatively with a strong instruction model
on task breadth, paraphrase handling, multi-part completeness, dialogue
continuity, and repair. Use the comparison to find user-visible gaps, not to
claim parity. The project is on track only when held-out users can complete
more of their real tasks without more confident errors, while the evidence and
correction lifecycle remains intact.

## Related plans

- [Detailed focused roadmap](focused_roadmap_to_goal.md)
- [Goal execution plan and project review](goal_execution_plan.md)
- [Current development history](current_development_plan.md)
- [Capability comparison with 70B-class systems](capability_comparison_70b.md)
- [Contextual user intent](design_user_intent_model.md)
- [Dialogue moves](design_dialogue_moves.md)
- [Learning dynamics](design_learning_dynamics.md)
