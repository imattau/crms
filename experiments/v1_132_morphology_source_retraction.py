"""Check productive morphology is withdrawn when donor evidence is retracted.

Run from the project root with:
    python3 experiments/v1_132_morphology_source_retraction.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach_relation(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                   relation: str, surface: str, prefix: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        document = f"{prefix}-{number}"
        index.add_document(document, document, sentence,
                           f"sources/{document}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document)
        kb.add_fact_from_hit(subject, relation, obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation=relation, obj=obj,
            research_index=index, hit=hit, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    teach_relation(kb, index, "design", "designed", "design")
    teach_relation(kb, index, "walk", "walked", "walk")
    teach_relation(kb, index, "paint", "paint", "paint")
    kb.add_fact("Sage", "paint", "Sculpture", "source:sage-paint")
    kb.teach_question("Who paint the Engine?", relation="paint",
                      answer_field="subject", bound_entity="Engine",
                      answer="Ada")
    kb.teach_question("Who paint the Compiler?", relation="paint",
                      answer_field="subject", bound_entity="Compiler",
                      answer="Bea")

    target = "The restorer painted a sculpture yesterday."
    index.add_document("painted-target", "Painted target", target,
                       "sources/painted-target.txt")
    before = kb.ask("Who painted the Sculpture?")
    if before.status != "answered" or before.answer != "Sage":
        raise SystemExit(f"induced -ed form was not usable before retraction: {before}")
    if not any(item["citation"].startswith("painted-target#")
               for item in kb.research("paint", index, limit=10).passages or []):
        raise SystemExit("induced -ed form did not expand research before retraction")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        kb = CRMSKnowledgeBase.load(path)
        restored_before = kb.ask("Who painted the Sculpture?")
        if restored_before.status != "answered":
            raise SystemExit("productive form did not survive before-retraction persistence")

    # Remove the complete evidence family for one of the two donor relations.
    for subject, obj, source in (
            ("Ada", "Engine", "design-1"),
            ("Bea", "Compiler", "design-2")):
        hit = next(item for item in index.search(
            f"{subject} designed {obj}", limit=10)
            if item.document_id == source)
        citation = index.citation(hit)
        if not kb.remove_fact(subject, "design", obj, citation):
            raise SystemExit(f"could not retract morphology donor {source}")

    after = kb.ask("Who painted the Sculpture?")
    if after.status == "answered":
        raise SystemExit("retracted donor still licensed the -ed question form")
    if any(item.relation == "paint" for item in kb.propose_facts(
            "Mira painted Sculpture.", source="review:after-retraction")):
        raise SystemExit("retracted donor still licensed -ed fact proposals")
    after_research = kb.research("paint", index, limit=10)
    if any(item["citation"].startswith("painted-target#")
           for item in after_research.passages or []):
        raise SystemExit("retracted donor still expanded research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "retracted-knowledge.json"
        kb.save(path)
        restored_after = CRMSKnowledgeBase.load(path)
        if restored_after.ask("Who painted the Sculpture?").status == "answered":
            raise SystemExit("retracted productive form returned after persistence")
        if any(item["citation"].startswith("painted-target#")
               for item in restored_after.research(
                   "paint", index, limit=10).passages or []):
            raise SystemExit("retracted research expansion returned after persistence")

    print("morphology source retraction diagnostic: PASS")
    print("QA, review-only extraction, and research expansion withdraw with donor evidence across persistence: PASS")


if __name__ == "__main__":
    main()
