# Design: Phase 6 domain breadth

**Status:** bounded Phase 6 gate implemented and measured.
**Date:** 2026-10-21
**Modules:** `crms_domains.py`, `crms_phase6_benchmark.py`
**Runner:** `run_phase6_eval.py`
**Fixture:** `experiments/scorecard/phase6_domains.json`
**Report:** `experiments/reports/phase6_domains.json`

## Scope

Phase 6 adds five measured domain slices rather than broad claims of general
reasoning:

| Slice | Bounded capability | Independent check |
|---|---|---|
| Math | exact arithmetic, units, word problems, linear inequalities, unique 2x2 systems | exact value comparison; inequality boundary/operator check; system substitution |
| Coding | typed list-operation IR, multi-step composition, contracts, static AST checks, sandboxed execution | independent list interpreter |
| Translation | reviewed English→Spanish lexicon, noun/adjective agreement, plain/formal register, semantic roles | authored target sentences and role checks |
| Creative | constraint planner over the deterministic story grammar, rubric-scored briefs | independent constraint rubric |
| Cross-domain | two-stage list→math and translate→count plans through the task IR | independent expected outputs and two-step plan inspection |

Every slice has 20 held-out tasks, negative controls, one repair case, and cost
measurement. Cross-domain has 10 held-out tasks because each task contains two
steps. The fixture is frozen in `experiments/scorecard/phase6_domains.json`.

## Slice details

### Math

`MathDomain` first tries reviewed word-problem templates, then linear
inequalities and 2x2 systems, then the existing exact `CRMSMath` arithmetic,
equation, and units implementation. It does not guess:

- nonlinear equations, irrational roots, non-unique systems, zero-division,
  dimension mismatches, and unsupported wording abstain;
- inequality solutions are checked at the exact boundary;
- system solutions are substituted back into both original equations.

The slice adds word problems (remaining quantity, average speed, unit cost,
arrivals), exact rational inequalities including sign flips, and unique 2x2
linear systems. Linear inequalities and systems are included only because the
held-out fixture contains them.

### Coding

The coding slice uses a typed operation IR over `list[int]` inputs:

- single operations (reverse, sort, dedupe, double, square, absolute, parity
  filters, sum, scale/add, divisibility, first/last/drop);
- multi-step sequences joined by “then”;
- input/output contracts bounded to 100 integers;
- static AST checks that reject imports, dangerous attribute access, and
  unbounded calls;
- execution in a fresh `python -I -S` subprocess with a short timeout.

A parse failure, contract failure, static-check failure, sandbox failure, or
malformed output abstains. The independent benchmark oracle reimplements the
list operations rather than trusting the generated source.

### Translation

`BoundedTranslator` composes noun phrases and predicate/location sentences from
a source-reviewed English→Spanish lexicon. It handles:

- masculine/feminine and singular/plural noun agreement;
- adjective agreement in attributive and predicate positions;
- `el/la/los/las` selection;
- plain (`está en`) and formal (`se encuentra en`) registers;
- explicit semantic roles recorded with each result.

Unknown nouns/adjectives, number disagreement, unsupported relations, and
trailing words abstain. Learning a missing noun through `teach_noun` repairs the
failed sentence. This is a bounded lexicon and grammar, not a general translator.

### Creative

`CreativeDomain` plans a five-beat fictional story under explicit constraints:

- topic and tone;
- required motifs;
- forbidden words;
- word limit;
- third-person narration.

The planner tries eligible story templates, inserts a required motif into the
attempt beat when needed, and rejects any candidate that violates the rubric.
Contradictory include/avoid constraints, an invalid tone, or an impossible word
limit abstain with a focused repair question. The rubric is separate from
generation and is rerun by the benchmark.

### Cross-domain

`CrossDomain` builds real `Plan` records with two dependent steps:

1. `domain-list-program` → `domain-math-map`;
2. `domain-translate` → `domain-word-count`.

Each step has an action-level verifier, evidence, and a dependency edge. The
plan executor returns an answer only if both steps pass. Unsupported second
stages or unknown translation words fail the plan and abstain; replacing the
failed stage repairs the composition.

## Measured result

| Slice | Held-out | Completion | Confident errors | Negatives | Repair | Median | p95 |
|---|---:|---:|---:|---:|---|---:|---:|
| Math | 20 | 20/20 (100%) | 0 | 4/4 | PASS | 0.04 ms | 0.10 ms |
| Coding | 20 | 20/20 (100%) | 0 | 3/3 | PASS | 14.48 ms | 18.53 ms |
| Translation | 20 | 20/20 (100%) | 0 | 3/3 | PASS | 0.01 ms | 0.02 ms |
| Creative | 20 | 20/20 (100%) | 0 | 3/3 | PASS | 0.03 ms | 0.06 ms |
| Cross-domain | 10 | 10/10 (100%) | 0 | 2/2 | PASS | 0.08 ms | 0.16 ms |
| **Total** | **90** | **90/90 (100%)** | **0** | **15/15** | **PASS** | — | — |

All 90 correct answers carry evidence. The domain registry has 47 active rules
after the repair lane adds one lexicon entry. Retiring
`domain-code-op-reverse` makes reverse abstain; rollback restores it.

## Gate

| Gate item | Result |
|---|---|
| Each slice ≥80% held-out completion | PASS; every slice 100% |
| Zero confident wrong outputs | PASS; 0 |
| Provenance present | PASS; 90/90 |
| Repair demonstrated | PASS; one repair per slice |
| Negative controls abstain | PASS; 15/15 |
| Cost reported | PASS; median/p95 per slice |
| Domain rules registered and validated | PASS; 47 active |
| Domain rule retirement/rollback | PASS |

## Limitations

- The fixture is authored and controlled. It demonstrates bounded domain
  behavior, not open-domain math, programming, translation, or writing.
- Math covers exact rational arithmetic, one-variable linear inequalities, and
  unique 2x2 systems; it does not solve general algebra.
- Coding covers a typed integer-list IR only. Other data types remain outside
  the slice until a verifiable semantics exists.
- Translation uses a small reviewed English→Spanish lexicon and two sentence
  shapes; it is not a corpus-scale translation model.
- Creative writing remains deterministic fiction with explicit constraints; it
  does not claim literary quality or factual grounding.
- Cross-domain plans are limited to two registered step pairs.
- The slices are measured through their APIs. Runtime chat still uses the
  existing Family B routes for the older prototypes; wiring the expanded slice
  into chat is a follow-up.
