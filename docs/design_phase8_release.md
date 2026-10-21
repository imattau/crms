# Phase 8 portable release and clean-room gate

**Status:** bounded Phase 8 release gate passed 2026-10-21.
**Code:** `crms_phase8_model.py`, `run_phase8_eval.py`.
**Contract test:** `experiments/v1_564_phase8_model.py`.
**Frozen fixture:** `corpus/phase8_eval/fixture.json`.
**Report:** `experiments/reports/phase8_release.json`.

## Goal

Phase 8 closes the distribution loop that Phase 7 left open. A release must be a
copyable directory whose chat model, source evidence, licences, rule lifecycle,
dependency lineage, and correction history are all inspectable without the
build inputs.

The gate is deliberately narrower than a general performance claim:

1. a release is copied to a temporary clean room;
2. the original release directory is hidden for the whole run;
3. the seed source directory is deleted after packaging;
4. a frozen scorecard runs through the real chat CLI with `--model-db`;
5. the source, math, dialogue, abstention, reload, learn/reload, release
   inspection, lineage, correction, and evidence tasks pass;
6. release size and runtime are reported.

## Release layout

```text
phase8_release/
  model.sqlite      chat-compatible learned model and embedded source text
  phase8.sqlite     licences, dependencies, registry, corrections, integrity
  release.json      format, model schema, compatibility, file digests, counts
```

`model.sqlite` is the existing `crms-learned-model` package format. Keeping it
separate preserves chat compatibility and lets the Phase 8 metadata evolve
without changing the model reader. Phase 8 adds a release format on top rather
than hiding its lineage in a second undocumented file.

`phase8.sqlite` tables:

- `release_meta` — format, model schema, creation time, read-only flag,
  compatibility, licence coverage, counts;
- `licences` — one per embedded source document: source, licence class, URL,
  attribution, retrieval date, revision, body SHA-256;
- `dependencies` and `dependency_edges` — source/fact/derived/rule lineage;
- `registry_rules` and `registry_history` — governed rule lifecycle;
- `corrections` — trigger, reason, affected nodes, retained nodes, timestamp;
- `integrity` — model file digest, size, role.

`release.json` repeats the file digests and compatibility range. `open_release`
rejects a missing file, a size mismatch, a changed digest, an invalid model
header, or a metadata integrity mismatch. The metadata connection is opened
with SQLite `mode=ro`; a write raises `OperationalError`.

## Model compatibility and migration

The release accepts chat models that pass `inspect_model_database`, including
package schemas 1–5. `release.json` records the compatibility range. A model
with a newer unsupported schema fails closed.

`crms_phase8_model.py migrate --model-db OLD --output NEW` materializes an older
model into the current package schema through the installer and re-exports it.
It does not need the original source files. The migrated model can be published
with `build_release`.

## Clean-room driver

`run_phase8_eval.py` builds a seed model once:

- writes the fixture's source documents;
- indexes them through chat;
- teaches the fixture math phrase and facts;
- exports a single `model.sqlite`;
- builds a rule registry and the Phase 8 metadata;
- deletes the seed workspace.

Each scorecard task receives a fresh copy of the release. The task workspace has
no source directory. If a task teaches a new math phrase, that state lives in
the task copy's sidecar, survives a `__restart__`, and is discarded with the
task. The original release is hidden during the entire run.

## Chat UX

When `--model-db` points inside a Phase 8 release, chat exposes:

```text
/model-info
/lineage derived:sum-mira
/corrections
/evidence people.txt
```

`/model-info` reports format, model schema, read-only status, size, source
count, licence coverage, dependency counts, corrections, and registry rules.
The command reads `release.json` and `phase8.sqlite` read-only. The existing
`/rule-health` and `/rule-detail` commands remain the registry inspector.

## Commands

```sh
python3 run_phase8_eval.py
python3 crms_phase8_model.py inspect --release data/phase8_release
python3 crms_phase8_model.py verify --release data/phase8_release
python3 crms_phase8_model.py lineage --release data/phase8_release derived:sum-mira
python3 crms_phase8_model.py corrections --release data/phase8_release
python3 crms_phase8_model.py evidence --release data/phase8_release people.txt
python3 crms_phase8_model.py migrate --model-db OLD.sqlite --output NEW.sqlite
python3 experiments/v1_564_phase8_model.py
```

## Measured result

| Measure | Value |
|---|---:|
| Release tasks | 12/12 |
| Unsafe answers | 0 |
| Model schema | 4 |
| Release size | 167,936 bytes |
| Model / metadata | 98,304 / 69,632 bytes |
| Embedded sources | 2 |
| Licence coverage | 100% |
| Dependency nodes / edges | 6 / 5 |
| Registry rules | 1 |
| Corrections | 1 |
| Build time | 0.41 s |
| Scoring time | 4.27 s |
| Median / p95 task | 0.31 s / 0.58 s |

The scorecard covers source citation, second source answer, learned math,
dialogue history, abstention, source reload after restart, learning a new math
phrase then reloading, rule-health inspection, release inspection, lineage,
corrections, and per-document licence evidence. Integrity verification passed,
the original release was hidden, and the seed source directory was not available
to any task.

Regression baselines remain green: smoke 12/12, Family A 30/30, and Family B
36/36, all with zero unsafe answers (`experiments/reports/phase8_regressions.json`).
These use their normal workspace fixtures; they are regression evidence, not
model-only distribution tasks.

## Limitations

- The measured release is a compact, deterministic fixture so the gate is
  reproducible and fast. It is not a packaged copy of the 1.3 GB Phase 7 corpus.
- The Phase 7 sharded corpus can remain a separate retrieval layer; packaging
  the full corpus into a single release needs a streaming packer and a size
  budget, and is not claimed here.
- This is a bounded release scorecard, not the full external v2 suite.
- Performance at one million facts and a 2 GB index is not measured.
- The seed facts and dependencies are fixture data, used to demonstrate
  inspectability, not a claim of broad learning.
