# Design: language breadth and construction learning (Phase 5)

**Status:** bounded Phase 5 gate implemented and measured.
**Date:** 2026-10-21
**Modules:** `crms_constructions.py`, `crms_morphology.py`,
`crms_construction_ranker.py`, `crms_phase5_benchmark.py`
**Runner:** `run_phase5_eval.py`
**Fixture:** `experiments/scorecard/phase5_constructions.json`
**Report:** `experiments/reports/phase5_constructions.json`

## Principle

A construction is a learned production, not a hand-written request regex.

Teacher-marked examples are aligned by their literal/slot structure. Literal
positions that vary across aligned examples become **token classes**; repeated
positions stay literal. Slots carry typed meaning (`values`, `claim`,
`condition`, `manner`, `entity`, `number`, `predicate`, `procedure`). The
induced production keeps every example as lineage and is proposed into the
governed rule registry. Matching is allowed only while that registry rule is
active.

The Phase 5 fixture covers ten composition shapes: direct, wh, relative,
coordination, conditional, passive, fronted PP, manner, comparative, and
purpose. This is a bounded construction learner, not a complete English grammar.

## Learned production

`ConstructionStore` saves examples, not compiled patterns. `derived_constructions`
re-derives productions deterministically:

1. group examples by construction id, goal, operation, and slot/literal shape;
2. for each shape, replace varying literal positions with a `ClassPart` whose
   members are the observed alternatives;
3. keep the example lineage on each pattern;
4. license only when at least two examples align and at least one token class is
   learned.

`ConstructionGrammar` matches escaped literals, learned classes, and typed
slots. Singular/plural forms come from `Morphology`; a class member `value`
matches `values`, but an irregular pair such as `child`/`children` is usable
only after that lexical pair has been observed. An unmatched or ambiguous
production abstains.

## Registry lifecycle

Every construction is a `construction` family rule. Registration records the
scope, patterns, token classes, examples, and provenance. Validation requires:

- the production replays exactly from its examples;
- distinct example sources;
- at least one learned token class;
- held-out cases supplied by the independent benchmark oracle.

The benchmark registers ten rules with **20 held-out cases and 20 independent
sources each**. Retiring a rule removes it from the grammar immediately;
rollback restores it. `ConstructionGrammar.dangling_references()` remains empty
because the grammar intersects licensed store rules with active registry ids.

A new construction can enter through the same path. The `polite-reverse` lane
licenses, activates, matches, retires, and rolls back a previously unseen
construction without a dangling reference.

## Morphology

`Morphology` separately licenses regular plural expansion and stores irregular
forms as lexical evidence pairs. It will not generate `children` from `child`
until that pair has been observed. The morphology rules are ordinary governed
rules; retiring the regular plural rule removes expansion.

## Propose-only ranker

`ConstructionRanker` orders already-licensed matches and returns at most a fixed
number of candidates with a bounded feature list. It never selects the answer,
filters the parser result, or activates a rule. The benchmark compares matches
with and without the ranker and requires the parser status to be unchanged.

## Active construction learning

When a request fails, `propose_construction_gap` finds the closest active
construction, identifies the first missing token-class member (or reports that a
new construction is needed), and asks for one marked example. The answer is
added to the store, the production is re-derived, and the registry rule is
revised and revalidated. In the measured lane, the missing member `enumerate`
is learned from one example and the original query then matches.

## Paraphrase benchmark

The frozen fixture has 60 teacher-marked training examples and 200 held-out
tasks:

- **60 controls** reuse a training wording with new values/claims; an exact
  hand-coded frame should still match these.
- **140 reworded tasks** recombine learned token-class alternatives in sequences
  that were never a training template.

Each output is checked by an independent operation oracle. The exact-frame
baseline is licensed from the same marked examples. It is not allowed to inspect
the learned classes.

| System | Correct | Coverage | Confident errors |
|---|---:|---:|---:|
| Exact hand-coded frames | 60/200 | 30% | 0 |
| Learned constructions | 200/200 | 100% | 0 |

On the split:

| Split | Tasks | Exact frames | Learned |
|---|---:|---:|---:|
| Same wording control | 60 | 60 | 60 |
| Reworded paraphrase | 140 | 0 | 140 |

The learned construction route therefore more than doubles coverage
(30% → 100%) with no increase in confident wrong answers. The same utterance
also produces different outputs under different selection contexts, while the
learned slots stay identical.

## Current gate result

| Gate item | Result |
|---|---|
| Paraphrase coverage at least doubles baseline | PASS; 30% → 100% |
| No wrong-answer increase | PASS; 0 → 0 |
| Learned constructions beat hand-coded frames | PASS; 200 vs 60 |
| Unlicensed productions abstain | PASS; unlicensed, malformed, single-example, and ambiguous cases |
| New constructions enter through registry and retire cleanly | PASS; no dangling references, rollback restores |
| Every construction has scope and holdout evidence | PASS; 20 cases, 20 sources each |
| Morphology expansion; irregular forms evidence-only | PASS |
| Propose-only ranker is bounded and bypassable | PASS |

## Limitations

- The fixture is authored and controlled. It demonstrates construction
  induction and held-out recombination, not open-domain English parsing.
- The ten shapes are a bounded inventory. Coordination and conditionals are
  represented as typed multi-clause patterns, not a full compositional parser.
- Slot semantics are task-specific (`values`, `claim`, etc.) and are checked by
  a deterministic operation oracle; this is not a general semantic parser.
- The construction route is measured as a lane. Runtime chat still uses the
  request-frame route; wiring constructions into chat is a follow-up.
- The ranker is a deterministic candidate proposer, not a trained intent model.
- Dialogue moves remain experimental and are not promoted by this lane.
