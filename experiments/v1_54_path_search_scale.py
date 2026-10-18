"""Exercise branching, cyclic, and expansion-limited path search.

Run from the project root with:
    python3 experiments/v1_54_path_search_scale.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_proof import verify_fact_path


def main() -> None:
    width = 24
    kb = CRMSKnowledgeBase()
    for left in range(width):
        left_node = f"Layer A {left}"
        kb.add_fact("Origin", "r1", left_node, f"source:r1:{left}")
        for right in range(width):
            right_node = f"Layer B {right}"
            kb.add_fact(left_node, "r2", right_node,
                        f"source:r2:{left}:{right}")
    for right in range(width):
        kb.add_fact(f"Layer B {right}", "r3", "Target",
                    f"source:r3:{right}")

    fact_snapshot = [fact.__dict__ for fact in kb.facts()]
    reverse_index = {}
    for fact in kb.facts():
        reverse_index.setdefault((fact.object, fact.relation), []).append(fact.subject)
    baseline_expansions = 0
    reverse_frontier = ["Target"]
    for relation in reversed(("r1", "r2", "r3")):
        next_frontier = []
        for entity in reverse_frontier:
            predecessors = reverse_index.get((entity, relation), ())
            baseline_expansions += len(predecessors)
            next_frontier.extend(predecessors)
        reverse_frontier = next_frontier

    started = time.perf_counter()
    result = kb.ask_path_between("Origin", "Target", ["r1", "r2", "r3"])
    elapsed = time.perf_counter() - started
    expected_paths = width * width
    # One-sided search expands all edges through three layers. Meet-in-the-
    # middle expands the first layer from Origin and the last two from Target.
    expected_expansions = width + width + expected_paths
    if (result.status != "answered" or result.truth is not True
            or len(result.proofs or []) != expected_paths
            or result.expansions != expected_expansions
            or baseline_expansions != width + 2 * expected_paths
            or result.expansions >= baseline_expansions):
        raise SystemExit(
            f"branching graph returned an unexpected result: "
            f"status={result.status}, proofs={len(result.proofs or [])}")

    for proof in result.proofs or []:
        checked = verify_fact_path(
            proof, fact_snapshot, start="Origin", relations=["r1", "r2", "r3"],
            answer="Target")
        if not checked.valid:
            raise SystemExit(f"scale run produced an invalid proof: {checked}")

    exhausted = kb.ask_path_between(
        "Origin", "Target", ["r1", "r2", "r3"],
        max_expansions=expected_expansions - 1)
    if exhausted.status != "unknown" or exhausted.proofs:
        raise SystemExit(f"one-under-budget search did not abstain: {exhausted.status}")
    at_limit = kb.ask_path_between(
        "Origin", "Target", ["r1", "r2", "r3"],
        max_expansions=expected_expansions)
    if at_limit.status != "answered" or len(at_limit.proofs or []) != expected_paths:
        raise SystemExit(f"exact expansion budget failed: {at_limit.status}")

    cyclic = CRMSKnowledgeBase()
    cyclic.add_fact("A", "r1", "B", "cycle:1")
    cyclic.add_fact("B", "r2", "A", "cycle:2")
    cyclic.add_fact("A", "r3", "A", "cycle:3")
    cycle_result = cyclic.ask_path_between("A", "A", ["r1", "r2", "r3"])
    if (cycle_result.status != "answered" or len(cycle_result.proofs or []) != 1
            or len(cycle_result.proofs[0]) != 3):
        raise SystemExit(f"bounded cyclic path was not resolved: {cycle_result}")
    cycle_check = verify_fact_path(
        cycle_result.proofs[0], [fact.__dict__ for fact in cyclic.facts()],
        start="A", relations=["r1", "r2", "r3"], answer="A")
    if not cycle_check.valid:
        raise SystemExit(f"cycle proof failed independent checking: {cycle_check}")

    print("path search scale diagnostic: PASS")
    print(f"branching graph: {len(fact_snapshot)} facts, {expected_paths} complete proofs, "
          f"{result.expansions} meet-in-the-middle expansions vs "
          f"{baseline_expansions} one-sided expansions, {elapsed:.3f}s")
    print("exact limit, one-under-limit abstention, bounded cycle, independent proofs: PASS")


if __name__ == "__main__":
    main()
