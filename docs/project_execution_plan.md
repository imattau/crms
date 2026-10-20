# CRMS project execution plan

**Reviewed:** 2026-10-20  
**Status:** working plan; the project goal is not yet achieved.

## Destination

CRMS should accept broad natural-language requests, continue across turns,
combine knowledge and learned procedures, reason over evidence, and improve
from use. Its knowledge and outputs should remain inspectable, correctable,
and clear about evidence, inference, uncertainty, and unsupported claims. A
portable SQLite model should carry the learned material needed to use the
system without the original source files. Coding, math, translation, creative
work, and other domains should use the same natural-language interface.

Strong 70B-class assistants are a qualitative comparison for breadth,
interaction, follow-up, and repair. They are not an architectural target or a
parity claim. CRMS progress is established by held-out task completion,
independent checking, and honest failure behavior.

## Current position

CRMS has real foundations: source-text retrieval, cited knowledge and rules,
review-gated learning, bounded proof-checked reasoning, contextual dialogue
state, some learned-procedure recombination, and a SQLite model format. Recent
work adds source-cited exact calculations and fresh-process controls.

The central gap is **generalization across the user's complete path**. Many
successful demonstrations still use small authored fixtures, prepared labels,
explicitly taught components, or constrained request frames. They show that
the mechanisms can work together under controlled conditions; they do not yet
show reliable transfer to independently authored tasks or broad everyday
language. The source-derived rule learner has concrete role, condition, and
boundary failures. Dialogue has useful targeted repairs, but no broad transfer
result. Derived write-back is not ready for routine reuse.

The project is still pointed toward its goal, but broad capability is not yet
on track to claim: the next milestone must turn controlled composition into
measured held-out task completion. See the [detailed roadmap](focused_roadmap_to_goal.md)
and [capability comparison](capability_comparison_70b.md) for experiment-level
evidence and caveats.

## Critical path

| Stage | Work and deliverable | Advance gate |
| --- | --- | --- |
| **1. Freeze the evaluation** | Build a small, versioned packet of complete chat tasks. Include independently authored requests, varied wording and evidence layout, multi-part requests, context changes, and known dialogue failures. Record all teaching, hand-coding, and labels. Reserve held-out sources/tasks before tuning. | A clean-process baseline reports task completion, correctness, omissions, abstention, wrong referents, evidence/proof validity, repair, latency, and reload separately. Ambiguous dialogue clarifies or abstains; no confident unsupported answer. |
| **2. Transfer recombination through ordinary chat** | Use already reviewed components to combine source evidence, learned rules/procedures, and reasoning on unseen task combinations. Test at least two task families, not just another variation of the current finite-list task. Vary entities, values, wording, operation order, and evidence arrangement. Include missing premises, conflict, cycles, unsupported steps, partial requests, and bounded-search cases. Verify outputs independently and test a copied model. | Held-out users complete more tasks than the explicit baseline; independent checks accept valid results and reject tampered/invalid ones; incomplete, conflicting, and unsupported cases do not become confident positives. Chat coordinates the work without a test harness doing the reasoning. |
| **3. Make dialogue reliable alongside every chat milestone** | Maintain complete multi-turn transcripts for topic changes, pronouns, source-only continuity, failed turns, `why?`, history, ordinal references, clarification, correction, and save/reload. Measure contextual intent by task outcome; preserve intent as revisable context, never as factual evidence or authorization. Keep dialogue-move induction as a scoped research pilot. | Frozen unseen conversations improve task completion without increasing confident wrong referents, stale context, unsupported claims, or inappropriate moves. If a learned dialogue model does not outperform the explicit baseline, retain the simpler route. |
| **4. Transfer source-derived rules as a separate research lane** | Redesign source claim assembly to preserve subject/role, condition, polarity, scope, and context citations. Freeze the method and evaluate on untouched source units from a publisher not used in development. Review both proposals and non-proposals; keep all candidates review-only. | Independent review finds useful claims with acceptable false proposals, missed claims, abstention, and review burden. A yield increase alone does not pass. This lane must not block recombination using reviewed components. |
| **5. Close the governed self-learning loop** | After recombination passes, allow verified outputs to create lineage-bearing proposals. Test independent revalidation, source/rule correction, dependent invalidation, duplicate handling, trust weights, conflicts, restart, and bounded store growth. Inject a bad derivation and ensure it cannot validate or reinforce itself. | Every correction invalidates or revalidates all affected descendants; stale or conflicted lineage abstains; reuse and growth are measured. Keep write-back review-gated until this gate passes. |
| **6. Widen domain breadth one slice at a time** | Use measured failures to choose bounded coding, math, translation, and creative tasks. Define held-out requests, negative controls, an independent checker or rubric, and revision behavior before building each slice. Test each domain alone, then test cross-domain recombination. | Each slice shows useful held-out completion, independent correctness/quality checks, traceable inputs where applicable, honest limits, and repair. A domain label or isolated success is not evidence of domain competence. |
| **7. Validate the distributable model as the product** | Copy the SQLite model to a clean environment with original documents unavailable. Exercise search, answer, learn/review, recombine, reason, explain, correct, and reload from the copy. Check embedded source text, citations, rules/procedures, correction lineage, licensing metadata, size, and migration. | The copied model and runtime reproduce the shared scorecard without source files; learned state and corrections remain inspectable after reload. |

Stages 1 and 3 are continuous evaluation and safety work. Stages 2 and 4 can
proceed in parallel after the evaluation packet is frozen. Stage 5 depends on
stage 2. Stage 6 expands from measured gaps rather than running as a broad,
unscored feature program. Stage 7 validates the stable learning lifecycle.

## Immediate next cycle

1. Freeze a compact task packet from the user-reported natural-language and
   dialogue failures, current passing regressions, and newly authored held-out
   tasks. Keep the answer key/checker separate from the implementation fixtures.
2. Run the packet in a fresh process against the current model and record the
   baseline. Recheck historical failures before deciding they remain open.
3. Extend recombination only where this packet demonstrates a missing user
   capability. Require an ordinary-chat path, source-disjoint or task-disjoint
   holdout, independent output checks, negative cases, and a copied-model run.
4. Keep the source-rule transfer experiment isolated and review-gated. Do not
   use its candidate volume as a proxy for useful learning.
5. After the recombination gate passes, exercise derived proposals and
   correction propagation before allowing normal retrieval to reuse them.

## Current baseline check (2026-10-20)

On the current checkout, the following runtime controls passed:

- `v1_427`: 30-turn dialogue transcript, including the Colosseum topic switch,
  history, stale explanation, clarification, and persistence.
- `v1_501` and `v1_502`: learned sequence and proof-selected numeric
  aggregation in fresh chat, including unknown/conflict controls.
- `v1_514` and `v1_516`: reviewed relation wording plus type reasoning across
  held-out routes, including unsupported-type abstention.
- `v1_533`: cited dated percentage-point comparison, independent decimal
  check, and direction, unsupported-measure, and conflicting-source controls.
- `v1_534`: new operation phrases compose in both orders after explicit
  supervision; unknown and unlicensed operations still abstain.
- `v1_535`: four new question frames retrieve and calculate one
  source-backed percentage-point comparison; unsupported measures/labels and
  a contradictory requested direction are controlled.

These are component/regression passes, not an independent user-task score.
Most use authored controls; `v1_533` uses two documents from one PMC
collection and remains narrow.

A focused request probe found that alternate operation wording was not
recognized. `v1_534` now demonstrates one bounded path through this gap:
explicitly teach two operation phrases, learn `and` and `then` sequence
connectives from separate examples, and combine the held-out phrases and
orders in fresh chat. Operation order changes the output; evidence, operation
labels, and connective provenance remain visible. Unknown values and
unlicensed operations/connectives abstain, and the copied SQLite model
reproduces the result. This is controlled transfer over supervised phrases
and a synthetic proof graph, not broad language transfer. `v1_535` adds a
second, non-list task family using real indexed article text and expands one
source-grounded math route from one question frame to four. It still tests one
sentence and one condition pair from one PMC collection; independent
publisher and user-task transfer remain unproven. The next gate is a frozen
multi-source packet with independently authored tasks spanning recombination,
reasoning, and source-grounded math. Measure useful transfer, wrong answers,
abstention, and teacher burden before widening phrase coverage.

The current experiments already demonstrate controlled reasoning-to-math,
typed relation/paraphrase recombination, learned sequence operations, and
targeted dialogue repairs. Preserve them as regression controls; do not expand
their fixture grids unless that adds a new independent task family or tests a
specific observed failure. Relation integrity checks and cycle handling
already have regression coverage, so they are controls rather than new work.

## Progress rules

- Freeze evaluation material before tuning; split by source, publisher, task,
  or whole conversation, as appropriate.
- Report correctness, coverage, abstention, omissions, evidence/proof validity,
  repair, latency, and storage separately. Do not merge unlike experiments
  into one accuracy score.
- Mark synthetic fixtures, human/LLM labels, hand-coded routes, and independent
  checks explicitly. A Codex label is supervision, not validation.
- Preserve failures as controls. Reproduce first, change the smallest seam,
  rerun focused and cross-domain checks, update evidence, then commit.
- Do not count corpus size, feature count, retrieval hits, or demonstrations as
  progress without held-out task improvement.
- Review the qualitative 70B-class comparison after each gate for breadth,
  paraphrase, compound-task completion, continuity, and repair. Do not infer
  parity from component tests.

## Evidence to consult

- [Focused roadmap and experiment history](focused_roadmap_to_goal.md)
- [Capability comparison with 70B-class assistants](capability_comparison_70b.md)
- [Benchmark baselines](benchmark_baselines.md)
- [Dialogue and contextual intent model](design_user_intent_model.md)
- [Learning dynamics and derived knowledge](design_learning_dynamics.md)
- [Evidence independence and transfer](design_evidence_independence_and_transfer.md)
- [Dialogue move research](design_dialogue_moves.md)
