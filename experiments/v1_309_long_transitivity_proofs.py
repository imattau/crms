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
    # The current default recursion depth is 40. Keep the irrelevant branch
    # long enough that exhaustive alternatives still hit that bound while
    # the six-edge target proof is already available.
    for index in range(99):
        recursive.add_fact(f"Person {index}", "parent", f"Person {index + 1}",
                           f"family:{index}")
    recursive.add_inference_rule(
        "parent-recursion", "parent", "ancestor", "ancestor")
    recursive.add_inference_rule(
        "parent-base", "parent", "parent", "ancestor")
    result = recursive.infer_relation("Person 0", "ancestor", "Person 5")
    require(result.status == "answered" and result.proofs,
            f"a found recursive proof was discarded after a depth-limited branch: {result}")
    require(not result.complete and result.support_class == "partial"
            and result.limit_kind == "depth_limit",
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

    # Two recursive branches converge on the same subgoal. Query-local
    # memoization should reuse that complete positive proof set.
    overlapping = CRMSKnowledgeBase()
    for source, target in (
            ("Root", "Left"), ("Root", "Right"),
            ("Left", "Join"), ("Right", "Join"),
            ("Join", "Next"), ("Next", "End")):
        overlapping.add_fact(source, "parent", target,
                             f"family:{source}:{target}")
    overlapping.add_inference_rule(
        "ancestor-recursive", "parent", "ancestor", "ancestor")
    overlapping.add_inference_rule(
        "ancestor-base", "parent", "parent", "ancestor")
    memoized = overlapping.infer_relation("Root", "ancestor", "End")
    require(memoized.status == "answered" and memoized.proofs
            and memoized.memo_hits > 0,
            f"overlapping recursive subgoals were not memoized: {memoized}")
    checked = verify_inference_proof(
        memoized.proofs[0], [asdict(fact) for fact in overlapping.facts()],
        [asdict(rule) for rule in overlapping._inference_rules.values()],
        expected_conclusion=memoized.conclusion)
    require(checked.valid,
            f"independent verifier rejected memoized proof: {checked}")
    require(overlapping.remove_fact(
        "Join", "parent", "Next", "family:Join:Next"),
        "could not retract the shared subgoal's supporting edge")
    after_retraction = overlapping.infer_relation(
        "Root", "ancestor", "End")
    require(after_retraction.status == "unknown"
            and not after_retraction.proofs,
            "a new inference call reused a stale query-local proof cache")

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
    require(branching.status == "answered" and len(branching.proofs) == 64
            and not branching.complete and branching.limit_kind == "proof_limit",
            f"ten-layer diamond did not prove at default depth: {branching}")
    checked = verify_inference_proof(
        branching.proofs[0], [asdict(fact) for fact in diamond.facts()], [],
        expected_conclusion=branching.conclusion)
    require(checked.valid,
            f"independent verifier rejected a diamond proof: {checked}")

    shortest = CRMSKnowledgeBase()
    for source, target, citation in (
            ("Start", "A", "edge:start-a"),
            ("A", "Finish", "edge:a-finish"),
            ("Start", "B", "edge:start-b"),
            ("B", "C", "edge:b-c"),
            ("C", "Finish", "edge:c-finish")):
        shortest.add_fact(source, "reaches", target, citation)
    shortest.add_relation_type("reaches", "transitive", "schema:shortest")
    shortest_result = shortest.infer_relation("Start", "reaches", "Finish")
    require(shortest_result.status == "answered" and shortest_result.proofs
            and all(len(proof.get("premises", [])) == 2
                    for proof in shortest_result.proofs),
            "transitive search returned a longer proof before the shortest path")
    expansion_limited = shortest.infer_relation(
        "Start", "reaches", "Finish", max_expansions=1)
    require(expansion_limited.status == "unknown"
            and expansion_limited.limit_kind == "expansion_limit",
            f"candidate expansion limit was not identified: {expansion_limited}")

    print("long transitive proof diagnostic: PASS")
    print("2, 8, 9, 12, 20, and 30-edge paths proved and independently verified")
    print("recursive proof retained with an explicit partial-support label: PASS")
    print(f"overlapping recursive subgoals reused ({memoized.memo_hits} memo hits): PASS")
    print("fact retraction is visible to the next inference call: PASS")
    print(f"ten-layer diamond: {len(branching.proofs)} shortest proof records; PASS")
    print("transitive search selects the two-edge proof before a longer path: PASS")


if __name__ == "__main__":
    main()
