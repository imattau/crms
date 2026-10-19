"""Check useful recursive reasoning beyond the former default depth of eight."""

from __future__ import annotations

from dataclasses import asdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def add_ancestor_rules(kb: CRMSKnowledgeBase) -> list[object]:
    return [
        kb.add_inference_rule("ancestor-base", "parent", "parent", "ancestor"),
        kb.add_inference_rule("ancestor-recursive", "parent", "ancestor", "ancestor"),
    ]


def main() -> None:
    chain = CRMSKnowledgeBase()
    for index in range(35):
        chain.add_fact(f"C{index}", "parent", f"C{index + 1}", f"chain:{index}")
    rules = add_ancestor_rules(chain)
    twelve_hops = chain.infer_relation("C0", "ancestor", "C12")
    require(twelve_hops.status == "answered" and twelve_hops.complete
            and twelve_hops.proofs,
            f"12-hop recursive proof failed at default depth: {twelve_hops}")
    facts = [asdict(fact) for fact in chain.facts()]
    rule_rows = [asdict(rule) for rule in rules]
    for proof in twelve_hops.proofs:
        checked = verify_inference_proof(
            proof, facts, rule_rows, expected_conclusion=twelve_hops.conclusion)
        require(checked.valid, f"independent verifier rejected 12-hop proof: {checked}")

    thirty_five_hops = chain.infer_relation("C0", "ancestor", "C35")
    require(thirty_five_hops.status == "answered" and thirty_five_hops.complete
            and thirty_five_hops.proofs,
            f"35-hop recursive proof failed at default depth: {thirty_five_hops}")
    for proof in thirty_five_hops.proofs:
        checked = verify_inference_proof(
            proof, facts, rule_rows,
            expected_conclusion=thirty_five_hops.conclusion)
        require(checked.valid, f"independent verifier rejected 35-hop proof: {checked}")

    bounded = chain.infer_relation("C0", "ancestor", "C12", max_depth=8)
    require(bounded.status == "unknown" and not bounded.complete
            and bounded.reason_code == "search_limit"
            and bounded.limit_kind == "depth_limit",
            f"explicit shallow depth was not reported as incomplete: {bounded}")

    # A 2,047-node binary tree has a nine-edge path to this leaf. This guards
    # against a default that works only for narrow chains.
    tree = CRMSKnowledgeBase()
    node_count = 2047
    for index in range(node_count):
        for child in (2 * index + 1, 2 * index + 2):
            if child < node_count:
                tree.add_fact(f"T{index}", "parent", f"T{child}",
                              f"tree:{index}:{child}")
    tree_rules = add_ancestor_rules(tree)
    depth_nine = tree.infer_relation("T0", "ancestor", "T1022")
    require(depth_nine.status == "answered" and depth_nine.complete
            and depth_nine.proofs,
            f"depth-nine tree proof failed at default depth: {depth_nine}")
    tree_facts = [asdict(fact) for fact in tree.facts()]
    tree_rule_rows = [asdict(rule) for rule in tree_rules]
    for proof in depth_nine.proofs:
        checked = verify_inference_proof(
            proof, tree_facts, tree_rule_rows, expected_conclusion=depth_nine.conclusion)
        require(checked.valid, f"independent verifier rejected tree proof: {checked}")

    print("recursive reasoning default depth (12/35-hop chain, depth-9 tree): PASS")
    print("explicit max_depth=8 abstains with a depth-limit reason: PASS")
    print(f"12-hop proofs={len(twelve_hops.proofs)}; 35-hop proofs={len(thirty_five_hops.proofs)}; "
          f"tree proofs={len(depth_nine.proofs)}")


if __name__ == "__main__":
    main()
