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

    proof_frame_kb = CRMSKnowledgeBase()
    proof_frame_kb.add_inference_rule(
        "parent-chain", "parent", "parent", "ancestor")
    for number in range(2):
        subject, middle, target = (f"Proof{number}A", f"Proof{number}B",
                                   f"Proof{number}C")
        proof_frame_kb.add_fact(subject, "parent", middle,
                                f"proof:{number}:left")
        proof_frame_kb.add_fact(middle, "parent", target,
                                f"proof:{number}:right")
        proof_frame_kb.teach_question(
            f"Who is an ancestor of {target}?", relation="ancestor",
            answer_field="subject", bound_entity=target, answer=subject)
    proof_frame_row = next(row for row in support_report(proof_frame_kb)
                           if row.item_kind == "frame"
                           and row.label.startswith("Question frame"))
    require(proof_frame_row.support_examples == 2
            and set(proof_frame_row.source_documents) == {
                "proof:0:left", "proof:0:right", "proof:1:left", "proof:1:right"},
            f"inference proof lineage was not captured for question frames: "
            f"{proof_frame_row}")
    with tempfile.TemporaryDirectory(prefix="crms-v1-344-proof-frame-") as folder:
        saved = Path(folder) / "proof-frame.json"
        proof_frame_kb.save(saved)
        CRMSKnowledgeBase.load(saved)
    first_source = "proof:0:left"
    require(proof_frame_kb.remove_fact(
        "Proof0A", "parent", "Proof0B", first_source),
        "inference-frame premise retraction failed")
    proof_frame_key, proof_frame_examples = next(iter(
        proof_frame_kb._question_examples.items()))
    require(len(proof_frame_examples) == 1
            and not proof_frame_kb._question_frame_is_licensed(
                proof_frame_key, proof_frame_examples),
            "removing a proof premise left its question-frame example licensed")

    learned = CRMSKnowledgeBase()
    for group, prefix in (("training", "train:"), ("holdout", "holdout:")):
        for number in range(2):
            subject, middle, target = (f"{group}{number}A", f"{group}{number}B",
                                       f"{group}{number}C")
            source = f"{prefix}{number}"
            learned.add_fact(subject, "parent", middle, source)
            learned.add_fact(middle, "parent", target, source)
            learned.add_fact(subject, "ancestor", target, source)
    review = learned.review_inference_rules("holdout:")
    candidate_number = next(number for number, item in enumerate(review.reviews, 1)
                            if (item.candidate.first_relation,
                                item.candidate.second_relation,
                                item.candidate.conclusion_relation)
                            == ("parent", "parent", "ancestor"))
    accepted = learned.accept_inference_rule_candidate(
        candidate_number, "accepted-parent-chain", "holdout:")
    require(accepted.accepted, f"source-backed rule acceptance failed: {accepted}")
    for index in range(3):
        subject, middle, target = (f"probe{index}A", f"probe{index}B",
                                   f"probe{index}C")
        learned.add_fact(subject, "parent", middle, f"probe:{index}:left")
        learned.add_fact(middle, "parent", target, f"probe:{index}:right")
        result = learned.practice_relation(subject, "ancestor", target)
        require(result.status == "answered", f"accepted rule did not derive: {result}")
    learned_rows = support_report(learned, min_dependents=3)
    rule_row = next(row for row in learned_rows
                    if row.item_kind == "rule"
                    and row.label.startswith("Rule accepted-parent-chain:"))
    require(rule_row.dependents == 3,
            f"rule use in verified cases was not counted: {rule_row}")
    require(set(rule_row.source_documents) >= {"train:0", "train:1",
                                               "holdout:0", "holdout:1"},
            f"stored train/holdout provenance was not reported: {rule_row}")
    require(rule_row.independent_origins is None
            and not rule_row.origin_count_available
            and rule_row.risk == "unassessed",
            f"unresolvable rule citations were overstated: {rule_row}")

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

        frame_kb = CRMSKnowledgeBase()
        frame_examples = (
            ("frame-a", "Alice likes tea.", "Alice", "tea",
             "https://publisher-a.example/facts/alice"),
            ("frame-b", "Bob likes coffee.", "Bob", "coffee",
             "https://publisher-b.example/facts/bob"),
        )
        licensed = []
        for document_id, sentence, subject, obj, location in frame_examples:
            index.add_document(document_id, document_id, sentence, location)
            hit = next(hit for hit in index.search("likes", limit=30)
                       if hit.document_id == document_id)
            citation = index.citation(hit)
            frame_kb.add_fact(subject, "likes", obj, citation)
            licensed.append(frame_kb.teach_fact_pattern(
                sentence, subject=subject, relation="likes", obj=obj,
                source=citation, predicate_phrase="likes"))
        require(licensed == [False, True],
                f"fact-backed frame licensing changed: {licensed}")
        frame = next(row for row in support_report(
            frame_kb, research_index=index) if row.item_kind == "frame")
        require(frame.support_examples == 2
                and frame.independent_origins == 2
                and frame.origin_count_available,
                f"source-backed frame evidence was not reported: {frame}")
        require(frame.dependents is None and frame.risk == "unassessed",
                f"frame usage was inferred without a usage link: {frame}")

        question_kb = CRMSKnowledgeBase()
        for document_id, sentence, subject, obj, _location in frame_examples:
            hit = next(hit for hit in index.search("likes", limit=30)
                       if hit.document_id == document_id)
            citation = index.citation(hit)
            question_kb.add_fact(subject, "likes", obj, citation)
            question_kb.teach_question(
                f"Who likes {obj}?", relation="likes", answer_field="subject",
                bound_entity=obj, answer=subject)
        question_rows = support_report(question_kb, research_index=index)
        question_frame = next(row for row in question_rows
                              if row.item_kind == "frame"
                              and row.label.startswith("Question frame"))
        require(question_frame.support_examples == 2
                and question_frame.independent_origins == 2,
                f"question-frame source lineage was not reported: {question_frame}")
        tea_fact_row = next(row for row in question_rows
                            if row.item_kind == "fact"
                            and row.label == "Alice — likes → tea")
        require(tea_fact_row.dependents == 1,
                f"question frame was not linked as a fact dependent: {tea_fact_row}")
        saved = Path(folder) / "question-kb.sqlite"
        question_kb.save(saved)
        restored = CRMSKnowledgeBase.load(saved)
        restored_rows = support_report(restored, research_index=index)
        restored_frame = next(row for row in restored_rows
                              if row.item_id == question_frame.item_id)
        require(restored_frame == question_frame,
                f"question-frame evidence was not preserved in SQLite: {restored_frame}")
        tea_hit = next(hit for hit in index.search("likes tea", limit=20)
                       if hit.document_id == "frame-a")
        tea_citation = index.citation(tea_hit)
        require(question_kb.remove_fact("Alice", "likes", "tea", tea_citation),
                "question-example source retraction failed")
        remaining_key, remaining_examples = next(iter(
            question_kb._question_examples.items()))
        require(len(remaining_examples) == 1
                and not question_kb._question_frame_is_licensed(
                    remaining_key, remaining_examples),
                "retracting one of two examples left the frame licensed")
        remaining_frame = next(row for row in support_report(
            question_kb, research_index=index)
                               if row.item_id == question_frame.item_id)
        require(remaining_frame.support_examples == 1,
                f"frame report did not reflect retracted support: {remaining_frame}")
        index.close()

    print("PASS: exact fact leaves link to verified derived dependents")
    print("PASS: teacher support and thin-support flag are reported")
    print("PASS: teacher support does not count as an external origin")
    print("PASS: deterministic report leaves facts and derived cases unchanged")
    print("PASS: inference-backed question frames retain and retract proof provenance")
    print("PASS: accepted rule records training/holdout support and derived dependents")
    print("PASS: citation text detects copies across distinct URL origins")
    print("PASS: unresolved multi-origin citations stay unassessed")
    print("PASS: configured origin mappings group related publishers")
    print("PASS: distinct cited text counts independent origins separately")
    print("PASS: learned sentence frame reports its fact-backed examples")
    print("PASS: explicit question-frame evidence survives SQLite round-trip")
    print("PASS: retracting a licensing fact removes that frame example")


if __name__ == "__main__":
    main()
