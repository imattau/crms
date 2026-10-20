# Family B specification: retrieval → reasoning → domain action

**Status:** implemented and measured through ordinary chat. Thirty scenario
tasks plus six negative controls are frozen in
`experiments/scorecard/family_b.jsonl`.
**Date:** 2026-10-21
**Provenance:** authored specification. Fixtures, expected outputs, and the
oracle class are explicit; the harness does not choose evidence or steps.

## Shape

Family B exercises the same typed planner and learned request-frame router as
Family A, but the bound goal selects a domain action:

1. retrieve a source and realize a cited answer;
2. or resolve exact arithmetic/unit evidence;
3. or apply a learned translation frame;
4. or generate a bounded Python artifact from committed learned rules;
5. or compose a deterministic fictional story.

Every plan step carries an independent verifier. Research answers encounter two
steps (`answer-research` then `verify-citation`); the other domains use one
domain action with a replay or parity check.

## Learned goals

The request-frame store licenses these goals from two varied, grounded examples
each:

| Goal | Example wording | Action |
|---|---|---|
| `research-answer` | Who created Python? | retrieve + realize + re-resolve citation |
| `math-compute` | Compute 4 plus 5. | exact arithmetic |
| `unit-convert` | How many metres are in 3 kilometres? | exact learned unit ratio |
| `translate` | Translate Hello, Rowan into French. | learned translation frame |
| `generate-code` | Write Python code that reverse the list. | bounded learned code generation |
| `write-story` | Write a short story about Python. | deterministic fictional story |

Unknown wording does not match a frame and falls to the ordinary chat routes or
abstains. A matching frame whose action fails never falls through to a second
composition path.

## Positive coverage

| Domain | Tasks | Variation |
|---|---:|---|
| Research | 8 | created/wrote relations, entities and citations |
| Math | 6 | plus, times, minus, division, alternate wording |
| Unit conversion | 6 | length, mass, time, volume, reverse direction |
| Translation | 4 | two languages, two held-out names |
| Code generation | 3 | reverse, double, add |
| Writing | 3 | three topics and two request frames |

Every answer must also print a `Plan plan-…` line naming the steps, statuses,
checks, and evidence references. `why?` expands the plan, each step's evidence,
and the verifier outcome.

## Negative controls

| Control | Expected |
|---|---|
| Unknown research entity | no realized source answer; abstain |
| Untaught math operator | action fails; abstain |
| Unsupported code operation | no artifact; abstain |
| Unknown target language | no learned translation frame; abstain |
| Partial unit evidence | one pair cannot license conversion; abstain |
| Conflicting unit ratios | conflicting evidence cannot license conversion; abstain |

Tampered outputs are rejected in `experiments/v1_558_family_b_plan.py`; a
tampered realized answer and a tampered math value both fail verification.
Plan-log records preserve failure candidates for later learning.

## Gate

- ≥80% scenario completion; current run: **30/30**.
- Zero confidently invalid answers; current run: **0 unsafe**.
- Matching controls abstain; current run: **6/6**.
- Every cited answer resolves to a stored source span.
- Every answer renders a plan; `why?` works for a Family B answer.
- `crms_plan_log.py` can summarize the run into the first compounding baseline.

## Limits

- Research realization is conservative: active-voice `created`/`wrote`
  sentences and the existing passive realization path; it does not synthesize
  an answer from unlicensed wording.
- Math and unit conversions are exact and evidence-backed, not open-ended
  symbolic mathematics.
- Code generation remains limited to committed learned list/math/unit
  procedures.
- Writing remains a deterministic fictional story grammar.
- Family B does not yet create long-lived derived artifacts; revalidation is
  covered for Family A derived compositions and by action replay here.
