# Phase 10 scorecard

**Status:** bounded lane complete 2026-10-21; full external gate open.
**Aggregate report:** `experiments/reports/phase10_external.json`.
**Rule file:** `crms_generation_rules.json`.
**Engine:** `crms_generation.py`.

## Bounded gate

| Check | Result |
|---|---|
| Frozen generation cases | **12/12** |
| Declared genres tested | **10/10** |
| Abstention and clarification controls | pass |
| Mean copy ratio | **0.157** |
| Mean sentences | **6.2** |
| Teacher accepted with no regression | pass |
| Teacher negative control rejected | pass |
| SQL snapshots/judgments/rollback | pass |
| Clean-room copied reload | pass |
| Generalisation diagnostics | pass |
| Automated 70B-class comparison thresholds | pass |

## Generated genres

Explanation, comparison, procedure, analysis, summary, argument, professional
writing, narrative, technical note, and dialogue.

All factual propositions carry evidence ids; abstention and missing-move
clarification are explicit paths.

## Teacher and SQL

- Accepted proposal: `teacher-align-jargon-v1`, authored offline by
  `opencode-go/qwen3.8-flash`; it aligns `clarity.jargon_terms` with the
  replacement map. Mean score and copy ratio unchanged; suite remains 12/12.
- Rejected control: `negative-control-short-sentences`, which forces a
  five-word sentence cap and fails the frozen cases.
- SQL store: `data/phase10_composition.sqlite` (git-ignored). Snapshot,
  judgment, active selection, frame stats, and rollback are recorded.
- Generalisation report: `experiments/reports/phase10_generalisation.json`
  covers class hierarchy, back-off, report-only analogies, evidence-count
  weights, and a fact-coverage curve.

## Automated comparison

Ten genre prompts; CRMS versus `opencode-go/qwen3.8-max`, a hosted 70B-class
proxy with undisclosed parameter count. Two hosted model raters scored blinded
A/B responses; they are not humans.

| System | Adequacy | Clarity | Coverage | Evidence | Confident errors |
|---|---:|---:|---:|---:|---:|
| CRMS | 1.75 | 1.90 | 1.85 | 1.85 | 3 |
| 70B-class proxy | 2.00 | 2.00 | 2.00 | 1.85 | 6 |

CRMS reaches 87.5% of proxy adequacy, 95% of clarity, and 92.5% of coverage.
Rater agreement is weak on clarity (kappa 0.0) and coverage (kappa -0.07); the
panel is a directional signal, not a human calibration.

## Limitations

See `docs/phase10_limitations.md` for the human-rater, measured-70B, suite-size,
input-representation, clarity, and generalisation gaps.

## Open full-gate items

- human clarity/comprehension calibration;
- independently authored 300-prompt suite over two source-disjoint corpora;
- measured 70B checkpoint with disclosed parameters, quantization, and hardware;
- full 10^2–10^5 rule-scaling curve and per-mechanism ablations;
- general source-to-proposition extraction (the `/compose` chat command exists,
  but it takes a structured request rather than extracting propositions from
  arbitrary source text).

## Reproduce

```sh
python3 run_phase10_eval.py
python3 run_phase10_teacher.py
python3 run_phase10_comparison.py
python3 run_phase10_external.py
python3 experiments/v1_566_phase10_generation.py
python3 experiments/v1_567_phase10_composition_memory.py
python3 experiments/v1_568_phase10_teacher.py
python3 experiments/v1_569_phase10_clean_room.py
python3 experiments/v1_570_phase10_external.py
python3 experiments/v1_571_phase10_cli.py
python3 experiments/v1_572_phase10_generalisation.py
python3 experiments/v1_573_phase10_chat_compose.py
```
