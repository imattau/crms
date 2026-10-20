"""Aggregate scorecard results.

Rates are reported separately by category and outcome. Known failures are
tracked but excluded from the gated pass rate so a frozen baseline can carry
open regressions without hiding them.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable


@dataclass
class TaskResult:
    id: str
    category: str
    provenance: str
    status: str
    observed: str
    failures: tuple[str, ...]
    unsafe: bool
    duration_s: float
    known_failure: bool
    notes: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[position]


def summarize(results: Iterable[TaskResult]) -> dict[str, Any]:
    rows = list(results)
    gated = [row for row in rows if not row.known_failure]
    known = [row for row in rows if row.known_failure]
    passed = [row for row in gated if row.passed]
    failed = [row for row in gated if row.status == "fail"]
    errors = [row for row in gated if row.status == "error"]
    unsafe = [row for row in rows if row.unsafe]
    durations = [row.duration_s for row in rows if row.duration_s > 0]

    categories: dict[str, dict[str, Any]] = {}
    for row in gated:
        entry = categories.setdefault(
            row.category, {"total": 0, "passed": 0, "failed": 0, "errors": 0})
        entry["total"] += 1
        if row.passed:
            entry["passed"] += 1
        elif row.status == "error":
            entry["errors"] += 1
        else:
            entry["failed"] += 1
    for entry in categories.values():
        entry["pass_rate"] = (
            round(entry["passed"] / entry["total"], 4) if entry["total"] else 0.0)

    observed: dict[str, int] = {}
    for row in rows:
        observed[row.observed] = observed.get(row.observed, 0) + 1

    return {
        "total": len(rows),
        "gated_total": len(gated),
        "passed": len(passed),
        "failed": len(failed),
        "errors": len(errors),
        "pass_rate": round(len(passed) / len(gated), 4) if gated else 0.0,
        "unsafe_answers": len(unsafe),
        "known_failures": len(known),
        "known_failures_passed": sum(1 for row in known if row.passed),
        "observed": observed,
        "by_category": categories,
        "duration_s": {
            "median": round(median(durations), 3) if durations else 0.0,
            "p95": round(percentile(durations, 0.95), 3),
            "max": round(max(durations), 3) if durations else 0.0,
        },
    }
