"""Check read-only fact support/dependency reporting on practice proofs."""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_support_report import support_report  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("A", "parent", "B", "teacher:conversation")
    kb.add_negative_fact("X", "likes", "Y", "counterexample:xy")
    kb.add_fact("B", "parent", "C", "corpus/family/a.txt#one")
    kb.add_fact("B", "parent", "D", "corpus/family/b.txt#two")
    kb.add_fact("B", "parent", "E", "corpus/family/c.txt#three")
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    for leaf in ("C", "D", "E"):
        result = kb.practice_relation("A", "ancestor", leaf)
        require(result.status == "answered", f"practice failed for {leaf}: {result}")

    before_facts = tuple((fact.subject, fact.relation, fact.object, fact.sources)
                         for fact in kb.facts())
    before_cases = tuple(kb.derived_cases())
    rows = support_report(kb, min_dependents=3)
    repeated = support_report(kb, min_dependents=3)
    require(rows == repeated, "report ordering or IDs are not deterministic")
    shared = next((row for row in rows if row.label == "A — parent → B"), None)
    require(shared is not None and shared.dependents == 3,
            f"three verified derived dependents were not counted: {shared}")
    require(shared.teacher_supported and shared.risk == "thin",
            f"teacher origin or thin-support flag was lost: {shared}")
    negative = next((row for row in rows if row.label == "X — not likes → Y"), None)
    require(negative is not None and negative.dependents == 0,
            f"negative fact report is malformed: {negative}")
    require(shared.independent_origins is None and not shared.origin_count_available,
            "document count was incorrectly presented as independent origins")
    require(set(shared.source_documents) == {"teacher:conversation"},
            f"citation document normalization failed: {shared.source_documents}")
    after_facts = tuple((fact.subject, fact.relation, fact.object, fact.sources)
                        for fact in kb.facts())
    after_cases = tuple(kb.derived_cases())
    require(before_facts == after_facts and before_cases == after_cases,
            "read-only report mutated accepted facts or derived cases")

    print("PASS: exact fact leaves link to verified derived dependents")
    print("PASS: teacher support and thin-support flag are reported")
    print("PASS: origin count is explicitly unavailable, not guessed")
    print("PASS: deterministic report leaves facts and derived cases unchanged")


if __name__ == "__main__":
    main()
