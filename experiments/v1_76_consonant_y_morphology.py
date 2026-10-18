"""Check grounded consonant-y to -ied predicate transfer.

Run from the project root with:
    python3 experiments/v1_76_consonant_y_morphology.py
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
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    teach_relation(kb, index, "study", "studied", "study")
    teach_relation(kb, index, "carry", "carried", "carry")
    teach_relation(kb, index, "worry", "worry", "worry")

    candidate = next((item for item in kb.propose_facts(
        "Sage worried Sculpture", source="review:consonant-y")
        if item.relation == "worry" and item.subject == "Sage"), None)
    rule = next((item for item in (candidate.language_evidence if candidate else ())
                 if item.get("kind") == "induced_suffix"), None)
    if (rule is None or rule["context"] != "consonant-y"
            or rule["removed_ending"] != "y" or rule["suffix"] != "ied"
            or {item["relation"] for item in rule["support"]}
            != {"carry", "study"}
            or not all(item["sources"] for item in rule["support"])):
        raise SystemExit("candidate did not expose exact independent ied evidence")
    if any(item.relation == "worry" and item.subject == "Sage"
           for item in kb.facts()):
        raise SystemExit("morphological fact proposal was committed without review")

    kb.add_fact("Sage", "worry", "Sculpture", "source:sage-worry")
    kb.teach_question("Who worry the Engine?", relation="worry",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who worry the Compiler?", relation="worry",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who worried the Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"consonant-y morphology did not transfer to QA: {answer}")
    qa_rules = answer.language_evidence or []
    qa_rule = next((item for item in qa_rules
                    if item.get("context") == "consonant-y"), None)
    if (qa_rule is None
            or {item["relation"] for item in qa_rule["support"]}
            != {"carry", "study"}
            or "study → studied" not in kb.render(answer)
            or "study-1#sha256=" not in kb.render(answer)):
        raise SystemExit("QA answer did not expose its induced morphology evidence")

    target = "The report notes that the researcher worried about the result."
    index.add_document("target", "target", target, "sources/target.txt")
    retrieved = kb.research("worry", index, limit=10)
    ids = {passage["citation"].split("#", 1)[0]
           for passage in retrieved.passages or []}
    if "target" not in ids:
        raise SystemExit("consonant-y morphology did not expand research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who worried the Sculpture?")
        if restored_answer.status != "answered" or restored_answer.answer != "Sage":
            raise SystemExit("consonant-y question transfer did not survive persistence")
        restored_candidate = next((item for item in restored.propose_facts(
            "Sage worried Sculpture", source="review:reload")
            if item.relation == "worry" and item.subject == "Sage"), None)
        if not any(item.get("context") == "consonant-y"
                   for item in (restored_candidate.language_evidence
                                if restored_candidate else ())):
            raise SystemExit("consonant-y rule evidence did not survive persistence")

    # The base relation must itself be grounded, and one donor relation alone
    # cannot license a productive spelling transfer.
    cautious = CRMSKnowledgeBase()
    cautious_index = CRMSResearchIndex()
    teach_relation(cautious, cautious_index, "study", "studied", "study")
    teach_relation(cautious, cautious_index, "worry", "worry", "worry")
    if any(item.relation == "worry" and item.subject == "Sage"
           for item in cautious.propose_facts(
               "Sage worried Sculpture", source="review:one-donor")):
        raise SystemExit("one donor relation licensed consonant-y transfer")
    cautious.add_fact("Sage", "worry", "Sculpture", "source:cautious")
    cautious.teach_question("Who worry the Engine?", relation="worry",
                            answer_field="subject", bound_entity="Engine",
                            answer="Ada")
    cautious.teach_question("Who worry the Compiler?", relation="worry",
                            answer_field="subject", bound_entity="Compiler",
                            answer="Bea")
    if cautious.ask("Who worried the Sculpture?").status != "unknown":
        raise SystemExit("one donor relation licensed unsupported QA morphology")

    print("consonant-y morphology diagnostic: PASS")
    print("cross-relation support, base-relation grounding, review-only extraction, QA provenance, research retrieval, persistence, insufficient-support abstention: PASS")


if __name__ == "__main__":
    main()
