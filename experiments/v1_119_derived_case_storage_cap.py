"""Check bounded deterministic storage for proof-backed practice memory.

Run from the project root with:
    python3 experiments/v1_119_derived_case_storage_cap.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def add_chain(kb: CRMSKnowledgeBase, subject: str, middle: str,
              obj: str, prefix: str) -> None:
    kb.add_fact(subject, "connected to", middle, f"{prefix}:left")
    kb.add_fact(middle, "located at", obj, f"{prefix}:right")


def main() -> None:
    try:
        CRMSKnowledgeBase(max_derived_cases=-1)
    except ValueError:
        pass
    else:
        raise SystemExit("negative storage cap was accepted")

    kb = CRMSKnowledgeBase(max_derived_cases=2)
    kb.add_inference_rule("connection-location", "connected to",
                          "located at", "connection location")
    add_chain(kb, "Ada", "Engine", "London", "ada")
    add_chain(kb, "Bea", "Compiler", "Paris", "bea")
    add_chain(kb, "Cal", "Archive", "Rome", "cal")

    conclusions = [("Ada", "London"), ("Bea", "Paris"), ("Cal", "Rome")]
    for subject, obj in conclusions[:2]:
        result = kb.practice_relation(subject, "connection location", obj)
        if result.status != "answered":
            raise SystemExit(f"practice failed for {subject}: {result.status}")
    reused = kb.retrieve_derived_case("Ada", "connection location", "London")
    if (reused is None or reused["status"] != "verified"
            or reused["reuse_count"] != 1):
        raise SystemExit("successful reuse was not recorded")

    result = kb.practice_relation("Cal", "connection location", "Rome")
    if result.status != "answered":
        raise SystemExit("practice stopped returning verified answers at capacity")
    cases = kb.derived_cases()
    retained = {(case["conclusion"]["subject"], case["conclusion"]["object"])
                for case in cases if case["status"] == "verified"}
    if retained != {("Ada", "London"), ("Cal", "Rome")}:
        raise SystemExit(f"least-reused oldest artifact was not evicted: {retained}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        if restored.max_derived_cases != 2:
            raise SystemExit("storage cap did not survive persistence")
        restored.practice_relation("Bea", "connection location", "Paris")
        restored_cases = restored.derived_cases()
        restored_retained = {
            (case["conclusion"]["subject"], case["conclusion"]["object"])
            for case in restored_cases if case["status"] == "verified"}
        if restored_retained != {("Ada", "London"), ("Bea", "Paris")}:
            raise SystemExit(
                f"persisted order did not give deterministic eviction: {restored_retained}")

    disabled = CRMSKnowledgeBase(max_derived_cases=0)
    disabled.add_inference_rule("connection-location", "connected to",
                                "located at", "connection location")
    add_chain(disabled, "Ada", "Engine", "London", "disabled")
    if disabled.practice_relation(
            "Ada", "connection location", "London").status != "answered":
        raise SystemExit("disabled storage changed the inference result")
    if disabled.derived_cases():
        raise SystemExit("zero cap retained a derived artifact")

    print("derived-case storage-cap diagnostic: PASS")
    print("bounded storage, successful-reuse priority, stable tie-breaking, persistence, zero-cap behavior: PASS")


if __name__ == "__main__":
    main()
