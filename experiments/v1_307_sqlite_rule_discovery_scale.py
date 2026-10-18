"""Profile source-backed rule discovery through a SQLite model store.

Run from the project root with:
    python3 experiments/v1_307_sqlite_rule_discovery_scale.py
"""
from __future__ import annotations

from pathlib import Path
import statistics
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def seeded(count: int) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for index in range(count):
        kb.add_fact(f"Entity{index:06d}", "isolated", f"Value{index:06d}",
                    f"background:{index:06d}")
    for number in range(2):
        subject, middle, target = (f"Person{number}A", f"Person{number}B",
                                   f"Person{number}C")
        source = f"labeled:{number}"
        kb.add_fact(subject, "parent", middle, source)
        kb.add_fact(middle, "parent", target, source)
        kb.add_fact(subject, "ancestor", target, source)
    return kb


def signature(kb: CRMSKnowledgeBase):
    result = kb.discover_inference_rules(max_expansions=100_000)
    candidates = [(candidate.first_relation, candidate.second_relation,
                   candidate.conclusion_relation, candidate.status,
                   len(candidate.positive_examples),
                   candidate.independent_sources)
                  for candidate in result.candidates]
    return result.complete, result.expansions, tuple(candidates)


def main() -> None:
    print("SQLite facts | expansions | median discovery time (3 runs)")
    for background in (20_000, 100_000):
        memory = seeded(background)
        expected = signature(memory)
        if (not expected[0] or expected[1] != 2
                or expected[2] != (("parent", "parent", "ancestor",
                                    "uncontradicted", 2,
                                    ("labeled:0", "labeled:1")),)):
            raise SystemExit(f"unexpected in-memory discovery result: {expected}")
        with tempfile.TemporaryDirectory(prefix="crms-sql-rule-discovery-") as folder:
            path = Path(folder) / "knowledge.sqlite"
            memory.save(path)
            sqlite_kb = CRMSKnowledgeBase.load(path)
            durations = []
            for _ in range(3):
                started = time.perf_counter()
                observed = signature(sqlite_kb)
                durations.append(time.perf_counter() - started)
                if observed != expected:
                    raise SystemExit(
                        f"SQLite discovery diverged from memory: {observed}")
            milliseconds = statistics.median(durations) * 1000
            print(f"{background + 6:>12,} | {expected[1]:>10,} | "
                  f"{milliseconds:>10.2f} ms", flush=True)
            sqlite_kb.close()


if __name__ == "__main__":
    main()
