"""Keep relation-schema vocabulary and proof metadata in one checked registry."""

from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof
from crms_schema import (
    DERIVATION_SCHEMA_TYPES, INTEGRITY_SCHEMA_TYPES, PROOF_SCHEMA_SPECS,
    RELATION_SCHEMA_SPECS, RELATION_SCHEMA_TYPES,
    WITNESS_CONSTRAINT_DENIAL_TYPES, relation_schema_spec,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    expected_types = {
        "transitive", "symmetric", "irreflexive", "asymmetric", "functional",
        "closed-world",
    }
    require(RELATION_SCHEMA_TYPES == expected_types,
            f"registry vocabulary drifted: {RELATION_SCHEMA_TYPES}")
    require(DERIVATION_SCHEMA_TYPES == {"transitive", "symmetric"}
            and INTEGRITY_SCHEMA_TYPES == expected_types - {
                "transitive", "symmetric"},
            "schema categories do not separate derivation from integrity")
    require(set(PROOF_SCHEMA_SPECS) == {"transitivity-v1", "symmetry-v1"},
            "proof registry exposes an unsupported built-in schema")
    require(WITNESS_CONSTRAINT_DENIAL_TYPES == {
                "irreflexive", "asymmetric", "functional"},
            "constraint-denial evidence modes changed unexpectedly")
    require(relation_schema_spec("closed world") is
            relation_schema_spec("closed-world"),
            "closed-world surface forms do not normalize to one schema")

    kb = CRMSKnowledgeBase()
    for number, spec in enumerate(RELATION_SCHEMA_SPECS):
        relation = f"schema relation {number}"
        kb.add_relation_type(relation, spec.name, f"schema:{spec.name}")
        candidate = CRMSKnowledgeBase._propose_explicit_relation_type(
            f'The relation "{relation}" is {spec.name.replace("-", " ")}.',
            f"proposal:{spec.name}")
        require(candidate is not None
                and candidate.object == spec.name,
                f"registered schema did not parse: {spec.name}")
    require(set(kb._inference_relation_names()) == {
                f"schema relation {number}"
                for number in range(len(RELATION_SCHEMA_SPECS))},
            "relation discovery omitted a registered schema type")
    try:
        kb.add_relation_type("unknown relation", "almost transitive", "bad")
    except ValueError:
        pass
    else:
        raise SystemExit("unregistered schema type was accepted")

    for relation, schema, edges, query in (
            ("related to", "symmetric", (("A", "B"),), ("B", "A")),
            ("ancestor of", "transitive", (("A", "B"), ("B", "C")),
             ("A", "C"))):
        proof_kb = CRMSKnowledgeBase()
        for index, (subject, obj) in enumerate(edges):
            proof_kb.add_fact(subject, relation, obj, f"edge:{index}")
        proof_kb.add_relation_type(relation, schema, f"schema:{schema}")
        result = proof_kb.infer_relation(query[0], relation, query[1])
        require(result.status == "answered" and result.proofs,
                f"registered {schema} schema did not derive its claim: {result}")
        check = verify_inference_proof(
            result.proofs[0], [asdict(fact) for fact in proof_kb.facts()],
            [asdict(rule) for rule in proof_kb._inference_rules.values()],
            expected_conclusion=result.conclusion)
        require(check.valid,
                f"independent verifier rejected registered {schema} proof: {check}")
        tampered = copy.deepcopy(result.proofs[0])
        tampered["proof_form"] = "unregistered-proof-form"
        rejected = verify_inference_proof(
            tampered, [asdict(fact) for fact in proof_kb.facts()],
            [asdict(rule) for rule in proof_kb._inference_rules.values()],
            expected_conclusion=result.conclusion)
        require(not rejected.valid,
                f"independent verifier accepted unknown proof form for {schema}")

    print("single relation-schema registry covers vocabulary and categories: PASS")
    print("parser, explicit teaching, relation discovery, and aliases: PASS")
    print("transitive and symmetric proofs remain independently verifiable: PASS")
    print("unsupported schema names are rejected: PASS")


if __name__ == "__main__":
    main()
