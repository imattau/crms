"""Check long transitive paths independently of rule nesting depth."""
from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_inference import infer_relation as infer_proof_relation
from crms_rule_proof import verify_inference_proof
from crms_text import tokens


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

    # A broader rule set retains the old honest partial-support behavior: the
    # optimization below must decline to prune when the closure pair is not
    # the complete set of rules for the conclusion relation.
    recursive = CRMSKnowledgeBase()
    for index in range(99):
        recursive.add_fact(f"Person {index}", "parent", f"Person {index + 1}",
                           f"family:{index}")
    recursive.add_inference_rule(
        "parent-recursion", "parent", "ancestor", "ancestor")
    recursive.add_inference_rule(
        "parent-base", "parent", "parent", "ancestor")
    recursive.add_inference_rule(
        "alternate-ancestor", "other-first", "other-second", "ancestor")
    result = recursive.infer_relation("Person 0", "ancestor", "Person 5")
    require(result.status == "answered" and result.proofs,
            f"a found recursive proof was discarded after a depth-limited branch: {result}")
    require(not result.complete and result.support_class == "partial"
            and result.limit_kind == "depth_limit",
            "unsupported pruning hid incomplete alternative enumeration")
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

    pruned = CRMSKnowledgeBase()
    for index in range(99):
        pruned.add_fact(f"Person {index}", "parent", f"Person {index + 1}",
                        f"pruned:{index}")
    pruned.add_inference_rule(
        "parent-recursion", "parent", "ancestor", "ancestor")
    pruned.add_inference_rule(
        "parent-base", "parent", "parent", "ancestor")
    pruned_result = pruned.infer_relation("Person 0", "ancestor", "Person 5")
    require(pruned_result.status == "answered" and pruned_result.complete
            and pruned_result.limit_kind is None and pruned_result.expansions < 100,
            f"target-unreachable branches were not safely pruned: {pruned_result}")
    pruned_check = verify_inference_proof(
        pruned_result.proofs[0], [asdict(fact) for fact in pruned.facts()],
        [asdict(rule) for rule in pruned._inference_rules.values()],
        expected_conclusion=pruned_result.conclusion)
    require(pruned_check.valid,
            f"independent verifier rejected target-pruned proof: {pruned_check}")
    bounded_pruning = pruned.infer_relation(
        "Person 0", "ancestor", "Person 5", max_expansions=1)
    require(bounded_pruning.status == "unknown"
            and not bounded_pruning.complete
            and bounded_pruning.limit_kind == "expansion_limit",
            f"target reachability scan escaped the expansion bound: {bounded_pruning}")
    retained = pruned.practice_relation(
        "Person 0", "ancestor", "Person 5")
    require(retained.status == "answered" and retained.complete
            and pruned.retrieve_derived_case(
                "Person 0", "ancestor", "Person 5") is not None,
            "complete target-pruned proof was not retained as a derived case")

    # A verified cached closure edge is a reachability anchor; its upstream
    # parent path must remain eligible even when it is not itself parent-derived.
    anchored = CRMSKnowledgeBase()
    for index in range(4):
        anchored.add_fact(f"A{index}", "parent", f"A{index + 1}",
                          f"anchor:parent:{index}")
    anchored.add_inference_rule(
        "anchor-parent-recursion", "parent", "ancestor", "ancestor")
    anchored.add_inference_rule(
        "anchor-parent-base", "parent", "parent", "ancestor")
    cached_anchor = anchored.infer_relation("A2", "ancestor", "A4")
    require(cached_anchor.status == "answered" and cached_anchor.complete
            and cached_anchor.proofs,
            f"could not create verified closure-edge anchor: {cached_anchor}")
    anchor_key = (tokens("A2"), tokens("ancestor"), tokens("A4"))
    anchored_result = infer_proof_relation(
        [asdict(fact) for fact in anchored.facts()],
        list(anchored._inference_rules.values()),
        subject="A0", relation="ancestor", obj="A4",
        verified_derived_proofs={anchor_key: cached_anchor.proofs})
    require(anchored_result.status == "answered" and anchored_result.complete
            and anchored_result.proofs,
            f"a verified closure-edge anchor was pruned: {anchored_result}")
    anchored_check = verify_inference_proof(
        anchored_result.proofs[0],
        [asdict(fact) for fact in anchored.facts()],
        [asdict(rule) for rule in anchored._inference_rules.values()],
        expected_conclusion=anchored_result.conclusion)
    require(anchored_check.valid,
            f"independent verifier rejected anchored recursive proof: {anchored_check}")

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
    print("partial-support disclosure remains for broader, unoptimized rule sets: PASS")
    print("target-directed pruning proves short recursive goals completely: PASS")
    print(f"overlapping recursive subgoals reused ({memoized.memo_hits} memo hits): PASS")
    print("fact retraction is visible to the next inference call: PASS")
    print(f"ten-layer diamond: {len(branching.proofs)} shortest proof records; PASS")
    print("transitive search selects the two-edge proof before a longer path: PASS")


if __name__ == "__main__":
    main()
