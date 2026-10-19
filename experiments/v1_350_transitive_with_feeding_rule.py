"""Prefer direct transitive fact paths before rule-fed edge expansion."""
from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for hops in range(2, 7):
        kb = CRMSKnowledgeBase()
        for i in range(hops):
            kb.add_fact(f"Node {i}", "connected to", f"Node {i + 1}",
                        f"edge:{i}")
        kb.add_fact("Node 0", "alias", "Other", "alias:source")
        kb.add_fact("Other", "connected to", "Node 0", "alias:edge")
        kb.add_inference_rule(
            "feed-connected", "alias", "connected to", "connected to")
        kb.add_relation_type("connected to", "transitive", "schema:connected")

        result = kb.infer_relation("Node 0", "connected to", f"Node {hops}")
        require(result.status == "answered" and result.proofs,
                f"{hops}-hop direct path did not prove: {result}")
        require(not result.complete,
                f"{hops}-hop direct proof omitted the open-alternatives flag")
        proof = result.proofs[0]
        require(all(item.get("kind") == "fact"
                    for item in proof.get("premises", [])),
                f"{hops}-hop first pass used a rule-fed edge")
        checked = verify_inference_proof(
            proof, [asdict(fact) for fact in kb.facts()],
            [asdict(rule) for rule in kb._inference_rules.values()],
            expected_conclusion=result.conclusion)
        require(checked.valid, f"direct path proof failed verification: {checked}")

    # The second pass remains available when a relation edge can only be
    # produced by a rule (capital-of plus located-in).
    derived = CRMSKnowledgeBase()
    derived.add_fact("Paris", "capital of", "France", "capital:source")
    derived.add_fact("France", "located in", "Europe", "location:source")
    derived.add_inference_rule(
        "capital-is-located-in", "capital of", "located in", "located in")
    derived.add_relation_type("located in", "transitive", "schema:location")
    result = derived.infer_relation("Paris", "located in", "Europe")
    require(result.status == "answered" and result.proofs,
            f"rule-derived edge was not tried after direct search: {result}")
    checked = verify_inference_proof(
        result.proofs[0], [asdict(fact) for fact in derived.facts()],
        [asdict(rule) for rule in derived._inference_rules.values()],
        expected_conclusion=result.conclusion)
    require(checked.valid, f"rule-fed proof failed verification: {checked}")

    absent = CRMSKnowledgeBase()
    absent.add_fact("A", "connected to", "B", "edge:a-b")
    absent.add_relation_type("connected to", "transitive", "schema:absent")
    unknown = absent.infer_relation("A", "connected to", "C")
    require(unknown.status == "unknown" and not unknown.proofs,
            f"unprovable path did not remain unknown: {unknown}")

    print("transitive direct-first path lengths 2-6: PASS (incomplete flagged)")
    print("rule-derived transitive edge fallback: PASS")
    print("unprovable conclusion remains unknown: PASS")


if __name__ == "__main__":
    main()
