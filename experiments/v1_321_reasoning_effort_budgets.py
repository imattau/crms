"""Check deterministic inference effort levels and wall-clock independence."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_inference import InferenceRule, infer_relation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    for index in range(36):
        kb.add_fact(f"P{index}", "parent", f"P{index + 1}",
                    f"family:{index}")
    kb.add_inference_rule("ancestor-base", "parent", "parent", "ancestor")
    kb.add_inference_rule("ancestor-recursive", "parent", "ancestor", "ancestor")

    short_results = {}
    for effort in ("quick", "standard", "thorough"):
        first = kb.infer_relation("P0", "ancestor", "P3", effort=effort)
        second = kb.infer_relation("P0", "ancestor", "P3", effort=effort)
        require(first == second,
                f"{effort} changed across repeated identical queries")
        require(first.status == "answered" and first.conclusion is not None,
                f"{effort} failed to prove the short chain: {first}")
        require(first.effort_level == effort,
                f"result did not identify {effort} effort")
        require(f"Reasoning effort: {effort};" in
                CRMSKnowledgeBase.render_inference(first),
                f"rendered reply omitted the {effort} effort label")
        short_results[effort] = first
    conclusion = short_results["quick"].conclusion
    require(all(result.conclusion == conclusion
                for result in short_results.values()),
            "raising effort changed a conclusion already proved at quick effort")

    quick_long = kb.infer_relation("P0", "ancestor", "P35", effort="quick")
    thorough_long = kb.infer_relation("P0", "ancestor", "P35", effort="thorough")
    require(not quick_long.complete and quick_long.limit_kind is not None,
            "quick effort failed to report its bounded incomplete search")
    require(thorough_long.status == "answered" and thorough_long.complete,
            f"thorough effort did not complete the long chain: {thorough_long}")
    require(thorough_long.effort_level == "thorough",
            "long result omitted its effort level")
    checks = thorough_long.effort_checks
    require(len(checks) == 4
            and any("Corroboration:" in check for check in checks)
            and any("Conflict scan:" in check for check in checks)
            and any("Independent proof verification:" in check
                    and "verified" in check for check in checks)
            and any("Missing-premise follow-through:" in check
                    for check in checks),
            f"thorough result omitted a performed check: {checks}")

    contested = CRMSKnowledgeBase()
    contested.add_fact("Ann", "parent", "Bob", "family:ann-bob")
    contested.add_fact("Bob", "parent", "Cara", "family:bob-cara")
    contested.add_negative_fact("Ann", "ancestor", "Cara", "family:denial")
    contested.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    conflict_result = contested.infer_relation(
        "Ann", "ancestor", "Cara", effort="thorough")
    require(conflict_result.status == "ambiguous"
            and any("conflicting or invalid support" in check
                    for check in conflict_result.effort_checks),
            "thorough conflict scan did not report explicit negative support")

    crowded_facts = [
        {"subject": f"E{index}", "relation": "owns", "object": f"O{index}",
         "sources": [f"source:{index}"], "qualifiers": []}
        for index in range(20)
    ]
    grounded_candidates = infer_relation(
        crowded_facts,
        [InferenceRule("r", "owns", "owns", "connected")],
        subject="E0", relation="connected", obj="O19",
        max_candidates=2)
    require(grounded_candidates.status == "unknown"
            and grounded_candidates.complete
            and grounded_candidates.limit_kind is None,
            "unrelated entities made an indexed, grounded search incomplete")
    recursive_candidates = infer_relation(
        crowded_facts,
        [InferenceRule("recursive", "connected", "connected", "connected")],
        subject="E0", relation="connected", obj="O19",
        max_candidates=2)
    require(not recursive_candidates.complete
            and recursive_candidates.limit_kind == "candidate_limit",
            "recursive broad search did not report the candidate cap")

    print("reasoning effort budgets: PASS")
    print("repeatability, stable proved conclusion, explicit completeness, "
          "candidate/depth bounds, and thorough checks: PASS")


if __name__ == "__main__":
    main()
