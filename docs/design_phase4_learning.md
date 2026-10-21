# Design: verified work, corrections, and consolidation (Phase 4)

**Status:** bounded Phase 4 gate implemented and measured.
**Date:** 2026-10-21
**Modules:** `crms_dependency.py`, `crms_verified_work.py`,
`crms_corrections.py`, `crms_active_learning.py`,
`crms_consolidation.py`, `crms_phase4_benchmark.py`
**Runner:** `run_phase4_eval.py`
**Fixture:** `experiments/scorecard/phase4_families.json`
**Report:** `experiments/reports/phase4_learning.json`

## Principle

A completed plan is evidence. It is not permission.

The Phase 4 lane has five rules:

1. sources, facts, schemas, procedures, rules, plans, and derived artifacts live
   in one reverse dependency index;
2. trust is ordered `taught` > `source-reviewed` > `derived`, and taught
   evidence wins a conflict;
3. a correction contests the affected artifact, every dependent artifact, and
   every dependent governed rule;
4. completed work is proposed with lineage, then independently replayed; a
   failed replay cannot validate it;
5. consolidation only merges equivalent records, reports conflicts it cannot
   resolve, and retires old active rules with zero measured utility.

## Dependency index

`DependencyIndex` is a SQLite-backed graph with node kinds `source`, `fact`,
`schema`, `procedure`, `rule`, `derived`, `plan`, `task`, `work`, and
`correction`. Edges are directional:

- `supports`: a source supports a fact;
- `derived_from`: an artifact was derived from another artifact;
- `uses`, `contains`, `revises`, `merged_from`: lifecycle lineage.

`retract_source` is support-aware. Removing one source from a fact with another
active source retains the fact and its dependents. Removing the last support
contests the fact, its derived/schema artifacts, and their rules. Rules are also
contested in `RuleRegistry`, so rule-to-rule dependents cannot keep being used.

## Trust and correction

`resolve_trust_conflict` returns a selected claim only when the highest trust
level has one winner. Same-level conflicts remain ambiguous. A taught claim is
authoritative against source-reviewed and derived claims; source-reviewed beats
derived. The caller contests losers through the same registry transition used by
ordinary correction propagation.

The correction lane exercises source → fact → schema → derived artifact →
rule → dependent rule. The gate requires every expected node to become
`contested`, while an unrelated source-supported fact stays active.

## Verified work

`VerifiedWork` records the request, goal, plan id, steps, output, checks, and
provenance. `learn_from_verified_work`:

1. creates a `work` node and plan-step lineage;
2. proposes a `task-plan` or `procedure` rule with `trust="derived"`;
3. calls a caller-supplied independent replay verifier;
4. records the validation result and activates only when `activate=True` after
   an explicit review call.

An injected output of `[999]` where the independent oracle says `[6]` leaves the
new rule `proposed`. Replacing an active rule with the bad revision moves it to
`contested`; the dependency node follows.

## Corrections and failures

`learn_from_correction` records a scoped negative example with the excluded
value, reason, source, and target rule. It proposes a revision rule with the
correction as a dependency; it never activates it. `learn_from_failure` records
the failed request/action/reason as a scoped negative. If a target rule is
identified, it proposes a failure revision; otherwise it records only the
negative.

## Active learning

`ActiveLearner` holds a finite hypothesis set and chooses the example that
maximally partitions the remaining hypotheses. One answer records supervision,
narrows the set, and can propose the surviving rule. It does not activate it.
An uninformative example is never asked.

## Consolidation

`consolidate` performs:

- exact duplicate merge by family, statement, and scope;
- explicit compatible merge by family, scope, and `merge_key`;
- cross-mechanism conflict audit by `conflict_key`;
- zero-utility retirement only for active rules older than the measured window
  with no recorded applications.

The survivor keeps the union of provenance, moves dependents, and records
`merged_from`. Conflicts are reported and left active for review.

## Scoped auto-accept

The registry policy remains off by default. With the policy enabled and
independent validation (at least two sources and three cases), only lexical,
morphology, and procedure families can activate with `scoped-auto`. Fact-frame
and derived rules are refused. Phase 4 does not turn the policy on for chat.

## Compounding benchmark

The frozen fixture has three training families (`sum`, `double`, `reverse`) and
one disjoint family (`keep-odd`). One verified work record learns the generic
select-then-transform plan rule. The three rounds then teach the procedures.

| Round | Learned | Held-out completion | Confident errors | Disjoint completion |
|---:|---|---:|---:|---:|
| 0 | none | 0/12 (0%) | 0 | 0/4 |
| 1 | sum | 4/12 (33%) | 0 | 0/4 |
| 2 | sum, double | 8/12 (67%) | 0 | 0/4 |
| 3 | sum, double, reverse | 12/12 (100%) | 0 | 0/4 |

The plan skeleton transfers from the sum family to the double family once the
double procedure is independently learned (`0/4` before, `4/4` after). The
disjoint family stays at `0/4` and is reported as an explicit plateau: there is
no verified procedure or rule for it, so the system abstains instead of
inventing transfer. Every task is checked by an independent oracle; no answer is
counted as correct merely because the model produced it.

## Current gate result

| Gate item | Result |
|---|---|
| Injected bad derivation cannot validate its rule | PASS; bad revision is `contested` |
| Correction propagation | 100%; 5/5 expected nodes contested |
| Compounding | gain 0% → 100%, zero confident errors, plateau diagnosed |
| Provenance and trust survive save/reload/model copy | PASS; skeleton stays active/derived |
| Storage growth bounded | PASS; 250/250 node cap enforced |
| Taught evidence authoritative | PASS |
| Scoped auto-accept off by default, high-risk families refused | PASS |

## Limitations

- The compounding fixture is authored and controlled; it demonstrates the
  learning mechanics, not broad natural-language learning.
- The dependency graph covers the fixture's source/fact/schema/procedure/rule
  chain; it is not yet the only path used by every chat route.
- "Model copy" means copying the model memory, governed registry, and
  dependency database; deployment packaging and key rotation are later work.
- Active learning uses a finite, deterministic hypothesis set. It does not claim
  a general question-selection policy over open-ended rules.
- The zero-utility window is measured on fixture timestamps; production windows
  need real usage telemetry.
- Scoped auto-accept is tested as a policy lane, not enabled for runtime chat.
