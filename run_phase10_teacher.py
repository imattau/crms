#!/usr/bin/env python3
"""Run the offline teacher proposal loop and persist composition memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_composition_memory import GenerationRuleStore, seed_store  # noqa: E402
from crms_examiner import evaluate_proposal, load_proposal, record_proposal  # noqa: E402
from crms_generation_rules import DEFAULT_RULES_PATH, load_rules  # noqa: E402

PROPOSAL = PROJECT / "corpus" / "phase10_eval" / "teacher_proposal.json"
REJECTED = PROJECT / "corpus" / "phase10_eval" / "teacher_proposal_rejected.json"
STORE = PROJECT / "data" / "phase10_composition.sqlite"
REPORT = PROJECT / "experiments" / "reports" / "phase10_teacher.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    args.store.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(DEFAULT_RULES_PATH.read_text(encoding="utf-8"))
    results = []
    with GenerationRuleStore(args.store) as store:
        if store.active_snapshot() is None:
            seed_store(store, payload)
        for path, expected in ((PROPOSAL, True), (REJECTED, False)):
            proposal = load_proposal(path)
            result = evaluate_proposal(proposal, rules=load_rules())
            result["snapshot_id"] = record_proposal(store, result)
            result["expected_acceptance"] = expected
            result["matches_expectation"] = result["accepted"] is expected
            results.append(result)
        active = store.active_snapshot()
        stats = store.stats()
    report = {
        "format": "crms-phase10-teacher-report",
        "version": 1,
        "proposals": results,
        "active": active,
        "store": str(args.store.resolve().relative_to(PROJECT))
        if args.store.resolve().is_relative_to(PROJECT) else str(args.store),
        "stats": stats,
        "gate": {
            "accepted_proposal_no_regression": results[0]["accepted"],
            "negative_control_rejected": not results[1]["accepted"],
            "sql_snapshot_recorded": bool(results[0].get("snapshot_id")),
            "teacher_model_recorded": bool(
                results[0]["proposal"].get("model")),
            "human_review": False,
        },
    }
    report["gate_passed"] = all(
        value for key, value in report["gate"].items() if key != "human_review")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    for result in results:
        print(f"{result['proposal']['proposal_id']}: "
              f"{'ACCEPT' if result['accepted'] else 'REJECT'} "
              f"(expected {'accept' if result['expected_acceptance'] else 'reject'})")
    print(f"Active snapshot: {active['snapshot_id'] if active else None}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
