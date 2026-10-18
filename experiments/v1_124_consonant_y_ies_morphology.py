"""Check cross-relation consonant-y → -ies transfer in grounded language.

Run from the project root with:
    python3 experiments/v1_124_consonant_y_ies_morphology.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach(kb: CRMSKnowledgeBase, relation: str, surface: str,
          document: str) -> None:
    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        source = f"{document}-{subject}"
        sentence = f"{subject} {surface} {obj}."
        kb.add_fact(subject, relation, obj, source)
        kb.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "study", "studies", "study-doc")
    teach(kb, "carry", "carries", "carry-doc")
    teach(kb, "marry", "marry", "marry-doc")
    teach(kb, "stay", "stays", "stay-doc")
    teach(kb, "pray", "prays", "pray-doc")
    kb.add_fact("Sage", "marry", "Sculpture", "source:sage-marry")

    forms, evidence = kb._predicate_forms_for_relation(("marry",), set())
    if ("marries",) not in forms:
        raise SystemExit("consonant-y donors did not generate marries")
    rule = evidence.get(("marries",))
    if (rule is None or rule.get("suffix") != "ies"
            or rule.get("context") != "consonant-y"
            or {item["relation"] for item in rule["support"]}
            != {"study", "carry"}
            or any(not item["sources"] for item in rule["support"])):
        raise SystemExit("generated -ies form lost its independent support evidence")
    vowel_forms, _ = kb._predicate_forms_for_relation(("play",), set())
    if ("plays",) not in vowel_forms or ("plaies",) in vowel_forms:
        raise SystemExit("vowel-y control did not retain the plain -s form")

    proposal = next((item for item in kb.propose_facts(
        "Sage marries Sculpture", source="review:marries")
        if item.relation == "marry" and item.subject == "Sage"), None)
    if (proposal is None or not any(
            item.get("suffix") == "ies" and item.get("context") == "consonant-y"
            for item in proposal.language_evidence)):
        raise SystemExit("-ies spelling did not reach review-only fact proposals")
    if "review:marries" in next(fact for fact in kb.facts()
                                if fact.subject == "Sage"
                                and fact.relation == "marry").sources:
        raise SystemExit("inflected proposal was committed without review")

    one_family = CRMSKnowledgeBase()
    teach(one_family, "study", "studies", "study-doc-a")
    teach(one_family, "study", "studies", "study-doc-b")
    if ("marries",) in one_family._predicate_forms_for_relation(
            ("marry",), set())[0]:
        raise SystemExit("one relation family licensed consonant-y transfer")

    kb.teach_question("Who marry Engine?", relation="marry",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who marry Compiler?", relation="marry",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who marries Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"-ies morphology did not transfer to QA: {answer}")
    if not any(item.get("suffix") == "ies"
               for item in answer.language_evidence or []):
        raise SystemExit("QA answer omitted consonant-y spelling evidence")

    index = CRMSResearchIndex()
    index.add_document("marries", "Marries", "The sculptor marries the material.",
                       "sources/marries.txt")
    research = kb.research("marry", index, limit=10)
    if not any(item["citation"].startswith("marries#")
               for item in research.passages or []):
        raise SystemExit("-ies morphology did not expand research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who marries Sculpture?")
    if restored_answer.status != "answered" or restored_answer.answer != "Sage":
        raise SystemExit("consonant-y -ies evidence did not survive persistence")

    print("consonant-y -ies morphology diagnostic: PASS")
    print("cross-relation/source support, vowel-y controls, review-only proposal, QA/research transfer, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
