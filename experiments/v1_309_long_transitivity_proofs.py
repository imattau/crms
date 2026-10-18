"""Check long transitive paths independently of rule nesting depth."""
from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for hops in (2, 8, 9, 12, 20, 30):
        kb = CRMSKnowledgeBase()
        for index in range(hops):
            kb.add_fact(f"Node {index}", "located in", f"Node {index + 1}",
                        f"edge:{index}")
        kb.add_relation_type("located in", "transitive", "schema:transitive")

        result = kb.infer_relation("Node 0", "located in", f"Node {hops}")
        require(result.status == "answered" and result.complete and result.proofs,
                f"{hops}-edge transitive chain did not prove at default bounds: {result}")
        proof = result.proofs[0]
        require(proof.get("proof_form") == "flat-chain-v1"
                and len(proof.get("premises", [])) == hops,
                f"{hops}-edge proof was not represented as a flat chain")
        checked = verify_inference_proof(
            proof, [asdict(fact) for fact in kb.facts()], [],
            expected_conclusion=result.conclusion)
        require(checked.valid,
                f"independent verifier rejected {hops}-edge proof: {checked}")

    # A recursive proof can be found even when exhaustive alternative-proof
    # enumeration explores an unrelated branch to the search limit. Preserve
    # the verified positive conclusion, label its search incomplete, and keep
    # it out of persistent practice memory.
    recursive = CRMSKnowledgeBase()
    for index in range(39):
        recursive.add_fact(f"Person {index}", "parent", f"Person {index + 1}",
                           f"family:{index}")
    recursive.add_inference_rule(
        "parent-recursion", "parent", "ancestor", "ancestor")
    recursive.add_inference_rule(
        "parent-base", "parent", "parent", "ancestor")
    result = recursive.infer_relation("Person 0", "ancestor", "Person 5")
    require(result.status == "answered" and result.proofs,
            f"a found recursive proof was discarded after a depth-limited branch: {result}")
    require(not result.complete and result.support_class == "partial",
            "incomplete alternative enumeration was reported as complete support")
    checked = verify_inference_proof(
        result.proofs[0], [asdict(fact) for fact in recursive.facts()],
        [asdict(rule) for rule in recursive._inference_rules.values()],
        expected_conclusion=result.conclusion)
    require(checked.valid,
            f"independent verifier rejected the recursive proof: {checked}")
    rendered = recursive.render_inference(result)
    require("but the search limit prevented enumerating all supporting proofs"
            in rendered,
            "partial proof status was not explained in the rendered result")
    practiced = recursive.practice_relation(
        "Person 0", "ancestor", "Person 5")
    require(practiced.status == "answered" and not practiced.complete
            and recursive.retrieve_derived_case(
                "Person 0", "ancestor", "Person 5") is None,
            "partial proof was incorrectly persisted as a complete practiced result")

    diamond = CRMSKnowledgeBase()
    previous = ["Start"]
    for layer in range(10):
        current = ([f"Layer {layer} A", f"Layer {layer} B"]
                   if layer < 9 else ["Finish"])
        for source in previous:
            for target in current:
                diamond.add_fact(source, "connects to", target,
                                 f"edge:{source}:{target}")
        previous = current
    diamond.add_relation_type("connects to", "transitive", "schema:diamond")
    branching = diamond.infer_relation("Start", "connects to", "Finish")
    require(branching.status == "answered" and branching.proofs,
            f"ten-layer diamond did not prove at default depth: {branching}")
    checked = verify_inference_proof(
        branching.proofs[0], [asdict(fact) for fact in diamond.facts()], [],
        expected_conclusion=branching.conclusion)
    require(checked.valid,
            f"independent verifier rejected a diamond proof: {checked}")

    print("long transitive proof diagnostic: PASS")
    print("2, 8, 9, 12, 20, and 30-edge paths proved and independently verified")
    print("recursive proof retained with an explicit partial-support label: PASS")
    print(f"ten-layer diamond: {len(branching.proofs)} verified proof paths; PASS")


if __name__ == "__main__":
    main()
