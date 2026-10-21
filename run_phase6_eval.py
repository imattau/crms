#!/usr/bin/env python3
"""Run the frozen Phase 6 domain breadth benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_phase6_benchmark import PHASE6_FIXTURE, evaluate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=PHASE6_FIXTURE)
    parser.add_argument("--out", type=Path,
                        default=PROJECT / "experiments" / "reports"
                        / "phase6_domains.json")
    args = parser.parse_args()
    report = evaluate(args.fixture)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    for name, row in report["slices"].items():
        print(f"{name:14s} {row['correct']:2d}/{row['tasks']:2d} "
              f"({row['completion']:.0%}) errors={row['confident_errors']} "
              f"negative={row['negative_abstained']}/{row['negative_total']} "
              f"repair={row['repair_passed']} "
              f"median={row['median_ms']:.2f}ms p95={row['p95_ms']:.2f}ms")
    print(f"Overall: {report['overall']['correct']}/"
          f"{report['overall']['tasks']} "
          f"({report['overall']['completion']:.1%})")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'} "
          f"{report['gate']}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
