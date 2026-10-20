#!/usr/bin/env python3
"""Summarize the first CRMS compounding baseline from a plan log.

The baseline is intentionally mechanical: completed vs failed typed plans,
which routes and goals were exercised, how many distinct request frames and
actions were used, and how many failure candidates were recorded. It is not a
model-quality score; it is the denominator for later learning curves.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_plan_log import load_plan_log, summarize_plan_log  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path,
                        help="plan log written by crms_chat.py --plan-log")
    parser.add_argument("--json", action="store_true",
                        help="print the summary as JSON")
    args = parser.parse_args()
    records = load_plan_log(args.log)
    summary = summarize_plan_log(records)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"Plan log: {args.log}")
    print(f"Plans: {summary['total']}  answered: {summary['answered']}  "
          f"success: {summary['success_rate'] * 100:.1f}%")
    print(f"Routes: {summary['by_route']}")
    print(f"Goals: {summary['by_goal']}")
    print(f"Statuses: {summary['by_status']}")
    print(f"Distinct frames: {summary['distinct_frames']}  "
          f"actions: {summary['distinct_actions']}  "
          f"procedures: {summary['distinct_procedures']}")
    print(f"Failure candidates: {summary['failure_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
