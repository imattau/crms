# Focused plan from current CRMS to its goal

**Reviewed:** 2026-10-20 (current runtime evidence through `v1_539`; recent
dialogue-context commits through `d1576a0`)
**Status:** active plan; broad capability is not yet demonstrated.

## Destination

Build a lightweight, distributable language system that handles a broad range
of ordinary requests through natural language, carries context across turns,
combines knowledge, learned procedures and reasoning, and improves from use.
Outputs should remain useful, inspectable, correctable, and clear about what is
known, inferred, uncertain, or unsupported. Coding, math, translation,
creative work, and other domains should share the interface. Strong 70B-class
models are a qualitative reference for breadth and interaction, not a parity
claim or a required live comparator.

## Overall review

CRMS is still aimed at the right goal. Its distinguishing foundations are
searchable source text, provenance-bearing knowledge and procedures,
review-gated learning, bounded proof-checked reasoning, dialogue state, and a
portable SQLite model. Recent work also shows controlled source-grounded
calculations, procedure composition, cross-source relation transfer, and
chat-level settlement comparisons. The recent dialogue-context changes keep
comparison entities available for short follow-ups and preserve useful context
from long preference replies.

The `v1_539` runtime increment now realizes one exact subject-gap question
from a cited passive clause into an active sentence, with wrong-entity,
wrong-predicate, polarity, example, and conflicting-agent controls. This
improves one user-facing path but does not change the main assessment: broad
held-out recombination and reasoning through normal chat remain the next
capability gate.

The central gap is transfer through the complete user path. Most positive
results still use small or synthetic fixtures, prepared labels, hand-mapped
source facts, tightly scoped question frames, or experiment orchestration.
They establish useful components and safety controls, not broad independent
task competence. Dialogue has many targeted regressions but limited transfer
evidence; the source-derived rule learner still needs independent quality and
transfer evaluation; derived write-back is not ready for routine reuse.

The project is architecturally on track, but the capability goal is not yet on
track to claim. Progress should be measured by held-out user-task completion
with controlled errors, not by code size, corpus size, feature count, or the
number of passing authored examples.

## Priority order

### 1. Freeze and run one complete chat scorecard

Create a compact, versioned set of complete user tasks before tuning. Include
ordinary questions, paraphrases, multi-part requests, source-only answers,
reasoning followed by a procedure, topic changes, pronouns, corrections,
clarification, history, `why?`, ordinal references, and save/reload. Include
negative, conflicting, incomplete, and unsupported cases. Use independent
expected outcomes or checkers where possible, and label authored, Codex-labeled,
hand-coded, and independently checked parts explicitly.

Replay known failures against a clean current process before calling them
open. Keep the Eiffel Tower/Colosseum topic switch, the Marie Curie/Einstein
retrieval confusion, omitted parts of compound questions, and source-only
context continuity as permanent controls. Preserve the user-modified
`experiments/reports/large_corpus_chat_audit.json`; use a copy or another
output path for new runs.

**Gate:** clean-process results report completion, correctness, omissions,
wrong referents, clarification, abstention, evidence/proof validity, repair,
latency, and reload separately. No fixed control yields a confident wrong
referent or unsupported answer. Ambiguous context clarifies or abstains.

### 2. Make recombination plus reasoning work on held-out requests

This is the main capability milestone. Use reviewed components already in the
system and ask new, ordinary-language tasks that require multiple steps:
retrieve distinct evidence, derive a result with a proof or checker, then use
that result in a separately learned procedure. Vary wording, entities, values,
evidence order/layout, and operation order. Cover at least two distinct task
families so the result cannot be explained by one finite-list route.

Run each task through normal chat and a fresh process. Independently check the
result; test missing premises, explicit negatives, contradictions, cycles,
unsupported operations, incomplete search, and partial multi-part requests.
Make the system expose which components were taught, hand-coded, or learned,
and ensure the experiment harness is not coordinating the answer on behalf of
chat.

**Gate:** frozen held-out tasks show useful completion beyond the explicit
baseline, with no confident invalid result. Independent checks accept valid
outputs and reject tampered ones. Report task completion, wrong answers,
omissions, abstention, proof/evidence validity, repair, and cost separately.

### 3. Keep dialogue and contextual intent as a continuous release gate

Evaluate full conversations, not only resolver calls or isolated labels.
Vary entity classes, paragraph structure, topic distance, interruptions,
source-only answers, same utterances in different contexts, repairs, and
reload. Treat user intent as a contextual, revisable hypothesis over the
utterance and explicit discourse state. It can route, clarify, or repair; it
cannot add facts or authorize unsupported actions. Keep dialogue-move learning
as a research comparison against the explicit baseline, with source and policy
provenance for labels.

**Gate:** unseen conversations improve task completion without more wrong
bindings, stale explanations, unsupported claims, or inappropriate moves.
Intent-label agreement alone does not pass. Every chat-facing change reruns
the fixed dialogue controls.

### 4. Continue source-derived rule learning as a bounded research lane

Freeze the candidate method, then evaluate on untouched complete source units
and a new publisher. Review both proposals and sampled non-proposals. Measure
useful yield, false proposals, missed claims, abstention, reviewer effort, and
source diversity. Preserve roles, conditions, scope, polarity, contrast,
qualifiers, and separate citations for claim and context. Candidate rules stay
review-only and cannot validate themselves. This lane can feed recombination,
but must not block work with already reviewed components.

**Gate:** a source-disjoint evaluation finds useful, reviewable rules with
measured error and review burden; a yield increase alone is insufficient.

### 5. Enable governed self-learning only after composition passes

Let independently verified outputs create lineage-bearing proposals, not
immediately trusted facts. Keep derived knowledge separate from taught and
source-backed material and lower-trust until revalidated. Test correction and
invalidation through the full dependency graph, conflicts, duplicates,
retrieval weighting, restart, bounded storage growth, and corrupted lineage.
A derivation must never validate the rule that produced it.

**Gate:** correcting any source or rule disables or revalidates all dependent
derivations; invalid lineage cannot support an answer; provenance survives
copy and reload. Until then, write-back remains review-gated.

### 6. Expand task breadth from measured failures

Add coding, math, translation, and creative work one bounded task slice at a
time through the same natural-language interface. Choose the next slice from
the scorecard, define held-out requests and negative cases before
implementation, and specify an independent checker or quality rubric,
provenance policy, and repair behavior. Validate domains separately before
testing cross-domain composition. For creative work, score constraint
following and coherence separately from factual grounding.

**Gate:** each slice demonstrates useful held-out completion and honest
limits, with correctness or quality, omissions, unsupported outputs,
provenance, repair, and cost reported. A domain label or one demonstration is
not domain competence.

### 7. Validate SQLite as the complete distributable model

Once the record and correction lifecycles are stable, copy the model to a
clean location where original documents are unavailable. From the copy alone,
exercise search, answer, learn/review, recombine, reason, explain, correct,
save/reload, and the shared scorecard. Confirm searchable source text,
knowledge, rules/procedures, citations, source/license metadata, and correction
lineage survive. Record size, compatibility, migration, and runtime.

**Gate:** tested behavior depends only on the copied model and runtime, with
evidence and corrections inspectable after reload.

## Immediate execution card

1. Freeze the end-to-end scorecard and expected outcomes; do not tune against
   its held-out portion.
2. Run it on the current checkout in a clean process, preserving all existing
   user-owned and untracked state. Replay reported failures before deciding
   what still needs implementation.
3. Use the result to select one end-to-end recombination/reasoning task family
   and one independent second family. Build a normal-chat path and checker;
   add only the smallest missing capability needed to pass the gate.
4. Run the dialogue packet and relevant engine/procedure regressions after
   each chat-facing change. Record both positive results and failures.
5. Update the benchmark and this plan with measured outcomes, then commit only
   the intended project files. Keep source-rule transfer running separately;
   defer routine derived-case reuse until correction propagation passes.

## Progress rule

For every cycle: reproduce a user-visible failure or name a gate; freeze the
case; change one responsible seam; validate in runtime; run relevant
cross-capability controls; record outcomes and limitations; update the plan;
commit only intended files. At each gate, compare qualitatively with a strong
70B-class assistant on breadth, paraphrase, compound-task completion,
continuity, and repair. Use that comparison to find gaps, never as a substitute
for independent correctness or a parity claim.
