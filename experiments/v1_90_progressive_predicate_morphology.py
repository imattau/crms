"""Check evidence-gated present-participle transfer across spelling classes.

Run from the project root with:
    python3 experiments/v1_90_progressive_predicate_morphology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach_relation(kb: CRMSKnowledgeBase, index: CRMSResearchIndex,
                   relation: str, surface: str, stem: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        document_id = f"{stem}-{number}"
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
    donors = (
        ("design", "designing", "design"), ("walk", "walking", "walk"),
        ("bake", "baking", "bake"), ("create", "creating", "create"),
        ("plan", "planning", "plan"), ("stop", "stopping", "stop"),
        ("study", "studying", "study"), ("carry", "carrying", "carry"),
    )
    for relation, surface, stem in donors:
        teach_relation(kb, index, relation, surface, stem)

    held_out = (
        ("paint", "paint", "painting", "The painter is painting clay models."),
        ("hope", "hope", "hoping", "The volunteer is hoping for clear skies."),
        ("tap", "tap", "tapping", "The technician is tapping the panel."),
        ("copy", "copy", "copying", "The clerk is copying old maps."),
    )
    for relation, surface, inflected, sentence in held_out:
        teach_relation(kb, index, relation, surface, f"target-{relation}")
        document_id = f"heldout-{relation}"
        index.add_document(document_id, document_id, sentence,
                           f"sources/{document_id}.txt")
        result = kb.research(relation, index, limit=30)
        retrieved = {item["citation"].split("#", 1)[0]
                     for item in result.passages or []}
        if document_id not in retrieved:
            raise SystemExit(
                f"{relation} did not expand to held-out form {inflected}")

    # The same induced spelling evidence should carry into a licensed question
    # frame without turning an unqualified proposition into a present-tense
    # claim. Aspect must match the fact evidence exactly.
    teach_relation(kb, index, "admire", "admired", "admire")
    kb.add_fact("Sage", "admire", "Sculpture", "source:sage-admire")
    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        kb.teach_question(f"Who admired the {obj}?", relation="admire",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    progressive_question = "Who is admiring the Sculpture?"
    unscoped = kb.ask(progressive_question)
    if unscoped.status != "unknown":
        raise SystemExit("progressive query used an unqualified fact as current evidence")
    kb.add_fact("Sage", "admire", "Sculpture", "source:sage-current",
                qualifiers={"aspect": "progressive"})
    answer = kb.ask(progressive_question)
    if answer.status != "answered" or answer.answer != "Sage":
        raise SystemExit(f"induced progressive question failed: {answer}")
    if (not any(item.get("surface_form") == "admiring"
               and item.get("suffix") == "ing"
               for item in answer.language_evidence or [])
            or not any(dict(item.get("qualifiers", []))
                       == {"aspect": "progressive"}
                       for item in answer.evidence or [])):
        raise SystemExit("progressive answer omitted its spelling-rule evidence")
    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        kb.teach_question(f"What did {subject} admire?", relation="admire",
                          answer_field="object", bound_entity=subject,
                          answer=obj)
    malformed = kb.ask("What did Ada is admiring?")
    if malformed.status != "unknown":
        raise SystemExit("progressive auxiliary was inserted after the bound subject")

    # One inflected relation family cannot license productive transfer.
    cautious_index = CRMSResearchIndex()
    cautious = CRMSKnowledgeBase()
    teach_relation(cautious, cautious_index, "design", "designing", "only-design")
    teach_relation(cautious, cautious_index, "paint", "paint", "only-paint")
    cautious_index.add_document("control", "control",
                                "The painter is painting a model.",
                                "sources/control.txt")
    control = cautious.research("paint", cautious_index, limit=10)
    control_ids = {item["citation"].split("#", 1)[0]
                   for item in control.passages or []}
    if "control" in control_ids:
        raise SystemExit("one relation family licensed progressive transfer")

    print("progressive predicate morphology diagnostic: PASS")
    print("held-out research expansion across four spelling classes: PASS")
    print("held-out progressive question answering with rule evidence: PASS")
    print("progressive word-order guard: PASS")
    print("one-family abstention: PASS")


if __name__ == "__main__":
    main()
