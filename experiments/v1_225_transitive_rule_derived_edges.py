"""Check transitive schemas can consume independently proved rule edges."""
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


def build(*, declare_transitive: bool = True) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    kb.add_fact("A", "part", "M", "source:part")
    kb.add_fact("M", "follows", "B", "source:follows")
    kb.add_fact("B", "precedes", "C", "source:direct-edge")
    if declare_transitive:
        kb.add_relation_type("precedes", "transitive", "source:schema")
    kb.add_inference_rule("part-follow", "part", "follows", "precedes")
    return kb


def main() -> None:
    kb = build()
    result = kb.infer_relation("A", "precedes", "C")
    require(result.status == "answered" and result.complete and result.proofs,
            f"transitivity did not compose a rule-derived edge: {result}")
    proof = result.proofs[0]
    require(proof.get("kind") == "schema"
            and proof.get("schema", {}).get("schema_id") == "transitivity-v1"
            and proof["premises"][0].get("kind") == "rule",
            f"derived relation edge was not retained in the schema proof: {proof}")
    checked = verify_inference_proof(
        proof, [asdict(fact) for fact in kb.facts()],
        [asdict(rule) for rule in kb._inference_rules.values()],
        expected_conclusion=result.conclusion)
    require(checked.valid, f"independent checker rejected mixed proof: {checked}")
    require(set(result.source_documents)
            == {"source:part", "source:follows", "source:direct-edge",
                "source:schema"},
            f"mixed proof lost source provenance: {result.source_documents}")

    absent_license = build(declare_transitive=False).infer_relation(
        "A", "precedes", "C")
    require(absent_license.status == "unknown" and absent_license.complete
            and absent_license.reason_code == "no_proof",
            "rule-derived edge composition bypassed the explicit schema license")

    depth_limited = build().infer_relation(
        "A", "precedes", "C", max_depth=1)
    require(depth_limited.status == "unknown" and not depth_limited.complete
            and depth_limited.reason_code == "search_limit",
            f"mixed proof leaked through the depth bound: {depth_limited}")
    expansion_limited = build().infer_relation(
        "A", "precedes", "C", max_expansions=1)
    require(expansion_limited.status == "unknown"
            and not expansion_limited.complete
            and expansion_limited.reason_code == "search_limit",
            f"mixed proof leaked through the expansion bound: {expansion_limited}")

    conflicted = build()
    conflicted.add_negative_fact("A", "precedes", "C", "source:negative")
    conflict = conflicted.infer_relation("A", "precedes", "C")
    require(conflict.status == "ambiguous" and conflict.complete,
            "negative evidence did not contest a mixed transitive proof")

    print("transitivity over rule-derived edges: PASS")
    print("mixed proof verification, provenance, explicit license, depth/expansion abstention, contradiction: PASS")


if __name__ == "__main__":
    main()
