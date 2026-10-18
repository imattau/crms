"""Profile source-backed rule discovery through a SQLite model store.

Run from the project root with:
    python3 experiments/v1_307_sqlite_rule_discovery_scale.py
"""
from __future__ import annotations

from dataclasses import asdict
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
    candidates = tuple(asdict(candidate) for candidate in result.candidates)
    return result.complete, result.expansions, tuple(candidates)


def check_pruned_parity() -> None:
    """Keep conclusion labels, counterexamples, scopes and kinds on SQLite."""
    memory = CRMSKnowledgeBase()
    memory.add_fact("A", "employs", "B", "train:one")
    memory.add_fact("B", "owns", "C", "train:one")
    memory.add_fact("C", "located in", "D", "train:one")
    memory.add_fact("A", "reaches", "D", "train:one")
    memory.add_fact("B", "is-a", "person", "train:one")
    memory.add_fact("C", "is-a", "asset", "train:one")
    for subject, first, second, target in (
            ("E", "F", "G", "H"),):
        memory.add_fact(subject, "employs", first, "train:two")
        memory.add_fact(first, "owns", second, "train:two")
        memory.add_fact(second, "located in", target, "train:two")
        memory.add_fact(subject, "reaches", target, "train:two")
        memory.add_fact(first, "is-a", "person", "train:two")
        memory.add_fact(second, "is-a", "asset", "train:two")
    # This negative label is not itself a chain edge and must survive the
    # indexed positive-fact filter as a counterexample.
    memory.add_negative_fact("A", "reaches", "D", "review:negative")
    # This cross-scope path must remain excluded after SQL candidate pruning.
    memory.add_fact("Other", "employs", "Middle", "scope:left",
                    qualifiers={"year": "2024"})
    memory.add_fact("Middle", "owns", "Target", "scope:right",
                    qualifiers={"year": "2025"})
    expected = memory.discover_inference_rules(max_arity=3)
    with tempfile.TemporaryDirectory(prefix="crms-sql-rule-parity-") as folder:
        path = Path(folder) / "knowledge.sqlite"
        memory.save(path)
        disk = CRMSKnowledgeBase.load(path)
        observed = disk.discover_inference_rules(max_arity=3)
        if (observed.complete, observed.expansions,
                tuple(asdict(candidate) for candidate in observed.candidates)) != (
                expected.complete, expected.expansions,
                tuple(asdict(candidate) for candidate in expected.candidates)):
            raise SystemExit("indexed discovery changed scope/evidence/candidate parity")
        if not any(candidate.status == "contradicted"
                   and candidate.third_relation == "located in"
                   for candidate in observed.candidates):
            raise SystemExit("isolated negative label was lost as a counterexample")
        disk.close()


def main() -> None:
    check_pruned_parity()
    print("SQLite facts | expansions | in-memory ms | SQLite ms (median of 3)")
    for background in (20_000, 100_000):
        memory = seeded(background)
        expected = signature(memory)
        if (not expected[0] or expected[1] != 2 or len(expected[2]) != 1
                or (expected[2][0]["first_relation"],
                    expected[2][0]["second_relation"],
                    expected[2][0]["conclusion_relation"],
                    expected[2][0]["status"],
                    len(expected[2][0]["positive_examples"]),
                    expected[2][0]["independent_sources"])
                != ("parent", "parent", "ancestor", "uncontradicted", 2,
                    ("labeled:0", "labeled:1"))):
            raise SystemExit(f"unexpected in-memory discovery result: {expected}")
        memory_durations = []
        for _ in range(3):
            started = time.perf_counter()
            if signature(memory) != expected:
                raise SystemExit("in-memory discovery changed across repeated runs")
            memory_durations.append(time.perf_counter() - started)
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
            memory_ms = statistics.median(memory_durations) * 1000
            sqlite_ms = statistics.median(durations) * 1000
            print(f"{background + 6:>12,} | {expected[1]:>10,} | "
                  f"{memory_ms:>12.2f} | {sqlite_ms:>9.2f}", flush=True)
            sqlite_kb.close()


if __name__ == "__main__":
    main()
