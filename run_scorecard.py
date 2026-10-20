#!/usr/bin/env python3
"""Run a frozen CRMS end-to-end scorecard suite.

Examples:
    python3 run_scorecard.py --suite smoke
    python3 run_scorecard.py --suite experiments/scorecard/smoke.jsonl
    python3 run_scorecard.py --suite smoke --out /tmp/crms-scorecard

Each task runs the real chat CLI in a clean temporary workspace. The runner
writes JSON and Markdown reports and exits non-zero when a gated task fails or
an expected abstention becomes a confident answer.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_eval.report import write_report  # noqa: E402
from crms_eval.runner import run_suite  # noqa: E402
from crms_eval.schema import load_suite  # noqa: E402

SUITES = PROJECT / "experiments" / "scorecard"
REPORTS = PROJECT / "experiments" / "reports" / "scorecard"


def resolve_suite(value: str) -> Path:
    candidate = Path(value)
    if candidate.suffix == ".jsonl" and candidate.is_file():
        return candidate
    if candidate.is_file():
        return candidate
    named = SUITES / f"{value}.jsonl"
    if named.is_file():
        return named
    raise SystemExit(
        f"unknown suite {value!r}; expected {named} or a .jsonl path")


def unique_output(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%H%M%S")
    candidate = path.with_name(f"{path.name}-{stamp}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{stamp}-{counter}")
        counter += 1
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="smoke",
                        help="suite name under experiments/scorecard or a JSONL path")
    parser.add_argument("--out", type=Path, default=None,
                        help="report directory (default: experiments/reports/scorecard/DATE-NAME)")
    parser.add_argument("--keep-workspaces", action="store_true",
                        help="keep per-task temporary workspaces for inspection")
    parser.add_argument("--fail-fast", action="store_true",
                        help="stop after the first gated failure")
    parser.add_argument("--list", action="store_true",
                        help="list selected tasks without running them")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON")
    args = parser.parse_args()

    suite_path = resolve_suite(args.suite)
    tasks = load_suite(suite_path)
    if args.list:
        for task in tasks:
            marker = "known-failure" if task.known_failure else "gated"
            print(f"{task.id}\t{task.category}\t{marker}")
        return 0

    outcome = run_suite(
        tasks,
        suite_name=suite_path.stem,
        keep_workspaces=args.keep_workspaces,
        fail_fast=args.fail_fast,
    )
    summary = outcome["summary"]
    output = args.out
    if output is None:
        date = datetime.now().strftime("%Y-%m-%d")
        output = unique_output(REPORTS / f"{date}-{suite_path.stem}")
    json_path, markdown_path = write_report(
        output,
        suite=suite_path.stem,
        results=outcome["results"],
        summary=summary,
        metadata=outcome["metadata"],
    )

    if args.json:
        import json
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        rate = f"{summary['pass_rate'] * 100:.1f}%"
        print(f"Suite: {suite_path.stem}")
        print(f"Passed: {summary['passed']}/{summary['gated_total']} ({rate})")
        print(f"Unsafe answers: {summary['unsafe_answers']}")
        print(f"Known failures: {summary['known_failures']} "
              f"({summary['known_failures_passed']} now passing)")
        print(f"Median task duration: {summary['duration_s']['median']}s "
              f"(p95 {summary['duration_s']['p95']}s)")
        failures = [task for task in outcome["results"]
                    if task.status != "pass" and not task.known_failure]
        if failures:
            print("\nFailures:")
            for task in failures:
                print(f"  {task.id}: {'; '.join(task.failures)}")
    print(f"\nReport: {markdown_path}")
    print(f"JSON:   {json_path}")

    gated_failures = any(
        task.status != "pass" and not task.known_failure
        for task in outcome["results"])
    return 1 if gated_failures or summary["unsafe_answers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
