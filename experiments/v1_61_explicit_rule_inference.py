"""Runtime checks for bounded, proof-producing explicit rule inference."""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_inference import InferenceRule, infer_relation
from crms_rule_proof import verify_inference_proof


def main() -> None:
    facts = [
        {"subject": "Ada", "relation": "parent", "object": "Bea", "sources": ["s1"]},
        {"subject": "Bea", "relation": "parent", "object": "Cal", "sources": ["s2"]},
        {"subject": "Bea", "relation": "sibling", "object": "Dee", "sources": ["s3"]},
        {"subject": "Bea", "relation": "parent", "object": "Eli", "sources": ["s4"]},
    ]
    rules = [InferenceRule("transitive-parent", "parent", "parent", "ancestor")]
    result = infer_relation(facts, rules, subject="Ada", relation="ancestor", obj="Cal")
    if result.status != "answered" or len(result.proofs) != 1:
        raise SystemExit(f"valid conclusion was not derived: {result}")
    rule_rows = [asdict(rule) for rule in rules]
    check = verify_inference_proof(
        result.proofs[0], facts, rule_rows, expected_conclusion=result.conclusion)
    if not check.valid:
        raise SystemExit(f"independent verifier rejected proof: {check}")
    absent = infer_relation(facts, rules, subject="Ada", relation="ancestor", obj="Dee")
    if (absent.status != "unknown" or not absent.complete
            or absent.reason_code != "no_proof"):
        raise SystemExit("disconnected near-miss was incorrectly inferred")
    negative = [{"subject": "Ada", "relation": "ancestor", "object": "Cal", "sources": ["n1"]}]
    if infer_relation(facts, rules, subject="Ada", relation="ancestor", obj="Cal",
                      negative_facts=negative).status != "ambiguous":
        raise SystemExit("derived positive plus explicit negative was not ambiguous")
    limited = infer_relation(facts, rules, subject="Ada", relation="ancestor", obj="Cal",
                             max_expansions=1)
    if (limited.status != "unknown" or limited.complete
            or limited.reason_code != "search_limit"):
        raise SystemExit("search-limit outcome was not marked incomplete")
    contextual_facts = [
        {"subject": "Ada", "relation": "parent", "object": "Bea",
         "sources": ["s1"], "qualifiers": (("time", "2020"),)},
        {"subject": "Bea", "relation": "parent", "object": "Cal",
         "sources": ["s2"], "qualifiers": (("time", "2021"),)},
    ]
    if infer_relation(contextual_facts, rules, subject="Ada", relation="ancestor",
                      obj="Cal").status != "unknown":
        raise SystemExit("qualified facts were combined without context semantics")
    forged = dict(result.proofs[0])
    forged["conclusion"] = {"subject": "Ada", "relation": "ancestor", "object": "Dee"}
    if verify_inference_proof(forged, facts, rule_rows).valid:
        raise SystemExit("independent verifier accepted forged endpoint")
    forged = dict(result.proofs[0])
    forged["rule"] = {**forged["rule"], "conclusion_relation": "owns"}
    if verify_inference_proof(forged, facts, rule_rows).valid:
        raise SystemExit("independent verifier accepted untrusted rule")
    print("explicit rule inference diagnostic: PASS")
    print("derived proof, independent checking, near-miss abstention, contradiction, budget, tamper rejection: PASS")


if __name__ == "__main__":
    main()
