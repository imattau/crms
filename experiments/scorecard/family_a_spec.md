# Family A specification: verified selection → learned procedure

**Status:** frozen design for the Phase 2 recombination milestone. The typed
actions execute through the plan path and chat uses it for the explicit
verified-filter frame. Four scorecard tasks cover filter+sum, reload, unknown
values, and an untaught procedure (`experiments/scorecard/family_a.jsonl`);
the remaining wording variations and controls await learned request frames.
**Date:** 2026-10-21
**Provenance:** authored specification. Fixtures, expected outputs, and the
oracle are defined before implementation and must not be tuned to the planner.

## Shape

A request supplies a finite integer list, a relation with explicit positive and
negative evidence, and a learned list procedure. The system must:

1. select the values with a complete verified positive relation and no explicit
   negative evidence;
2. apply the learned procedure to the selected list;
3. report the result with the proof and procedure evidence.

The harness supplies the fact fixture, the teaching examples, the request
wording, and an independent oracle. It must not select values, order steps, or
compose the answer.

## Fixture

Facts (each with a distinct source label):

```
board  approved  3   source:minutes-1
board  approved  8   source:minutes-2
board  approved  5   source:minutes-3
board  approved  11  source:minutes-4   (explicit negative fact)
board  approved  -2  source:minutes-5   (explicit negative fact)
```

Learned procedures, each taught from at least two varied input/output examples
through `CRMSModel`:

| Instruction | Behaviour |
|---|---|
| `sum every value` | `[a, b, ...] -> [a + b + ...]` |
| `double every value` | `[a, b, ...] -> [2a, 2b, ...]` |
| `reverse the list` | `[a, b, ...] -> [..., b, a]` |
| `keep odd values` | keep values not divisible by two |
| `add 1 to every value` | `[a, b, ...] -> [a+1, b+1, ...]` |

## Positive tasks

Expected output is the transformed list or scalar. Every answer must cite the
fact sources used for selection and the procedure evidence.

| # | Request | Expected |
|---|---|---|
| A1 | Which values in `[-2, 3, 8, 5, 11]` are approved, and what do they sum to? | `16` |
| A2 | From `[5, -2, 11, 8, 3]`, keep the approved values, then double every value. | `[6, 16, 10]` |
| A3 | Of `[3, 8, 5]`, which are approved? Reverse the result. | `[5, 8, 3]` |
| A4 | Filter `[-2, 3, 8, 5, 11]` to approved values, then keep only the odd values. | `[3, 5]` |
| A5 | Take the values in `[8, 3, 5]` that are approved, sum them, then add 1 to every value. | `[17]` |
| A6 | Which of `[11, 5, 8, -2, 3]` were approved? Add them up. | `16` |
| A7 | From `[3, 8]`, keep the approved values and reverse the list. | `[8, 3]` |
| A8 | Use only values with a positive approval proof: `[3, 11, 8]`; double the approved values. | `[6, 16]` |
| A9 | Which approved values in `[5, 3]` sum to what? Show the supporting sources. | `8` plus two citations |
| A10 | Repeat A1 in a fresh process after save/reload. | `16` |

Wording varies deliberately: "which values", "from", "of", "keep", "filter",
"add them up", "sum", "double", "reverse". A plan may not depend on one fixed
phrase.

## Negative controls

| # | Case | Required outcome |
|---|---|---|
| N1 | Unknown relation: "Which values are certified?" | abstain; no guessed values |
| N2 | Unknown value: `[3, 99]` with only 3 approved | select 3; 99 remains unknown, not rejected |
| N3 | Both positive and negative evidence for 8 | ambiguous; do not choose |
| N4 | Procedure not taught: "cube every value" | clarify; ask for examples |
| N5 | Procedure outside the grammar: "sort by digit sum" | unsupported |
| N6 | Missing output request: "Do the approval thing" | clarify; do not execute a default |
| N7 | Tampered step result: procedure output altered after execution | verification failure; no answer |
| N8 | Source retracted after the proof was built | revalidate; abstain if no support remains |

Explicit negative evidence excludes a value. Absence of positive evidence is
unknown, not negative.

## Independent oracle

The oracle is a standalone function over the fixture, not the planner:

```python
def expected(values, facts, procedure, negatives):
    selected = [
        value for value in values
        if ("board", "approved", value) in facts
        and ("board", "approved", value) not in negatives
    ]
    return apply_procedure(procedure, selected)
```

`apply_procedure` is the experiment's independent implementation of the taught
procedure, checked against `CRMSModel` on the teaching examples. The oracle
checks outputs, not prose.

## Evidence requirements

- Selection steps carry `EvidenceRef(kind="fact", ref=..., source=...)` and
  `EvidenceRef(kind="proof", ref=...)`.
- Procedure steps carry `EvidenceRef(kind="procedure", ref=...)` plus the
  teaching examples.
- The answer renders the selected values, the procedure, and each source.
- Derived values are not written into the fact store.

## Gate

Through ordinary chat and a fresh reload:

- ≥8/10 positive tasks complete with the expected value;
- every cited source resolves to the fixture sentence or fact;
- N1–N8 behave as specified, with zero confident wrong answers;
- the harness does not choose evidence or order steps;
- the plan artifact id is stable for the same request and changes when the
  request or steps change.

## Open issues

- Whether "add 1 to every value" after a scalar sum should be representable as
  a list of one value or a scalar step. Default: the procedure returns a
  singleton list; the plan declares the output type explicitly.
- Whether unknown values in the input list are ignored or make the request
  ambiguous. Default: ignore values with no fact, but report them as unknown;
  do not treat them as rejected.
- Whether proof and procedure evidence may be combined into one check.
  Default: separate step checks plus one plan-level oracle.
