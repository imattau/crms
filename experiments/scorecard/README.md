# CRMS scorecard suites

The scorecard is the project's end-to-end instrument of record. It runs complete
user tasks through the real chat CLI in a clean process and checks outcomes with
explicit oracles. It is not a replacement for the unit diagnostics in
`experiments/`; those remain the regression layer.

## Run it

```sh
python3 run_scorecard.py --suite smoke
python3 run_scorecard.py --suite family_a
python3 run_scorecard.py --suite smoke --list
python3 run_scorecard.py --suite experiments/scorecard/smoke.jsonl --keep-workspaces
```

Reports are written to `experiments/reports/scorecard/<date>-<suite>/` as
`report.json` and `report.md`. Runs never overwrite an existing report
directory.

Current suites:

- `smoke` — 12 cross-capability tasks (research, dialogue, reload, math,
  abstention, procedures).
- `family_a` — 4 proof-selected value → learned procedure tasks, including a
  fresh reload and an unknown-value abstention.

The command exits non-zero when a gated task fails or an expected abstention
becomes a confident answer.

## Task schema

One JSON object per line. Blank lines and `#` comments are ignored.

```json
{
  "id": "research-who-created-python",
  "category": "research",
  "provenance": "authored",
  "notes": "Direct source-backed who question with an exact citation.",
  "known_failure": false,
  "index_kind": "json",
  "rule_depth": 2,
  "timeout_s": 180,
  "documents": [
    {"path": "people.txt", "text": "Python was created by Guido van Rossum in 1991."}
  ],
  "turns": ["Who created Python?"],
  "expect": {
    "contains": ["Guido van Rossum created Python.", "[Source: people.txt"],
    "not_contains": ["I don't know"],
    "regex": ["(?i)created"],
    "citations": [{"source": "people.txt", "quote": "Guido van Rossum created Python."}],
    "occurrences": [{"text": "Guido van Rossum created Python.", "count": 1}],
    "outcome": "answer"
  }
}
```

Fields:

| Field | Meaning |
|---|---|
| `id` | Unique non-whitespace slug |
| `category` | Reporting bucket: research, abstention, reload, math, procedures, dialogue, coding, translation, creative, ... |
| `provenance` | `authored`, `codex-labelled`, `hand-coded`, or `independently-checked` |
| `documents` | Source fixtures written under a temp `sources/` directory and ingested with `/source-dir` |
| `turns` | Chat input, in order. Use `__restart__` to start a fresh process between turns |
| `index_kind` | `json` (default) or `sqlite` |
| `rule_depth` | Max procedure composition depth (chat default is 2; use 1 for primitive lessons) |
| `known_failure` | Frozen open failure: reported separately and excluded from the gated pass rate |
| `expect.outcome` | `answer`, `abstain`, or `clarify` |

Oracles:

- `contains` / `regex` — must appear in the transcript (including system lines).
- `not_contains` — must not appear in assistant replies.
- `citations` — source label and exact quote must appear in the transcript.
- `occurrences` — minimum count of an exact string; useful for reload checks.
- `outcome` — the final assistant reply must answer, abstain, or ask for
  clarification. A confident answer when abstention was expected is recorded as
  an **unsafe answer** and fails the gate.

The harness only supplies source text and turns. It must never select evidence,
choose an operation, or compose an answer on the system's behalf.

## Policy

1. Freeze a task's expectations before tuning the behaviour it measures.
2. Keep the held-out split locked by content; do not edit a held-out task to
   make it pass.
3. Record provenance for every task. Codex-labelled or hand-coded fixtures are
   supervision, not independent validation.
4. Keep every reproduced failure as a permanent control (`known_failure` when
   it is an open gap).
5. Report completion, wrong answers, abstentions, clarification, evidence
   validity, task duration, and reload separately. Do not collapse them into one
   score.
6. New chat-facing behaviour runs the smoke suite before merge.

## Current coverage

`smoke.jsonl` covers direct research answers, compound questions, abstention,
reload, SQLite retrieval, learned math, procedure learning, untaught-request
clarification, dialogue history, and locally anchored pronoun date answers. The
full ~300-task suite is built incrementally; add tasks from reproduced failures
and independently authored user requests, not from implementation details.

## Adding a task

1. Write the user request first, with its expected outcome.
2. Decide the oracle before looking at the current output.
3. Add the task to the suite (or a new suite under this directory).
4. Run `python3 run_scorecard.py --suite <suite> --list` to validate the schema.
5. Run the suite. A failure is a result, not a reason to weaken the oracle.
6. If the failure is an accepted open gap, mark `known_failure` and keep it
   visible in the report.
