"""Learn final-o → -oes as a distinct evidence-grounded spelling class."""

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
        kb.teach_fact_pattern(sentence, subject=subject, relation=relation,
                              obj=obj, source=source,
                              predicate_phrase=surface)


def candidate_for(kb: CRMSKnowledgeBase, text: str, relation: str):
    return next((candidate for candidate in kb.propose_facts(
        text, source=f"review:{relation}")
        if candidate.relation == relation and candidate.subject == "Sage"), None)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "go", "goes", "go-doc")
    teach(kb, "do", "does", "do-doc")
    teach(kb, "walk", "walks", "walk-doc")
    teach(kb, "paint", "paints", "paint-doc")
    teach(kb, "echo", "echo", "echo-doc")
    teach(kb, "go", "went", "go-past-doc")

    go_forms, _ = kb._predicate_forms_for_relation(
        ("go",), kb._observed_predicates_by_relation().get(("go",), set()))
    if not {("goes",), ("went",)}.issubset(go_forms) or ("goed",) in go_forms:
        raise SystemExit(f"final-o and irregular classes interfered: {go_forms}")

    kb.add_fact("Sage", "echo", "Sculpture", "source:sage-echo")
    proposal = candidate_for(kb, "Sage echoes Sculpture", "echo")
    rule = next((item for item in (proposal.language_evidence if proposal else ())
                 if item.get("kind") == "induced_suffix"), None)
    if (proposal is None or rule is None
            or rule.get("context") != "final-o-es"
            or rule.get("suffix") != "es"
            or {item["relation"] for item in rule["support"]} != {"do", "go"}
            or any(not item["sources"] for item in rule["support"])):
        raise SystemExit("independent final-o evidence did not license echo → echoes")
    if any("review:echoes" in fact.sources for fact in kb.facts()
           if fact.relation == "echo"):
        raise SystemExit("review-only inflection was committed as fact evidence")

    # The learned class must not leak its -es ending to unrelated stems, and
    # ordinary -s evidence must remain distinguishable from the final-o class.
    talk_forms, _ = kb._predicate_forms_for_relation(("talk",), set())
    if ("talkes",) in talk_forms or ("talks",) not in talk_forms:
        raise SystemExit(f"final-o rule contaminated ordinary -s forms: {talk_forms}")
    if candidate_for(kb, "Sage walkes Sculpture", "walk") is not None:
        raise SystemExit("final-o -es transferred to a consonant-final stem")

    # One donor relation cannot establish a productive class, even across files.
    one_family = CRMSKnowledgeBase()
    teach(one_family, "go", "goes", "go-doc-a")
    teach(one_family, "go", "goes", "go-doc-b")
    forms, _ = one_family._predicate_forms_for_relation(("echo",), set())
    if ("echoes",) in forms:
        raise SystemExit("one relation family licensed final-o -es transfer")

    kb.teach_question("Who echo Engine?", relation="echo",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who echo Compiler?", relation="echo",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who echoes Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"final-o morphology did not transfer to QA: {answer}")
    if not any(item.get("context") == "final-o-es"
               for item in answer.language_evidence or []):
        raise SystemExit("QA omitted final-o morphology evidence")

    index = CRMSResearchIndex()
    index.add_document("echoes", "Echoes", "The chamber echoes softly.",
                       "sources/echoes.txt")
    research = kb.research("echo", index, limit=10)
    if not any(item["citation"].startswith("echoes#")
               for item in research.passages or []):
        raise SystemExit("final-o form did not expand research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        persisted = candidate_for(restored, "Sage echoes Sculpture", "echo")
        if (persisted is None or not any(
                item.get("context") == "final-o-es"
                for item in persisted.language_evidence)):
            raise SystemExit("final-o morphology failed after persistence")

    print("final-o -es morphology diagnostic: PASS")
    print("cross-relation/source support, final-o restriction, review-only proposal, "
          "QA/research transfer, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
