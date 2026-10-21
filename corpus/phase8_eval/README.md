# Phase 8 release fixture

This fixture builds a compact Phase 8 release and then runs a clean-room
scorecard against copies of it.

- `sources` are used once to seed the model; the seed directory is deleted after
  the release is built.
- `seed_turns` teach source facts and a math phrase.
- `licences`, `dependencies`, `edges`, and `corrections` are packaged into
  `phase8.sqlite`.
- `tasks` run through the real chat CLI with `--model-db` and no source
  directory.

`fixture.sha256` locks the frozen content digest.

The fixture is deliberately synthetic and small so the gate is reproducible.
It demonstrates distribution, evidence, lineage, correction history, and
learn/reload behavior; it is not a substitute for the Phase 7 corpus or an
external v2 scorecard.

Run it with:

```sh
python3 run_phase8_eval.py
```

Report: `experiments/reports/phase8_release.json`.
