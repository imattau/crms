#!/usr/bin/env python3
"""Phase 12: abstention gate on the quote fallback, measured.

Runs the chat on the independent set (corpus A: Simple English Wikipedia, corpus B:
arXiv) and on the frozen oracle samples, records every quote-gate decision through
``CRMS_GATE_TRACE``, and reports correct / wrong / abstain, answers to unanswerable
questions, and the rejected sentences by deviation dimension. The independent set is
a final measurement only: it is not used to choose thresholds (see
``docs/design_phase12_coverage_and_supervision.md``). Compare against the unchanged
chat's answers in ``experiments/reports/phase12_independent_answers.json``.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_independent_eval import load_set, oracle_label, summarise  # noqa: E402
from crms_oracle_eval import grade  # noqa: E402

INDEX = {"A": PROJECT / "data" / "crms_simplewiki_research.sqlite",
         "B": PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"}
INDEPENDENT = PROJECT / "corpus" / "phase12_eval" / "independent_set.json"
ORACLES = {"oracle_a": PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json",
           "oracle_b": PROJECT / "corpus" / "phase12_eval" / "oracle_sample_b.json"}
BASELINE = PROJECT / "experiments" / "reports" / "phase12_independent_answers.json"
REPORT = PROJECT / "experiments" / "reports" / "phase12_gate.json"


def run_chat(item: dict, extra: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="crms-gate-") as folder:
        command = [sys.executable, str(PROJECT / "crms_chat.py"), "--index",
                   str(INDEX[item["corpus"]])]
        for name in ("dialogue-state", "candidate-session", "rule-session", "math-session"):
            command += [f"--{name}", f"{folder}/{name}.json"]
        command += ["--feedback-db", f"{folder}/feedback.sqlite3", *extra]
        trace = f"{folder}/trace.jsonl"
        try:
            out = subprocess.run(command, input=item["question"] + "\n/quit\n", text=True,
                                 capture_output=True, timeout=240, cwd=folder,
                                 env=dict(os.environ, CRMS_GATE_TRACE=trace)).stdout
        except (subprocess.TimeoutExpired, OSError):
            out = ""
        records = ([json.loads(line) for line in open(trace, encoding="utf-8")]
                   if os.path.exists(trace) else [])
    parts = out.split("CRMS> ")
    answer = ""
    if len(parts) > 1:
        answer = re.sub(r"\s*you>\s*$", "", parts[1].strip()).split("CRMS state saved")[0].strip()
    return {"id": item["id"], "answer": answer, "gate": records}


def run_all(items: list[dict], extra: list[str], workers: int) -> list[dict]:
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(lambda it: run_chat(it, extra), items))
    for k, row in enumerate(rows):          # a timed-out run is retried once, alone
        if not row["answer"]:
            rows[k] = run_chat(items[k], extra)
    return rows


def dimension_counts(rows: list[dict]) -> dict[str, int]:
    counts: collections.Counter = collections.Counter()
    for row in rows:
        if row["gate"] and row["gate"][-1]["status"] == "rejected":
            counts.update(row["gate"][-1].get("dimensions", []))
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--only", choices=["independent", "oracle"], default=None)
    args = parser.parse_args()
    report: dict = {"phase": 12, "workstream": "abstention gate on the quote fallback"}
    if REPORT.is_file():                     # keep the other half of an earlier run
        report.update(json.loads(REPORT.read_text()))
    if args.only in (None, "independent"):
        digest = INDEPENDENT.with_suffix(".sha256").read_text().strip()
        if hashlib.sha256(INDEPENDENT.read_bytes()).hexdigest() != digest:
            raise SystemExit("independent set does not match its digest")
        items = load_set(INDEPENDENT)
        before = json.loads(BASELINE.read_text())["rows"]
        rows = run_all(items, [], args.workers)
        report["independent"] = {
            "set_digest": digest,
            "unchanged_chat": summarise(items, [oracle_label(i, r["chat"]) for i, r in zip(items, before)])["overall"],
            "with_gate": summarise(items, [oracle_label(i, r["answer"]) for i, r in zip(items, rows)])["overall"],
            "rejections_by_dimension": dimension_counts(rows),
        }
        lost = [i["id"] for i, b, r in zip(items, before, rows)
                if oracle_label(i, b["chat"]) == "correct"
                and oracle_label(i, r["answer"]) != "correct"]
        report["independent"]["correct_lost"] = lost
        print("independent", json.dumps(report["independent"], indent=1))
    if args.only in (None, "oracle"):
        report["oracle"] = {}
        for name, path in ORACLES.items():
            raw = json.loads(path.read_text())["items"]
            items = [{"id": f"{name}{k}", "corpus": "A", "question": it["question"],
                      "gold": it["gold"], "answerable": True, "support": ""}
                     for k, it in enumerate(raw)]
            rows = run_all(items, [], args.workers)
            labels = [grade(it, r["answer"]) for it, r in zip(items, rows)]
            counts = collections.Counter(labels)
            answered = counts["correct"] + counts["wrong"]
            report["oracle"][name] = {
                "questions": len(items), **{k: counts[k] for k in ("correct", "wrong", "abstain")},
                "wrong_share_of_answered": round(counts["wrong"] / answered, 4) if answered else 0.0,
                "rejections_by_dimension": dimension_counts(rows)}
            print(name, report["oracle"][name])
    REPORT.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
