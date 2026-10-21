#!/usr/bin/env python3
"""Assemble the bounded Phase 10 external-validation gate."""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
REPORTS = PROJECT / "experiments" / "reports"
OUT = REPORTS / "phase10_external.json"


def _load(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> int:
    generation = _load("phase10_generation.json")
    teacher = _load("phase10_teacher.json")
    comparison = _load("phase10_comparison.json")
    clean = _load("phase10_clean_room.json")
    generalisation = _load("phase10_generalisation.json")
    systems = comparison["systems"]
    baseline = systems["baseline"]
    crms = systems["crms"]
    adequacy_ratio = (crms["mean_answer_adequacy"] /
                      baseline["mean_answer_adequacy"]
                      if baseline["mean_answer_adequacy"] else 0.0)
    clarity_ratio = (crms["mean_clarity"] / baseline["mean_clarity"]
                     if baseline["mean_clarity"] else 0.0)
    coverage_ratio = (crms["mean_coverage"] / baseline["mean_coverage"]
                      if baseline["mean_coverage"] else 0.0)
    bounded = {
        "generation_cases_12": (generation["summary"]["passed"] == 12
                                and generation["summary"]["cases"] == 12),
        "all_10_genres_tested": not generation["coverage"]["untested_genres"],
        "mean_copy_ratio_at_most_0_4": (
            generation["summary"]["mean_copy_ratio"] <= 0.4),
        "teacher_no_regression": teacher["gate"]["accepted_proposal_no_regression"],
        "teacher_negative_control_rejected": teacher["gate"]["negative_control_rejected"],
        "sql_rule_snapshots_recorded": teacher["stats"]["snapshots"] >= 3,
        "clean_room_identical": clean["gate_passed"],
        "generalisation_curve_published": generalisation["gate_passed"],
        "comparison_baseline_calls_ok": comparison["gate"]["baseline_calls_ok"],
        "comparison_adequacy_at_least_80pct": adequacy_ratio >= 0.8,
        "comparison_clarity_at_least_90pct": clarity_ratio >= 0.9,
        "comparison_coverage_at_least_80pct": coverage_ratio >= 0.8,
        "two_automated_raters": comparison["agreement"].get("available", False),
    }
    open_gate = {
        "human_clarity_calibration": False,
        "independent_300_prompt_suite": False,
        "two_source_disjoint_corpora": False,
        "measured_70b_model": False,
    }
    report = {
        "format": "crms-phase10-external",
        "version": 1,
        "bounded_gate": bounded,
        "bounded_gate_passed": all(bounded.values()),
        "open_gate": open_gate,
        "full_gate_passed": all(bounded.values()) and all(open_gate.values()),
        "metrics": {
            "generation": generation["summary"],
            "coverage": generation["coverage"],
            "teacher": teacher["gate"],
            "comparison": systems,
            "comparison_ratios": {
                "adequacy": adequacy_ratio,
                "clarity": clarity_ratio,
                "coverage": coverage_ratio,
            },
            "agreement": comparison["agreement"],
            "clean_room": clean,
            "generalisation": generalisation,
        },
        "reports": {
            "generation": "experiments/reports/phase10_generation.json",
            "teacher": "experiments/reports/phase10_teacher.json",
            "comparison": "experiments/reports/phase10_comparison.json",
            "clean_room": "experiments/reports/phase10_clean_room.json",
            "generalisation": "experiments/reports/phase10_generalisation.json",
        },
        "limitations": [
            "Raters are two hosted model instances, not humans.",
            "The comparison baseline is a hosted 70B-class proxy with undisclosed parameter count.",
            "The frozen suite has 12 project-authored cases, not 300 independently authored prompts over two source-disjoint corpora.",
            "Clarity is measured by automated raters and heuristics, not reader comprehension tests.",
            "The generalisation workstream has diagnostics but not the full 10^2-10^5 scaling curve.",
        ],
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"Bounded Phase 10 gate: {'PASS' if report['bounded_gate_passed'] else 'FAIL'}")
    for key, value in bounded.items():
        print(f"  {'PASS' if value else 'FAIL'} {key}")
    print("Open gate:")
    for key, value in open_gate.items():
        print(f"  {'OPEN' if not value else 'CLOSED'} {key}")
    print(f"Report: {OUT}")
    return 0 if report["bounded_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
