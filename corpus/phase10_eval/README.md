# Phase 10 first-slice generation fixture

This directory freezes the first vertical slice of rule-only generation. It is
not the full Phase 10 evaluation.

Contents:

- `fixture.json` — twelve cases covering all ten declared genres plus
  abstention and clarification. Facts are structured propositions with source
  spans. Source documents use different wording so the copy ratio measures
  realization rather than sentence selection.
- `fixture.sha256` — content lock checked by the runner.
- `teacher_proposal.json` — accepted offline teacher clarity proposal.
- `teacher_proposal_rejected.json` — negative control rejected by the frozen
  suite.
- The visible rule file is `crms_generation_rules.json`.
- The generator is `crms_generation.py`.
- The runner is `run_phase10_eval.py`.
- The SQL/teacher lane is `run_phase10_teacher.py`.
- The automated comparison is `run_phase10_comparison.py`.
- The aggregate gate is `run_phase10_external.py`.

Run:

```sh
python3 run_phase10_eval.py
python3 run_phase10_teacher.py
python3 run_phase10_comparison.py
python3 run_phase10_external.py
```

The bounded lane covers all ten declared genres, the teacher proposal loop, SQL
snapshots and rollback, clean-room reload, `/compose PATH` in chat, and an
automated 70B-class comparison. It still lacks human clarity calibration, an independently authored
300-prompt suite over two source-disjoint corpora, and a measured 70B
checkpoint; those remain open full-gate items.
