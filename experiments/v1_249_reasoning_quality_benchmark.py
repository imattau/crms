"""Small deterministic benchmark for bounded reasoning soundness and coverage.

This is a controlled symbolic benchmark, not a real-world knowledge benchmark.
It checks the reasoner's answer set against a planted chain graph, verifies all
positive derivations independently, and measures abstention, contradiction,
and bound behavior.
"""

from __future__ import annotations

from dataclasses import asdict
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    nodes = [f"N{index}" for index in range(7)]
    for index, (subject, obj) in enumerate(zip(nodes, nodes[1:])):
        kb.add_fact(subject, "parent", obj, f"chain:{index}")
    base_rule = kb.add_inference_rule(
        "ancestor-base", "parent", "parent", "ancestor")
    recursive_rule = kb.add_inference_rule(
        "ancestor-recursive", "parent", "ancestor", "ancestor")

    expected_positive = {
        (nodes[left], nodes[right])
        for left in range(len(nodes))
        for right in range(left + 2, len(nodes))
    }
    expected_unknown = {
        (subject, obj) for subject in nodes for obj in nodes
    } - expected_positive
    observed_positive: set[tuple[str, str]] = set()
    observed_unknown: set[tuple[str, str]] = set()
    proof_count = 0
    false_positive: list[tuple[str, str]] = []
    false_negative: list[tuple[str, str]] = []
    wrong_unknown: list[tuple[str, str, str]] = []
    facts = [asdict(fact) for fact in kb.facts()]
    rules = [asdict(base_rule), asdict(recursive_rule)]

    for subject, obj in sorted(expected_positive | expected_unknown):
        result = kb.infer_relation(subject, "ancestor", obj)
        pair = (subject, obj)
        if pair in expected_positive:
            if result.status != "answered" or not result.complete:
                false_negative.append(pair)
                continue
            observed_positive.add(pair)
            require(bool(result.proofs), f"answer had no proof: {pair}")
            for proof in result.proofs:
                checked = verify_inference_proof(
                    proof, facts, rules, expected_conclusion=result.conclusion)
                require(checked.valid,
                        f"independent verifier rejected {pair}: {checked}")
                proof_count += 1
        elif result.status == "answered":
            false_positive.append(pair)
        elif result.status == "unknown" and result.complete:
            observed_unknown.add(pair)
        else:
            wrong_unknown.append((subject, obj, result.status))

    # Plant a contradiction against a derivable conclusion. Positive evidence
    # must not silently override the explicit negative.
    contradiction_kb = CRMSKnowledgeBase()
    for index, (subject, obj) in enumerate(zip(nodes, nodes[1:])):
        contradiction_kb.add_fact(subject, "parent", obj, f"chain:{index}")
    contradiction_kb.add_inference_rule(
        "ancestor-base", "parent", "parent", "ancestor")
    contradiction_kb.add_inference_rule(
        "ancestor-recursive", "parent", "ancestor", "ancestor")
    contradiction_kb.add_negative_fact(nodes[0], "ancestor", nodes[2],
                                       "planted-negative")
    contradiction = contradiction_kb.infer_relation(
        nodes[0], "ancestor", nodes[2])

    # A shallow limit must be reported as incomplete, never as absence or a
    # partial answer.
    bounded = kb.infer_relation(nodes[0], "ancestor", nodes[6],
                                max_depth=1)

    require(not false_positive,
            f"unsupported conclusions were answered: {false_positive}")
    require(not false_negative,
            f"known chain conclusions were missed: {false_negative}")
    require(not wrong_unknown,
            f"unsupported queries were not complete unknowns: {wrong_unknown}")
    require(observed_unknown == expected_unknown,
            "complete unknown coverage did not match the planted graph")
    require(contradiction.status == "ambiguous"
            and contradiction.reason_code == "contradiction",
            f"planted contradiction was not exposed: {contradiction}")
    require(bounded.status == "unknown" and not bounded.complete
            and bounded.reason_code == "search_limit",
            f"depth exhaustion was not an incomplete unknown: {bounded}")

    # Exercise the same rule against several reproducible graph shapes. The
    # oracle is graph reachability over parent edges, independent of the
    # reasoner's proof search. Keep edges acyclic so every positive has a
    # finite, unambiguous path and every non-reachable pair is truly unknown.
    generated_queries = 0
    generated_positives = 0
    for seed in range(12):
        rng = random.Random(seed)
        graph_kb = CRMSKnowledgeBase()
        graph_nodes = [f"G{seed}_{index}" for index in range(8)]
        adjacency: dict[str, set[str]] = {node: set() for node in graph_nodes}
        for left in range(len(graph_nodes)):
            for right in range(left + 1, len(graph_nodes)):
                if rng.random() < 0.27:
                    source, target = graph_nodes[left], graph_nodes[right]
                    adjacency[source].add(target)
                    graph_kb.add_fact(source, "parent", target,
                                      f"generated:{seed}:{left}:{right}")
        graph_base = graph_kb.add_inference_rule(
            "generated-base", "parent", "parent", "ancestor")
        graph_recursive = graph_kb.add_inference_rule(
            "generated-recursive", "parent", "ancestor", "ancestor")
        graph_facts = [asdict(fact) for fact in graph_kb.facts()]
        graph_rules = [asdict(graph_base), asdict(graph_recursive)]

        def two_or_more_hops(start: str) -> set[str]:
            reached: set[str] = set()
            for first_hop in adjacency[start]:
                pending = list(adjacency[first_hop])
                while pending:
                    node = pending.pop()
                    if node in reached:
                        continue
                    reached.add(node)
                    pending.extend(adjacency[node] - reached)
            return reached

        closure = {node: two_or_more_hops(node) for node in graph_nodes}
        for subject in graph_nodes:
            for obj in graph_nodes:
                expected = obj in closure[subject]
                # The learned base rule intentionally represents a path of two
                # parent edges; a direct parent edge alone is not an ancestor
                # answer in this benchmark's relation definition.
                result = graph_kb.infer_relation(subject, "ancestor", obj)
                generated_queries += 1
                if expected:
                    require(result.status == "answered" and result.complete,
                            f"seed {seed} missed reachable pair {(subject, obj)}")
                    require(bool(result.proofs),
                            f"seed {seed} returned no proof for {(subject, obj)}")
                    for proof in result.proofs:
                        checked = verify_inference_proof(
                            proof, graph_facts, graph_rules,
                            expected_conclusion=result.conclusion)
                        require(checked.valid,
                                f"seed {seed} proof rejected for {(subject, obj)}: "
                                f"{checked}")
                    generated_positives += 1
                else:
                    require(result.status == "unknown" and result.complete,
                            f"seed {seed} overclaimed unsupported pair "
                            f"{(subject, obj)}: {result.status}/{result.reason_code}")

    total = len(expected_positive | expected_unknown)
    precision = len(observed_positive) / (len(observed_positive)
                                          + len(false_positive) or 1)
    recall = len(observed_positive) / len(expected_positive)
    print("reasoning quality benchmark: PASS")
    print(f"queries={total}; expected_positive={len(expected_positive)}; "
          f"expected_unknown={len(expected_unknown)}")
    print(f"positive_precision={precision:.3f}; "
          f"positive_recall={recall:.3f}; independently_verified_proofs={proof_count}")
    print("planted contradiction=ambiguous; depth limit=incomplete unknown")
    print(f"generated_dag_queries={generated_queries}; "
          f"generated_positive_closure={generated_positives}; "
          "all generated positive proofs independently verified")
    print("scope: seeded chain plus 12 generated DAGs; exact rules, no noise "
          "or open-world corpus")


if __name__ == "__main__":
    main()
