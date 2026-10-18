"""Reuse practiced proof trees as bounded intermediate inference proofs."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "parent", "Bea", "source:family-a")
    kb.add_fact("Bea", "parent", "Cal", "source:family-b")
    kb.add_fact("Cal", "located in", "Rome", "source:location")
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    kb.add_inference_rule("ancestor-city", "ancestor", "located in",
                          "family located in")

    practiced = kb.practice_relation("Ada", "ancestor", "Cal")
    if practiced.status != "answered":
        raise SystemExit("intermediate proof practice failed")

    cached = kb.infer_relation("Ada", "family located in", "Rome")
    baseline = copy.deepcopy(kb)
    baseline._derived_cases.clear()
    uncached = baseline.infer_relation(
        "Ada", "family located in", "Rome")
    if (cached.status != "answered" or uncached.status != "answered"
            or cached.conclusion != uncached.conclusion):
        raise SystemExit("subgoal reuse changed the inferred answer")
    if cached.expansions >= uncached.expansions:
        raise SystemExit(
            f"derived subgoal did not reduce search work: cached={cached.expansions}, "
            f"uncached={uncached.expansions}")

    facts = [item.__dict__ for item in kb.facts()]
    rules = [item.__dict__ for item in kb._inference_rules.values()]
    for proof in cached.proofs:
        if not verify_inference_proof(
                proof, facts, rules,
                expected_conclusion=cached.conclusion).valid:
            raise SystemExit("reused proof failed independent validation")

        def check_leaves(node: dict) -> None:
            if node.get("kind") == "fact":
                return
            if node.get("kind") != "rule":
                raise SystemExit("derived artifact leaked in as a proof leaf")
            for premise in node.get("premises", []):
                check_leaves(premise)

        check_leaves(proof)

    # Any inference-relevant change disables all cached subgoal shortcuts.
    kb.add_negative_fact("Ada", "parent", "Bea", "source:counter")
    conflicted = kb.infer_relation("Ada", "family located in", "Rome")
    if conflicted.status != "ambiguous":
        raise SystemExit("changed negative evidence did not invalidate subgoal reuse")

    print("derived subgoal reuse diagnostic: PASS")
    print("different-query reuse, lower search expansions, proof expansion, snapshot invalidation: PASS")


if __name__ == "__main__":
    main()
