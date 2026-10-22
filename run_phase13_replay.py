#!/usr/bin/env python3
"""Replay the answerability gate over recorded chat traces and tune its policy offline.

Each quality report (run_phase13_quality.py) keeps, per question, the candidate sentences the chat
offered the gate. Replaying them with a changed policy shows how many correct answers survive and
how many wrong ones are stopped, without re-running the chat. Development data only."""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

import crms_nl_gate as gate  # noqa: E402
from crms_oracle_eval import matches  # noqa: E402


def load(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        for row in json.loads(Path(path).read_text())["rows"]:
            if row.get("trace"):
                rows.append(row)
    return rows


def decide(row: dict, policy: dict) -> tuple[str, str]:
    """(status, evidence text) of the last gate call recorded for the question."""
    gate.gate_policy = lambda: policy              # replay under the candidate policy
    record = row["trace"][-1]
    result = gate.gate_quoted_evidence(record["question"], record["rows"],
                                       licensed_predicates=record.get("licensed", []))
    evidence = result.get("evidence") or {}
    return result["status"], str(evidence.get("text", ""))


def score(rows: list[dict], policy: dict) -> dict:
    good = bad = 0
    for row in rows:
        if row["trace"][-1]["status"] not in ("accepted", "rejected", "unchanged"):
            continue
        status, text = decide(row, policy)
        if status != "accepted":
            continue
        answerable = row["label"] != "unanswerable_answered" and bool(row["gold"])
        if answerable and matches(row["gold"], text):
            good += 1
        else:
            bad += 1
    return {"correct": good, "wrong": bad, "utility": good - 3 * bad}


def with_rows(base: dict, **rows: float | None) -> dict:
    policy = {k: dict(v) for k, v in base.items()}
    for name, threshold in rows.items():
        if threshold is None:
            policy.pop(name, None)
        else:
            policy[name] = {"answer_types": None, "invariant": True, "threshold": threshold,
                            "typed_reason": name}
    return policy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+")
    parser.add_argument("--grid", action="store_true")
    args = parser.parse_args()
    rows = load(args.reports)
    base = gate.gate_policy()
    print("rows with gate traces:", len(rows))
    print("current policy:", score(rows, base))
    if args.grid:
        results = []
        for rare, weighted in itertools.product([None, 9.0, 8.0, 7.0, 6.5, 6.0, 5.5, 5.0],
                                                [None, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4]):
            policy = with_rows(base, rare_term_absent=rare, weighted_coverage=weighted)
            results.append((score(rows, policy), rare, weighted))
        for res, rare, weighted in sorted(results, key=lambda r: -r[0]["utility"])[:12]:
            print(res, "rare>=", rare, "weighted>=", weighted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
