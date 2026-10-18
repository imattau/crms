"""Check recursive backward chaining, proof trees, and cycle termination."""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_inference import InferenceRule, infer_relation
from crms_rule_proof import verify_inference_proof


def main() -> None:
    facts = [
        {"subject": "Ada", "relation": "parent", "object": "Bea", "sources": ["f1"]},
        {"subject": "Bea", "relation": "parent", "object": "Cal", "sources": ["f2"]},
        {"subject": "Cal", "relation": "employed_by", "object": "Acme", "sources": ["f3"]},
    ]
    rules = [
        InferenceRule("parent-transitivity", "parent", "parent", "ancestor"),
        InferenceRule("ancestor-employer", "ancestor", "employed_by",
                      "ancestor_employed_by"),
    ]
    result = infer_relation(
        facts, rules, subject="Ada", relation="ancestor_employed_by", obj="Acme")
    if result.status != "answered" or len(result.proofs) != 1:
        raise SystemExit(f"recursive conclusion was not derived: {result}")
    valid = verify_inference_proof(
        result.proofs[0], facts, [asdict(rule) for rule in rules],
        expected_conclusion=result.conclusion)
    if not valid.valid:
        raise SystemExit(f"independent checker rejected nested proof: {valid}")
    if infer_relation(facts, rules, subject="Ada", relation="ancestor_employed_by",
                      obj="Acme", max_depth=1).status != "unknown":
        raise SystemExit("depth exhaustion returned a partial proof")

    cyclic_rules = [
        InferenceRule("recursive-only", "ancestor", "parent", "ancestor")]
    cycle = infer_relation(facts, cyclic_rules, subject="Ada", relation="ancestor",
                           obj="Cal")
    if cycle.status != "unknown":
        raise SystemExit(f"unsupported cyclic rule produced a conclusion: {cycle}")

    forged = dict(result.proofs[0])
    forged["premises"] = list(forged["premises"])
    forged["premises"][0] = dict(forged["premises"][0])
    forged["premises"][0]["conclusion"] = {
        "subject": "Ada", "relation": "unrelated", "object": "Bea"}
    invalid = verify_inference_proof(
        forged, facts, [asdict(rule) for rule in rules],
        expected_conclusion=result.conclusion)
    if invalid.valid:
        raise SystemExit("independent checker accepted a tampered nested premise")
    print("recursive backward-chaining diagnostic: PASS")
    print("nested rule proof, independent verification, depth abstention, cycle termination, tamper rejection: PASS")


if __name__ == "__main__":
    main()
