"""Check read-only fact support/dependency reporting on practice proofs."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_support_report import support_report  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


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
    require(shared.independent_origins == 0 and shared.origin_count_available,
            "teacher evidence was counted as an independent external origin")
    remapped_teacher = next(row for row in support_report(
        kb, min_dependents=3, origin_map={r"teacher:": "external"})
                            if row.label == "A — parent → B")
    require(remapped_teacher.origins == ("teacher",)
            and remapped_teacher.independent_origins == 0,
            "a custom origin map reclassified teacher input as external")
    require(set(shared.source_documents) == {"teacher:conversation"},
            f"citation document normalization failed: {shared.source_documents}")
    after_facts = tuple((fact.subject, fact.relation, fact.object, fact.sources)
                        for fact in kb.facts())
    after_cases = tuple(kb.derived_cases())
    require(before_facts == after_facts and before_cases == after_cases,
            "read-only report mutated accepted facts or derived cases")

    with tempfile.TemporaryDirectory(prefix="crms-v1-344-") as folder:
        index = CRMSSQLiteResearchIndex(Path(folder) / "research.sqlite")
        index.add_document("copy-a", "Copy A", "A parent of B.",
                           "https://publisher-a.example/family/a")
        index.add_document("copy-b", "Copy B", "A parent of B.",
                           "https://publisher-b.example/family/b")
        citations = []
        for document_id in ("copy-a", "copy-b"):
            hit = next(hit for hit in index.search("parent", limit=10)
                       if hit.document_id == document_id)
            citations.append(index.citation(hit))
        copied_kb = CRMSKnowledgeBase()
        for citation in citations:
            copied_kb.add_fact("A", "parent", "B", citation)
        copied = next(row for row in support_report(
            copied_kb, research_index=index) if row.label == "A — parent → B")
        require(copied.origins == ("publisher-a.example", "publisher-b.example"),
                f"URL origins were not normalized: {copied.origins}")
        require(copied.copied is True and copied.independent_origins == 1,
                f"verbatim cross-origin copying was counted as independent: {copied}")
        unresolved = next(row for row in support_report(copied_kb)
                          if row.label == "A — parent → B")
        require(unresolved.independent_origins is None
                and not unresolved.origin_count_available
                and unresolved.risk == "unassessed",
                f"unresolved citations were treated as independent: {unresolved}")
        merged = next(row for row in support_report(
            copied_kb, research_index=index,
            origin_map={r"publisher-[ab]\.example": "shared-publisher"})
                      if row.label == "A — parent → B")
        require(merged.origins == ("shared-publisher",)
                and merged.independent_origins == 1,
                f"configured origin grouping was ignored: {merged}")

        distinct_kb = CRMSKnowledgeBase()
        for document_id, text, location in (
                ("distinct-a", "A is a parent of B.",
                 "https://publisher-a.example/family/a"),
                ("distinct-b", "A has B as a child.",
                 "https://publisher-b.example/family/b")):
            index.add_document(document_id, document_id, text, location)
            hit = next(hit for hit in index.search("parent OR child", limit=20)
                       if hit.document_id == document_id)
            distinct_kb.add_fact("A", "parent", "B", index.citation(hit))
        distinct = next(row for row in support_report(
            distinct_kb, research_index=index) if row.label == "A — parent → B")
        require(distinct.independent_origins == 2 and distinct.copied is False,
                f"distinct origin statements were not counted: {distinct}")
        index.close()

    print("PASS: exact fact leaves link to verified derived dependents")
    print("PASS: teacher support and thin-support flag are reported")
    print("PASS: teacher support does not count as an external origin")
    print("PASS: deterministic report leaves facts and derived cases unchanged")
    print("PASS: citation text detects copies across distinct URL origins")
    print("PASS: unresolved multi-origin citations stay unassessed")
    print("PASS: configured origin mappings group related publishers")
    print("PASS: distinct cited text counts independent origins separately")


if __name__ == "__main__":
    main()
