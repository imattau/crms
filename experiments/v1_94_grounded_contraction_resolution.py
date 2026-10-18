"""Check evidence-selected expansion of ambiguous apostrophe-s questions.

Run from the project root with:
    python3 experiments/v1_94_grounded_contraction_resolution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from experiments.v1_90_progressive_predicate_morphology import teach_relation


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    for relation, surface, stem in (
            ("bake", "baking", "bake"),
            ("create", "creating", "create")):
        teach_relation(kb, index, relation, surface, stem)
    teach_relation(kb, index, "admire", "admired", "admire")
    for subject, obj in (("Ada", "Engine"), ("Bea", "Compiler")):
        kb.teach_question(f"Who admired the {obj}?", relation="admire",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    kb.add_fact("Sage", "admire", "Sculpture", "source:sage-unscoped")
    kb.add_fact("Sage", "admire", "Sculpture", "source:sage-progressive",
                qualifiers={"aspect": "progressive"})

    dialogue = CRMSDialogue(kb)
    result = dialogue.turn("Who’s admiring the Sculpture?", research_index=index)
    if (result.status != "answered"
            or result.resolved_question != "Who is admiring the Sculpture?"
            or result.response is None or result.response.answer != "Sage"
            or not result.research):
        raise SystemExit(f"grounded contraction expansion failed: {result}")
    if not any(dict(item.get("qualifiers", [])) == {"aspect": "progressive"}
               for item in result.response.evidence or []):
        raise SystemExit("contraction answer lost its exact aspect evidence")

    possessive = dialogue.turn("Who designed Ada's Engine?")
    if possessive.status == "answered":
        raise SystemExit("proper-name possessive was mistaken for a contraction")

    retrieval_index = CRMSResearchIndex()
    source_text = "The field note asks: Who is designing the Engine?"
    retrieval_index.add_document("design-note", "Design Note", source_text,
                                 "notes/design.txt")
    retrieval_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    retrieved = retrieval_dialogue.turn(
        "Who's designing the Engine?", research_index=retrieval_index)
    if (retrieved.status != "sources_found"
            or retrieved.resolved_question != "Who is designing the Engine?"
            or not retrieved.research
            or not any(item["citation"].startswith("design-note#")
                       for item in retrieved.research.passages or [])):
        raise SystemExit(f"source-supported contraction did not reach research: {retrieved}")

    print("grounded contraction resolution diagnostic: PASS")
    print("QA and full-coverage research readings, exact aspect, possessive guard: PASS")


if __name__ == "__main__":
    main()
