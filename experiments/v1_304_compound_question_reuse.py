"""Check deterministic compound answers and invariant-clause reuse."""
from __future__ import annotations

from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_knowledge(filler_count: int = 0) -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada", "design", "Engine", "source:design")
    knowledge.add_fact("Ada", "build", "Loom", "source:build")
    for number in range(filler_count):
        knowledge.add_fact(f"Entity{number}", "recorded", f"Value{number}",
                           f"source:filler:{number}")
    return knowledge


def main() -> None:
    knowledge = build_knowledge()
    original_ask = knowledge.ask
    counts: dict[str, int] = {}

    def counted_ask(question: str, **kwargs):
        counts[question] = counts.get(question, 0) + 1
        return original_ask(question, **kwargs)

    knowledge.ask = counted_ask
    started = time.perf_counter()
    answer = knowledge.ask("Did Ada design Engine and build Loom?")
    elapsed = time.perf_counter() - started
    require(answer.status == "answered" and answer.truth is True
            and {source for fact in answer.evidence or []
                 for source in fact["sources"]}
            == {"source:design", "source:build"},
            f"compound answer or provenance changed: {answer}")
    first_clause_calls = counts.get("Did Ada design Engine?", 0)
    require(first_clause_calls == 1,
            f"invariant first clause was evaluated {first_clause_calls} times")

    # A disjunct exercises the same reconstruction route with a distinct
    # result, guarding fixed-order combination as well as the conjunct path.
    second = build_knowledge().ask("Did Ada design Engine or build Loom?")
    require(second.status == "answered" and second.truth is True,
            f"disjunctive answer regressed: {second}")

    print("compound question serial-work diagnostic: PASS")
    print(f"first clause evaluated once across {len(counts) - 1} candidate "
          f"questions; one query took {elapsed * 1000:.2f} ms")


if __name__ == "__main__":
    main()
