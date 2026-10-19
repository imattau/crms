"""Deterministic outcome and resource baseline across reasoning graph shapes.

Elapsed time and tracemalloc peak are diagnostic values, not pass thresholds.
The experiment gates semantic status, completeness, limits, and proof validity.
"""

from __future__ import annotations

from dataclasses import asdict
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_constraint_denial, verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def ancestor_rules(kb: CRMSKnowledgeBase) -> list[object]:
    return [
        kb.add_inference_rule("ancestor-base", "parent", "parent", "ancestor"),
        kb.add_inference_rule("ancestor-recursive", "parent", "ancestor", "ancestor"),
    ]


def measure(label: str, kb: CRMSKnowledgeBase, subject: str, relation: str,
            obj: str, *, max_expansions: int = 100_000,
            max_depth: int = 40) -> tuple[dict[str, object], object]:
    tracemalloc.start()
    started = time.perf_counter_ns()
    result = kb.infer_relation(
        subject, relation, obj,
        max_expansions=max_expansions, max_depth=max_depth)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    row: dict[str, object] = {
        "case": label,
        "status": result.status,
        "complete": result.complete,
        "max_depth": max_depth,
        "max_expansions": max_expansions,
        "expansions": result.expansions,
        "proofs": len(result.proofs or ()),
        "shortest_proof_depth": min(
            (proof_depth(proof) for proof in result.proofs or ()), default=None),
        "reason": result.reason_code,
        "limit": result.limit_kind,
        "elapsed_ms": round(elapsed_ms, 3),
        "peak_kib": round(peak_bytes / 1024, 1),
    }
    return row, result


def proof_depth(proof: object) -> int:
    if not isinstance(proof, dict):
        return 0
    premises = proof.get("premises", [])
    if proof.get("proof_form") == "flat-chain-v1":
        return len(premises) if isinstance(premises, list) else 0
    if proof.get("kind") == "fact" or not isinstance(premises, list) or not premises:
        return 0
    return 1 + max((proof_depth(item) for item in premises), default=0)


def semantic_signature(result: object) -> tuple[object, ...]:
    return (result.status, result.complete, result.expansions,
            len(result.proofs or ()), result.reason_code, result.limit_kind,
            repr(result.conclusion), result.request,
            tuple(json.dumps(proof, sort_keys=True, ensure_ascii=False)
                  for proof in result.proofs or ()))


def check_deterministic(label: str, kb: CRMSKnowledgeBase,
                        subject: str, relation: str, obj: str,
                        first: object, *, max_expansions: int = 100_000,
                        max_depth: int = 40) -> None:
    replay = kb.infer_relation(
        subject, relation, obj,
        max_expansions=max_expansions, max_depth=max_depth)
    require(semantic_signature(first) == semantic_signature(replay),
            f"{label} changed its semantic result on replay: "
            f"{semantic_signature(first)} != {semantic_signature(replay)}")


def verify_all(kb: CRMSKnowledgeBase, result: object) -> None:
    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(rule) for rule in kb._inference_rules.values()]
    for proof in result.proofs or ():
        check = verify_inference_proof(
            proof, facts, rules, expected_conclusion=result.conclusion)
        require(check.valid,
                f"independent verifier rejected benchmark proof: {check}")


def main() -> None:
    cases: list[tuple[str, CRMSKnowledgeBase, str, str, str, dict[str, int]]] = []

    chain = CRMSKnowledgeBase()
    for index in range(35):
        chain.add_fact(f"C{index}", "parent", f"C{index + 1}",
                       f"chain:{index}")
    ancestor_rules(chain)
    cases.append(("recursive-chain-35", chain, "C0", "ancestor", "C35", {}))

    tree = CRMSKnowledgeBase()
    for index in range(2047):
        for child in (2 * index + 1, 2 * index + 2):
            if child < 2047:
                tree.add_fact(f"T{index}", "parent", f"T{child}",
                              f"tree:{index}:{child}")
    ancestor_rules(tree)
    cases.append(("binary-tree-depth-9", tree, "T0", "ancestor", "T1022", {}))

    diamond = CRMSKnowledgeBase()
    previous = ["Start"]
    for layer in range(10):
        current = ([f"L{layer}A", f"L{layer}B"]
                   if layer < 9 else ["Finish"])
        for source in previous:
            for target in current:
                diamond.add_fact(source, "connects to", target,
                                 f"diamond:{source}:{target}")
        previous = current
    diamond.add_relation_type("connects to", "transitive", "schema:diamond")
    cases.append(("diamond-proof-cap", diamond, "Start", "connects to", "Finish", {}))

    conflict = CRMSKnowledgeBase()
    conflict.add_fact("Mira", "prefers", "tea", "positive:tea")
    conflict.add_negative_fact("Mira", "prefers", "tea", "negative:tea")
    cases.append(("explicit-positive-negative", conflict,
                  "Mira", "prefers", "tea", {}))

    negative_only = CRMSKnowledgeBase()
    negative_only.add_negative_fact("Mira", "prefers", "coffee", "negative:coffee")
    cases.append(("negative-only-open-world", negative_only,
                  "Mira", "prefers", "coffee", {}))

    miss = CRMSKnowledgeBase()
    miss.add_fact("A", "parent", "B", "miss:ab")
    ancestor_rules(miss)
    cases.append(("complete-miss", miss, "A", "ancestor", "Z", {}))

    bounded = CRMSKnowledgeBase()
    for index in range(8):
        bounded.add_fact(f"N{index}", "reaches", f"N{index + 1}",
                         f"bounded:{index}")
    bounded.add_relation_type("reaches", "transitive", "schema:bounded")
    cases.append(("expansion-budget", bounded, "N0", "reaches", "N8",
                  {"max_expansions": 1}))

    cyclic = CRMSKnowledgeBase()
    cyclic.add_fact("A", "parent", "B", "cycle:ab")
    cyclic.add_fact("B", "parent", "A", "cycle:ba")
    ancestor_rules(cyclic)
    cases.append(("cycle-backed-self-relation", cyclic,
                  "A", "ancestor", "A", {}))

    constrained = CRMSKnowledgeBase()
    constrained.add_relation_type("parent", "irreflexive", "schema:parent-irreflexive")
    cases.append(("declared-irreflexive-denial", constrained,
                  "A", "parent", "A", {}))

    expectations = {
        "recursive-chain-35": ("answered", True, None),
        "binary-tree-depth-9": ("answered", True, None),
        "diamond-proof-cap": ("answered", False, "proof_limit"),
        "explicit-positive-negative": ("ambiguous", True, None),
        "negative-only-open-world": ("unknown", True, None),
        "complete-miss": ("unknown", True, None),
        "expansion-budget": ("unknown", False, "expansion_limit"),
        "cycle-backed-self-relation": ("ambiguous", True, None),
        "declared-irreflexive-denial": ("denied", True, None),
    }
    rows = []
    for label, kb, subject, relation, obj, limits in cases:
        row, result = measure(label, kb, subject, relation, obj, **limits)
        expected_status, expected_complete, expected_limit = expectations[label]
        require((result.status, result.complete, result.limit_kind)
                == (expected_status, expected_complete, expected_limit),
                f"{label} outcome changed: {result}")
        if result.proofs:
            verify_all(kb, result)
        if result.status == "answered":
            require(result.proofs, f"{label} answered without a proof")
        if result.constraint_denial is not None:
            denial_check = verify_constraint_denial(
                result.conclusion, result.constraint_denial,
                expected_conclusion={"subject": subject, "relation": relation,
                                     "object": obj},
                complete=result.complete, proofs=result.proofs or (),
                facts=[asdict(fact) for fact in kb.facts()],
                rules=[asdict(rule) for rule in kb._inference_rules.values()])
            require(denial_check.valid,
                    f"independent verifier rejected {label} denial: "
                    f"{denial_check}")
        check_deterministic(label, kb, subject, relation, obj, result, **limits)
        rows.append(row)

    print("case\tstatus\tcomplete\tmax-depth\tmax-expansions\texpansions\tproofs\t"
          "shortest-proof-depth\treason\tlimit\tms\tpeak KiB")
    for row in rows:
        print("\t".join(str(row[key]) for key in (
            "case", "status", "complete", "max_depth", "max_expansions",
            "expansions", "proofs", "shortest_proof_depth", "reason", "limit",
            "elapsed_ms", "peak_kib")))
    print("all returned positive proofs independently verified; semantic replays deterministic: PASS")
    print("resource values are observations, not portable thresholds")


if __name__ == "__main__":
    main()
