"""Check report-only procedure-equivalence conjectures are deterministic.

Objective: reject behavior merges that do not survive an independent holdout.
Setup: use the intentionally weak 150-random-list probe on the default
depth-two procedure set and compare two runs with fixed seeds.
Metrics: determinism, rejected-group count, and warning visibility.
Failure modes: a false equivalence enters the conjecture list, a weak-probe
warning is omitted, or fixed-seed output changes between runs.
Definition of success: both runs are identical, at least one false merge is
rejected on holdout, and both the holdout and weak-probe warnings are present.

Run from the project root with:
    python3 experiments/v1_297_equivalence_dream_diagnostic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_equivalence_dream import analyze


def main() -> None:
    options = {
        "exhaustive_short": False,
        "random_probes": 150,
        "holdout_size": 300,
    }
    first = analyze(**options)
    second = analyze(**options)
    if first != second:
        raise SystemExit("fixed-seed equivalence reports were not deterministic")
    if first["rejected_group_count"] < 1:
        raise SystemExit("weak probe did not expose a false behavior merge")
    warnings = " ".join(first["warnings"])
    if ("disagreed on holdout" not in warnings
            or "intentionally weak" not in warnings):
        raise SystemExit(f"weak-probe warning was not explicit: {warnings}")
    if any(group.get("holdout_behavior_sha256")
           for group in first["rejected_groups"]):
        raise SystemExit("rejected groups unexpectedly have one holdout signature")

    print("equivalence-dream diagnostic: PASS")
    print(f"rejected_false_merges={first['rejected_group_count']}; "
          "deterministic output and weak-probe warnings: PASS")


if __name__ == "__main__":
    main()
