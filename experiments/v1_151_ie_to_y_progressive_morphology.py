"""Learn the grounded ie → y change before progressive -ing."""

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
    teach(kb, "die", "dying", "die-doc")
    teach(kb, "lie", "lying", "lie-doc")
    teach(kb, "walk", "walking", "walk-doc")
    teach(kb, "paint", "painting", "paint-doc")
    teach(kb, "tie", "tie", "tie-doc")
    kb.add_fact("Sage", "tie", "Sculpture", "source:sage-tie")

    proposal = candidate_for(kb, "Sage tying Sculpture", "tie")
    rule = next((item for item in (proposal.language_evidence if proposal else ())
                 if item.get("kind") == "induced_suffix"), None)
    if (proposal is None or rule is None
            or rule.get("context") != "final-ie-y"
            or rule.get("suffix") != "ing"
            or {item["relation"] for item in rule["support"]} != {"die", "lie"}
            or any(not item["sources"] for item in rule["support"])):
        raise SystemExit("independent ie → y evidence did not license tie → tying")
    if any("review:tying" in fact.sources for fact in kb.facts()
           if fact.relation == "tie"):
        raise SystemExit("review-only progressive proposal was committed")

    forms, _ = kb._predicate_forms_for_relation(("tie",), set())
    if ("tieing",) in forms:
        raise SystemExit("generic progressive evidence overrode ie → y spelling")
    one_family = CRMSKnowledgeBase()
    teach(one_family, "die", "dying", "die-doc-a")
    teach(one_family, "die", "dying", "die-doc-b")
    if ("tying",) in one_family._predicate_forms_for_relation(
            ("tie",), set())[0]:
        raise SystemExit("one relation family licensed ie → y transfer")

    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        kb.teach_question(f"Who tie {obj}?", relation="tie",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    kb.add_fact("Sage", "tie", "Sculpture", "source:sage-progressive",
                qualifiers={"aspect": "progressive"})
    answer = kb.ask("Who is tying Sculpture?")
    if (answer.status != "answered" or answer.answer != "Sage"
            or not any(item.get("context") == "final-ie-y"
                       for item in answer.language_evidence or [])):
        raise SystemExit(f"ie → y form did not transfer to progressive QA: {answer}")

    index = CRMSResearchIndex()
    index.add_document("tying", "Tying", "The maker is tying the sculpture.",
                       "sources/tying.txt")
    research = kb.research("tie", index, limit=10)
    if not any(item["citation"].startswith("tying#")
               for item in research.passages or []):
        raise SystemExit("ie → y progressive form did not expand research")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        persisted = candidate_for(restored, "Sage tying Sculpture", "tie")
        if (persisted is None or not any(
                item.get("context") == "final-ie-y"
                for item in persisted.language_evidence)):
            raise SystemExit("ie → y evidence failed after persistence")

    print("ie-to-y progressive morphology diagnostic: PASS")
    print("cross-relation/source support, final-e/generic controls, review-only "
          "proposal, progressive QA, research transfer, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
