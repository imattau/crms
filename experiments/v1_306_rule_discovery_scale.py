"""Measure sparse rule-discovery cost as the fact store grows.

The generated facts are intentionally disconnected from two labeled
parent/parent -> ancestor examples. The profile therefore measures the cost
of loading, normalizing, and indexing a large store without hiding a dense
join behind the candidate-search bound. It is a local scaling diagnostic,
not a representative semantic-rule benchmark.

Run from the project root with:
    python3 experiments/v1_306_rule_discovery_scale.py
"""
from __future__ import annotations

import statistics
import time
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def build_store(background_count: int) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for index in range(background_count):
        kb.add_fact(f"Entity{index:06d}", "isolated", f"Value{index:06d}",
                    f"background:{index:06d}")
    for number in range(2):
        subject = f"Person{number}A"
        middle = f"Person{number}B"
        target = f"Person{number}C"
        source = f"labeled:{number}"
        kb.add_fact(subject, "parent", middle, source)
        kb.add_fact(middle, "parent", target, source)
        kb.add_fact(subject, "ancestor", target, source)
    return kb


def profile(background_count: int) -> tuple[float, int, int]:
    kb = build_store(background_count)
    durations: list[float] = []
    signature = None
    for _ in range(3):
        started = time.perf_counter()
        result = kb.discover_inference_rules(max_expansions=100_000)
        durations.append(time.perf_counter() - started)
        target = [candidate for candidate in result.candidates
                  if (candidate.first_relation, candidate.second_relation,
                      candidate.conclusion_relation)
                  == ("parent", "parent", "ancestor")]
        current = (result.complete, result.expansions,
                   tuple(candidate.status for candidate in target),
                   tuple(len(candidate.positive_examples) for candidate in target))
        if signature is None:
            signature = current
        elif current != signature:
            raise SystemExit(f"discovery changed across repeated runs: {current}")
    if signature != (True, 2, ("uncontradicted",), (2,)):
        raise SystemExit(f"sparse rule discovery lost its labeled rule: {signature}")
    return statistics.median(durations), background_count + 6, signature[1]


def main() -> None:
    print("facts | join expansions | median rule-discovery time (3 runs)")
    for count in (10_000, 50_000, 100_000):
        elapsed, total, expansions = profile(count)
        print(f"{total:>7,} | {expansions:>15,} | {elapsed * 1000:>10.2f} ms",
              flush=True)


if __name__ == "__main__":
    main()
