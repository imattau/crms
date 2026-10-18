"""Check cross-relation induction of the sibilant-final -es form.

Run from the project root with:
    python3 experiments/v1_120_sibilant_es_morphology.py
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
    for index, (subject, obj) in enumerate((("Ada", "Engine"),
                                             ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        source = f"{document}#example-{index}"
        kb.add_fact(subject, relation, obj, source)
        kb.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "pass", "passes", "pass-doc")
    teach(kb, "watch", "watches", "watch-doc")
    teach(kb, "fix", "fixes", "fix-doc")
    teach(kb, "mix", "mix", "mix-doc")
    teach(kb, "walk", "walk", "walk-doc")

    proposal = next((item for item in kb.propose_facts(
        "Sage mixes Sculpture", source="review:mixes")
        if item.relation == "mix" and item.subject == "Sage"), None)
    rule = next((item for item in (proposal.language_evidence if proposal else [])
                 if item.get("kind") == "induced_suffix"), None)
    if (proposal is None or rule is None or rule.get("context") != "sibilant-es"
            or rule.get("suffix") != "es"
            or {item["relation"] for item in rule["support"]}
            != {"pass", "watch", "fix"}
            or any(not item["sources"] for item in rule["support"])):
        raise SystemExit("independent sibilant examples did not license mix → mixes")
    if any(fact.relation == "mix" and fact.subject == "Sage"
           for fact in kb.facts()):
        raise SystemExit("inflected proposal was committed without review")

    # The learned -es class must not create an -es form on a nonsibilant stem.
    if any(item.relation == "walk" for item in kb.propose_facts(
            "Sage walkes Sculpture", source="review:walkes")):
        raise SystemExit("sibilant -es transferred to a nonsibilant stem")

    # Several examples from one relation family cannot license the productive
    # rule, even when they come from distinct documents.
    one_family = CRMSKnowledgeBase()
    teach(one_family, "pass", "passes", "pass-doc-a")
    teach(one_family, "pass", "passes", "pass-doc-b")
    if any(item.relation == "mix" for item in one_family.propose_facts(
            "Sage mixes Sculpture", source="review:unsupported")):
        raise SystemExit("one relation family licensed productive -es transfer")

    # Verify that the induced form reaches question answering and retains its
    # source and spelling evidence without adding it to the fact store.
    kb.add_fact("Sage", "mix", "Sculpture", "source:sage-mix")
    kb.teach_question("Who mix Engine?", relation="mix",
                      answer_field="subject", bound_entity="Engine", answer="Ada")
    kb.teach_question("Who mix Compiler?", relation="mix",
                      answer_field="subject", bound_entity="Compiler", answer="Bea")
    answer = kb.ask("Who mixes Sculpture?")
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"induced -es form did not transfer to QA: {answer}")
    if not any(item.get("suffix") == "es" and item.get("context") == "sibilant-es"
               for item in answer.language_evidence or []):
        raise SystemExit("QA answer omitted the induced sibilant evidence")

    index = CRMSResearchIndex()
    index.add_document("mixes", "Mixes", "The athlete mixes ingredients.",
                       "sources/mixes.txt")
    research = kb.research("mix", index, limit=10)
    if not any(item["citation"].startswith("mixes#")
               for item in research.passages or []):
        raise SystemExit("induced -es form did not expand research retrieval")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_answer = restored.ask("Who mixes Sculpture?")
        if (restored_answer.status != "answered"
                or restored_answer.answer != "Sage"
                or not any(item.get("context") == "sibilant-es"
                           for item in restored_answer.language_evidence or [])):
            raise SystemExit("sibilant morphology did not survive persistence")

    regular = CRMSKnowledgeBase()
    teach(regular, "walk", "walked", "walk-past-doc")
    teach(regular, "paint", "painted", "paint-past-doc")
    teach(regular, "pass", "passes", "pass-present-doc")
    past = next((item for item in regular.propose_facts(
        "Sage passed Engine", source="review:passed")
        if item.relation == "pass" and item.subject == "Sage"), None)
    if (past is None or not any(
            item.get("suffix") == "ed" and item.get("context") == "other-ending"
            for item in past.language_evidence)):
        raise SystemExit("ordinary -ed stopped applying to sibilant-final verbs")

    print("sibilant -es morphology diagnostic: PASS")
    print("cross-relation/source support, sibilant class restriction, review-only proposal, QA/research transfer, persistence, one-family abstention: PASS")


if __name__ == "__main__":
    main()
