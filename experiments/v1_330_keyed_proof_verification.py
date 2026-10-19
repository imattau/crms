"""Measure independent proof verification with full and keyed fact lookup."""

from __future__ import annotations

import statistics
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_rule_proof import _fact_signature, verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    count = 300_000
    proof_facts = [
        {"subject": left, "relation": "parent", "object": right,
         "sources": [f"source:{left}"], "qualifiers": []}
        for left, right in (("A", "B"), ("B", "C"), ("C", "D"))
    ]
    type_fact = {
        "subject": "parent", "relation": "has relation type",
        "object": "transitive", "sources": ["source:type"],
        "qualifiers": [],
    }
    facts = [
        {"subject": f"Entity {index}", "relation": "connected to",
         "object": f"Target {index}", "sources": [f"source:{index}"],
         "qualifiers": []}
        for index in range(count - len(proof_facts) - 1)
    ]
    facts.extend((*proof_facts, type_fact))

    def fact_proof(fact):
        return {"kind": "fact", "fact": fact,
                "conclusion": {key: fact[key]
                               for key in ("subject", "relation", "object")}}

    conclusion = {"subject": "A", "relation": "parent", "object": "D"}
    proof = {
        "kind": "schema", "schema_id": "transitivity-v1",
        "conclusion": conclusion,
        "schema": {
            "schema_id": "transitivity-v1", "schema_type": "transitive",
            "relation": "parent",
            "validation": {"status": "validated",
                           "validator": "builtin-schema-check-v1"},
        },
        "relation_type_fact": type_fact,
        "premises": [fact_proof(fact) for fact in proof_facts],
        "proof_form": "flat-chain-v1",
    }
    signatures = {_fact_signature(fact) for fact in facts}
    keyed_lookup = lambda fact: _fact_signature(fact) in signatures

    full_times = []
    keyed_times = []
    for _ in range(3):
        start = perf_counter()
        full = verify_inference_proof(
            proof, facts, [], expected_conclusion=conclusion, max_depth=64)
        full_times.append(perf_counter() - start)
        start = perf_counter()
        keyed = verify_inference_proof(
            proof, (), [], expected_conclusion=conclusion,
            fact_lookup=keyed_lookup, max_depth=64)
        keyed_times.append(perf_counter() - start)
        require(full == keyed and keyed.valid,
                f"verification paths disagree: full={full}; keyed={keyed}")

    altered = dict(proof_facts[0], sources=["source:forged"])
    forged = {**proof, "premises": [fact_proof(altered), *proof["premises"][1:]]}
    rejected = verify_inference_proof(
        forged, (), [], expected_conclusion=conclusion,
        fact_lookup=keyed_lookup, max_depth=64)
    require(not rejected.valid, "keyed verifier accepted altered provenance")

    print(f"keyed proof verification at {count:,} facts: PASS")
    print(f"full-snapshot median={statistics.median(full_times) * 1000:.2f} ms; "
          f"keyed lookup median={statistics.median(keyed_times) * 1000:.3f} ms")
    print("three-edge transitive proof: full and keyed outcomes agree; "
          "altered provenance rejected")


if __name__ == "__main__":
    main()
