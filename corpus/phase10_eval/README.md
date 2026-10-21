# Phase 10 first-slice generation fixture

This directory freezes the first vertical slice of rule-only generation. It is
not the full Phase 10 evaluation.

Contents:

- `fixture.json` — seven cases: explanation, comparison, procedure, analysis,
  summary, abstention, and clarification. Facts are structured propositions with
  source spans. Source documents use different wording so the copy ratio
  measures realization rather than sentence selection.
- `fixture.sha256` — content lock checked by the runner.
- The visible rule file is `crms_generation_rules.json`.
- The generator is `crms_generation.py`.
- The runner is `run_phase10_eval.py`.

Run:

```sh
python3 run_phase10_eval.py
```

The first slice covers five of the ten declared genres. It has no teacher loop,
SQL rule lifecycle, human clarity calibration, two-source-disjoint corpus, or
70B comparison. The report keeps those as open full-gate items.
