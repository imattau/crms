"""Check that rule discovery reports and ranks support coverage."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    kb = CRMSKnowledgeBase()
    for index in range(20):
        subject = f"Researcher {index:02d}"
        middle = f"Colleague {index:02d}"
        target = f"Project {index:02d}"
        source = f"fixture:chain:{index:02d}"
        kb.add_fact(subject, "works with", middle, source)
        kb.add_fact(middle, "lives near", target, source)
        if index < 2:
            kb.add_fact(subject, "admires", target, source)
        if index < 18:
            kb.add_fact(subject, "trusts", target, source)

    result = kb.discover_inference_rules()
    candidates = [candidate for candidate in result.candidates
                  if (candidate.first_relation, candidate.second_relation)
                  == ("works with", "lives near")]
    by_conclusion = {candidate.conclusion_relation: candidate
                     for candidate in candidates}
    rare = by_conclusion.get("admires")
    common = by_conclusion.get("trusts")
    if rare is None or common is None:
        raise SystemExit(f"missing expected candidates: {candidates}")
    if (rare.status != "uncontradicted"
            or common.status != "uncontradicted"
            or rare.possible_examples != 20
            or common.possible_examples != 20
            or rare.support_coverage != 0.1
            or common.support_coverage != 0.9):
        raise SystemExit(
            "candidate support coverage did not distinguish 2/20 from 18/20: "
            f"rare={rare}; common={common}")
    if candidates[0].conclusion_relation != "trusts":
        raise SystemExit(
            "rule candidates were not ranked by observed support coverage: "
            f"{[candidate.conclusion_relation for candidate in candidates]}")

    rendered = kb.render_rule_discovery(result)
    if "coverage=18/20 (90.0%)" not in rendered or "coverage=2/20 (10.0%)" not in rendered:
        raise SystemExit(f"rule discovery hid coverage from the user:\n{rendered}")

    limited = kb.discover_inference_rules(max_expansions=3)
    partial = next((candidate for candidate in limited.candidates
                    if (candidate.first_relation, candidate.second_relation,
                        candidate.conclusion_relation)
                    == ("works with", "lives near", "admires")), None)
    if partial is not None and partial.support_coverage is not None:
        raise SystemExit(
            "incomplete search presented partial support as complete coverage")

    print("rule coverage ranking: PASS; 18/20 ranks above 2/20")
    print("incomplete-search coverage labeling: PASS")


if __name__ == "__main__":
    main()
