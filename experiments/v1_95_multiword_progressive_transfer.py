"""Check grounded progressive transfer for aligned multiword predicates.

Run from the project root with:
    python3 experiments/v1_95_multiword_progressive_transfer.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach_relation(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                   relation: str, surface: str, prefix: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        document_id = f"{prefix}-{number}"
        index.add_document(document_id, document_id, sentence,
                           f"sources/{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=10)
                   if item.document_id == document_id)
        kb.add_fact_from_hit(subject, relation, obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation=relation, obj=obj,
            predicate_phrase=surface, research_index=index, hit=hit)


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    teach_relation(kb, index, "work through", "working through", "work")
    teach_relation(kb, index, "talk through", "talking through", "talk")
    teach_relation(kb, index, "walk through", "walked through", "walk")
    teach_relation(kb, index, "walk around", "walked around", "around")
    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        kb.teach_question(f"Who walked through the {obj}?",
                          relation="walk through", answer_field="subject",
                          bound_entity=obj, answer=subject)
        kb.teach_question(f"Who walked around the {obj}?",
                          relation="walk around", answer_field="subject",
                          bound_entity=obj, answer=subject)

    # The output relation is explicitly grounded, but the held-out inflection
    # is licensed only by the two independent multiword donor relations.
    kb.add_fact("Sage", "walk through", "Forest", "source:sage-current",
                qualifiers={"aspect": "progressive"})
    sentence = "The guide is walking through the forest."
    index.add_document("heldout", "Held Out", sentence,
                       "sources/heldout.txt")
    answer = kb.ask("Who is walking through the Forest?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"multiword progressive QA failed: {answer}")
    if not any(item.get("surface_form") == "walking through"
               and item.get("suffix") == "ing"
               for item in answer.language_evidence or []):
        raise SystemExit("multiword answer lost its induced morphology evidence")
    if not any(dict(item.get("qualifiers", [])) == {"aspect": "progressive"}
               for item in answer.evidence or []):
        raise SystemExit("multiword progressive answer ignored exact aspect scope")

    research = kb.research("walk through", index, limit=20)
    ids = {item["citation"].split("#", 1)[0]
           for item in research.passages or []}
    if "heldout" not in ids:
        raise SystemExit("multiword progressive form did not expand research retrieval")

    kb.add_fact("Sage", "walk around", "Garden", "source:sage-around",
                qualifiers={"aspect": "progressive"})
    unsupported_particle = kb.ask("Who is walking around the Garden?")
    if unsupported_particle.status != "unknown":
        raise SystemExit("progressive rule crossed to an unsupported particle")

    print("multiword progressive transfer diagnostic: PASS")
    print("independent multiword support, held-out QA, exact aspect, research expansion, particle abstention: PASS")


if __name__ == "__main__":
    main()
