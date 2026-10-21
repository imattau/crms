#!/usr/bin/env python3
"""Measure Phase 5 construction learning against an exact-frame baseline.

The benchmark induces ten construction shapes from teacher-marked examples and
scores 200 held-out paraphrases with an independent operation oracle. Controls
reuse a training wording with new fillers; reworded tasks recombine learned
token-class alternatives.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_phase5_benchmark import (  # noqa: E402
    PHASE5_FIXTURE, abstention_lane, active_learning_lane, context_lane,
    load_constructions, morphology_lane, new_construction_lane, ranker_lane,
    registry_lane, run_benchmark,
)


def _display_path(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def _delta(learned: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "correct": learned["correct"] - baseline["correct"],
        "coverage": learned["coverage"] - baseline["coverage"],
        "confident_errors": (learned["confident_errors"]
                             - baseline["confident_errors"]),
    }


def evaluate(families_path: str | Path = PHASE5_FIXTURE) -> dict[str, Any]:
    data = load_constructions(families_path)
    benchmark = run_benchmark(data)
    registry = registry_lane(benchmark["store"], benchmark["registry"], data)
    abstention = abstention_lane(
        benchmark["store"], benchmark["registry"], data)
    morphology = morphology_lane()
    ranker = ranker_lane(benchmark["store"], benchmark["registry"])
    active = active_learning_lane()
    new_construction = new_construction_lane()
    context = context_lane(benchmark["store"], benchmark["registry"], data)

    by_construction = {}
    for construction_id in sorted(benchmark["learned"]["by_construction"]):
        learned = benchmark["learned"]["by_construction"][construction_id]
        baseline = benchmark["baseline"]["by_construction"][construction_id]
        by_construction[construction_id] = {
            "learned": learned,
            "baseline": baseline,
            "delta": _delta(learned, baseline),
        }

    learned = benchmark["learned"]
    baseline = benchmark["baseline"]
    gate = {
        "paraphrase_coverage_doubles": (
            baseline["coverage"] > 0
            and learned["coverage"] >= 2 * baseline["coverage"]),
        "no_wrong_answer_increase": (
            learned["confident_errors"] <= baseline["confident_errors"]),
        "learned_beats_handcoded": (
            learned["correct"] > baseline["correct"]
            and all(row["delta"]["correct"] >= 0
                    for row in by_construction.values())
            and any(row["delta"]["correct"] > 0
                    for row in by_construction.values())),
        "no_confident_wrong_answers": learned["confident_errors"] == 0,
        "unlicensed_productions_abstain": (
            abstention["all_abstain"]),
        "registry_lifecycle": (
            registry["all_active_have_holdout_evidence"]
            and registry["matched_before_retire"] == "matched"
            and registry["after_retire"] == "no_match"
            and not registry["dangling_references"]
            and registry["matched_after_rollback"] == "matched"),
        "new_construction_registry": (
            new_construction["state_before"] == "active"
            and new_construction["matched_before"] == "matched"
            and new_construction["matched_after_retire"] == "no_match"
            and not new_construction["dangling_references"]
            and new_construction["matched_after_rollback"] == "matched"),
        "morphology_expansion": (
            morphology["regular_expansion"]
            and not morphology["irregular_before_evidence"]
            and morphology["irregular_after_evidence"]
            and morphology["registry_regular_active"]
            and morphology["registry_irregular_active"]
            and not morphology["regular_after_retirement"]),
        "propose_only_ranker": (
            ranker["candidate_count"] <= ranker["max_candidates"]
            and all(count <= ranker["max_features"]
                    for count in ranker["feature_counts"])
            and ranker["bypass_same"]),
        "active_construction_learning": (
            active["questions_asked"] == 1
            and active["failed_status"] == "no_match"
            and "enumerate" in active["missing"]
            and active["matched_after"] == "matched"
            and active["rule_state"] == "active"),
        "same_utterance_different_context": (
            context["matched"] and context["context_sensitive"]
            and context["context_count"] == 2),
    }
    return {
        "format": "crms-phase5-eval",
        "version": 1,
        "corpus": {
            "constructions": len(data["specs"]),
            "training_examples": len(data["training"]),
            "heldout_tasks": len(data["heldout"]),
            "controls": sum(1 for task in data["heldout"]
                            if task["kind"] == "control"),
            "reworded": sum(1 for task in data["heldout"]
                            if task["kind"] == "reworded"),
            "composition_shapes": sorted({
                spec["composition"] for spec in data["specs"]}),
        },
        "learned": learned,
        "baseline": baseline,
        "delta": _delta(learned, baseline),
        "control_and_reworded": {
            "learned": benchmark["learned_by_kind"],
            "baseline": benchmark["baseline_by_kind"],
        },
        "by_construction": by_construction,
        "registry": registry,
        "abstention": abstention,
        "morphology": morphology,
        "ranker": ranker,
        "active_learning": active,
        "new_construction": new_construction,
        "context": context,
        "dialogue_moves": {
            "status": "experimental",
            "used_by_construction_route": False,
            "note": ("dialogue moves remain behind the explicit baseline; "
                     "construction routing does not promote them"),
        },
        "gate": gate,
        "gate_passed": all(gate.values()),
        "provenance": {
            "fixture": _display_path(families_path),
            "method": ("teacher-marked induction, exact-frame baseline, "
                       "independent operation oracle"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=PHASE5_FIXTURE)
    parser.add_argument(
        "--out", type=Path,
        default=PROJECT / "experiments" / "reports"
        / "phase5_constructions.json")
    args = parser.parse_args()
    report = evaluate(args.fixture)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    learned = report["learned"]
    baseline = report["baseline"]
    print("Phase 5 construction learning")
    print(f"  constructions: {report['corpus']['constructions']}  "
          f"held-out: {report['corpus']['heldout_tasks']}")
    print(f"  exact frames: {baseline['correct']}/{baseline['tasks']} "
          f"({baseline['coverage']:.1%})")
    print(f"  learned constructions: {learned['correct']}/{learned['tasks']} "
          f"({learned['coverage']:.1%})")
    print(f"  wrong answers: baseline {baseline['confident_errors']}  "
          f"learned {learned['confident_errors']}")
    print(f"  controls: learned {report['control_and_reworded']['learned']['control']['answered']}"
          f"/{report['control_and_reworded']['learned']['control']['tasks']}  "
          f"reworded: learned {report['control_and_reworded']['learned']['reworded']['answered']}"
          f"/{report['control_and_reworded']['learned']['reworded']['tasks']}")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'} "
          f"{report['gate']}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
