"""Check evidence-bound possessive-property dialogue follow-ups."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def build_knowledge(*, two_owners: bool = False) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    records = (("the Engine", "has color", "Blue", "color"),
               ("the Chassis", "has color", "Red", "color"),
               ("the Engine", "has size", "large", "size"),
               ("the Chassis", "has size", "small", "size"),
               ("the Engine", "has entrance", "east side", "entrance"),
               ("the Chassis", "has entrance", "north side", "entrance"))
    for subject, relation, obj, _kind in records:
        kb.add_fact(subject, relation, obj, f"spec:{subject}:{relation}")
    for subject, relation, obj, _kind in records:
        property_name = {"has color": ("What is", "color"),
                         "has size": ("What is", "size"),
                         "has entrance": ("Where is", "entrance")}[relation]
        wh_aux, property_label = property_name
        kb.teach_question(f"{wh_aux} the {property_label} of {subject}?",
                          relation=relation, answer_field="object",
                          bound_entity=subject, answer=obj)
        if relation == "has size":
            kb.teach_question(f"What was the size of {subject}?",
                              relation=relation, answer_field="object",
                              bound_entity=subject, answer=obj)
    if two_owners:
        kb.add_fact("Blue", "has size", "tiny", "spec:size-blue")
        kb.teach_question("What is the size of Blue?", relation="has size",
                          answer_field="object", bound_entity="Blue", answer="tiny")
    return kb


def main() -> None:
    dialogue = CRMSDialogue(build_knowledge())
    first = dialogue.turn("What is the color of the Engine?")
    location = dialogue.turn("Where is its entrance?")
    past_followup = dialogue.turn("What was its size?")
    followup = dialogue.turn("What's its size?")
    if (first.status != "answered" or first.response is None
            or first.response.answer != "Blue"
            or location.status != "answered" or location.response is None
            or location.response.answer != "east side"
            or location.resolved_question != "Where is the entrance of the Engine?"
            or past_followup.status != "answered" or past_followup.response is None
            or past_followup.response.answer != "large"
            or past_followup.resolved_question != "What was the size of the Engine?"
            or followup.status != "answered" or followup.response is None
            or followup.response.answer != "large"
            or followup.resolved_question != "What is the size of the Engine?"):
        raise SystemExit(f"possessive property follow-up failed: {followup}")

    ambiguous_dialogue = CRMSDialogue(build_knowledge(two_owners=True))
    if ambiguous_dialogue.turn("What is the color of the Engine?").status != "answered":
        raise SystemExit("could not establish possessive-reference context")
    ambiguous = ambiguous_dialogue.turn("What is its size?")
    if (ambiguous.status != "ambiguous" or ambiguous.response is None
            or set(ambiguous.response.candidates or ()) != {"Blue", "the Engine"}):
        raise SystemExit(f"multiple supported possessors were not clarified: {ambiguous}")

    unknown_dialogue = CRMSDialogue(build_knowledge())
    unknown_dialogue.turn("What is the color of the Engine?")
    unknown = unknown_dialogue.turn("What is its mass?")
    if unknown.status != "unknown" or "name the entity" not in unknown.text:
        raise SystemExit(f"unsupported possessive property was guessed: {unknown}")

    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    source_facts = (("engine-color", "the Engine", "has color", "Blue"),
                    ("chassis-color", "the Chassis", "has color", "Red"),
                    ("engine-size", "the Engine", "has size", "large"),
                    ("chassis-size", "the Chassis", "has size", "small"),
                    ("engine-entrance", "the Engine", "has entrance", "east side"),
                    ("chassis-entrance", "the Chassis", "has entrance", "north side"))
    for document_id, subject, relation, obj in source_facts:
        sentence = f"{subject} {relation} {obj}."
        index.add_document(document_id, document_id, sentence, f"docs/{document_id}.txt")
        hit = next(item for item in index.search(sentence, limit=5)
                   if item.document_id == document_id)
        kb.add_fact_from_hit(subject, relation, obj, index, hit)
    for _document_id, subject, relation, obj in source_facts:
        wh_aux, property_name = {
            "has color": ("What is", "color"),
            "has size": ("What is", "size"),
            "has entrance": ("Where is", "entrance"),
        }[relation]
        kb.teach_question(f"{wh_aux} the {property_name} of {subject}?",
                          relation=relation, answer_field="object",
                          bound_entity=subject, answer=obj)
    research_dialogue = CRMSDialogue(kb)
    research_dialogue.turn("What is the color of the Engine?", research_index=index)
    researched = research_dialogue.turn("What is its size?", research_index=index)
    if (researched.status != "answered" or researched.research is None
            or researched.response is None or researched.response.answer != "large"
            or not researched.research.response.evidence):
        raise SystemExit(f"research-backed possessive resolution lost evidence: {researched}")

    print("possessive dialogue diagnostic: PASS")
    print("unique evidence binding, ambiguity clarification, abstention, and research provenance: PASS")


if __name__ == "__main__":
    main()
