"""Check evidence-gated doubling for single-z verb forms such as quiz/quizzes.

Run from the project root with:
    python3 experiments/v1_123_single_z_verb_morphology.py
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
    teach(kb, "quiz", "quizzes", "quiz-source")
    teach(kb, "whiz", "whizzes", "whiz-source")
    teach(kb, "gliz", "gliz", "gliz-source")

    kb.add_fact("Sage", "gliz", "Sculpture", "source:sage-gliz")
    proposal = next((item for item in kb.propose_facts(
        "Sage glizzes Sculpture", source="review:glizzes")
        if item.relation == "gliz" and item.subject == "Sage"), None)
    morphology = next((item for item in (proposal.language_evidence if proposal else [])
                       if item.get("kind") == "induced_suffix"), None)
    if (proposal is None or morphology is None
            or morphology.get("context") != "single-z-double"
            or morphology.get("suffix") != "es"
            or {item["relation"] for item in morphology["support"]}
            != {"quiz", "whiz"}
            or any(not item["sources"] for item in morphology["support"])):
        raise SystemExit("independent single-z examples did not license gliz → glizzes")
    if any(fact.relation == "gliz" and fact.subject == "Sage"
           and fact.object == "Sculpture" for fact in kb.facts()):
        # The direct fact above is the grounding fact; the proposed spelling
        # must not create a second source or promote the review candidate.
        stored = next(fact for fact in kb.facts()
                      if fact.relation == "gliz" and fact.subject == "Sage"
                      and fact.object == "Sculpture")
        if "review:glizzes" in stored.sources:
            raise SystemExit("inflected proposal was committed without review")

    # A single-z-after-vowel rule must not leak to consonant+z spellings.
    waltz_forms, _ = kb._predicate_forms_for_relation(("waltz",), set())
    if ("waltzzes",) in waltz_forms:
        raise SystemExit("single-z doubling transferred to waltz")
    one_family = CRMSKnowledgeBase()
    teach(one_family, "quiz", "quizzes", "quiz-source-a")
    teach(one_family, "quiz", "quizzes", "quiz-source-b")
    if ("glizzes",) in one_family._predicate_forms_for_relation(
            ("gliz",), set())[0]:
        raise SystemExit("one relation family licensed single-z doubling")

    kb.teach_question("Who gliz Engine?", relation="gliz",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who gliz Compiler?", relation="gliz",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who glizzes Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"single-z morphology did not transfer to QA: {answer}")
    if not any(item.get("context") == "single-z-double"
               for item in answer.language_evidence or []):
        raise SystemExit("QA answer omitted single-z morphology evidence")

    index = CRMSResearchIndex()
    index.add_document("glizzes", "Glizzes", "The artist glizzes the sculpture.",
                       "sources/glizzes.txt")
    research = kb.research("gliz", index, limit=10)
    if not any(item["citation"].startswith("glizzes#")
               for item in research.passages or []):
        raise SystemExit("single-z morphology did not expand research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who glizzes Sculpture?")
    if restored_answer.status != "answered" or restored_answer.answer != "Sage":
        raise SystemExit("single-z spelling evidence did not survive persistence")

    print("single-z verb morphology diagnostic: PASS")
    print("cross-relation/source support, consonant-z control, review-only proposal, QA/research transfer, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
