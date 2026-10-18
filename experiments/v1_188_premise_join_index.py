"""Measure sound endpoint-index pruning for fact-grounded rule premises."""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Start", "left-edge", "Bridge", "left:valid")
    kb.add_fact("Bridge", "right-edge", "Finish", "right:valid")
    for index in range(24):
        left_only = f"Left Only {index:02d}"
        right_only = f"Right Only {index:02d}"
        kb.add_fact("Start", "left-edge", left_only, f"left:{index}")
        kb.add_fact(right_only, "right-edge", "Finish", f"right:{index}")
    rule = kb.add_inference_rule(
        "two-sided-join", "left-edge", "right-edge", "connected")

    result = kb.infer_relation("Start", "connected", "Finish")
    require(result.status == "answered" and result.complete
            and result.lineage_count == 1,
            f"indexed relation join lost the valid proof: {result}")
    # The endpoint indexes each contain 25 candidates, but only Bridge occurs
    # on both sides. Search spends once on that middle and once on its proof.
    require(result.expansions == 2,
            f"middle candidates were not intersected before expansion: {result.expansions}")
    check = verify_inference_proof(
        result.proofs[0], [asdict(fact) for fact in kb.facts()],
        [asdict(rule)], expected_conclusion=result.conclusion)
    require(check.valid, f"independent checker rejected indexed proof: {check}")

    limited = kb.infer_relation(
        "Start", "connected", "Finish", max_expansions=1)
    require(limited.status == "unknown" and not limited.complete
            and limited.reason_code == "search_limit" and not limited.proofs,
            "one-under-budget indexed search leaked a partial proof")

    print("premise join index diagnostic: PASS")
    print("51 all-entity candidates reduced to one joined middle; proof and limit abstention verified")


if __name__ == "__main__":
    main()
