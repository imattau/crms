"""Resolve explicit distributive plurals over two grounded dialogue entities."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def build() -> tuple[CRMSKnowledgeBase, CRMSResearchIndex]:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    facts = [
        ("Ada", "designed", "Engine", "design-a"),
        ("Grace", "designed", "Compiler", "design-g"),
        ("Ada", "built", "Widget", "build-a"),
        ("Engine", "built", "Rotor", "build-e"),
    ]
    for subject, relation, obj, source in facts:
        kb.add_fact(subject, relation, obj, source)
    questions = [
        ("Who designed Engine?", "designed", "subject", "Engine", "Ada"),
        ("Who designed Compiler?", "designed", "subject", "Compiler", "Grace"),
        ("What did Ada build?", "built", "object", "Ada", "Widget"),
        ("What did Engine build?", "built", "object", "Engine", "Rotor"),
    ]
    for question, relation, answer_field, entity, answer in questions:
        kb.teach_question(question, relation=relation,
                          answer_field=answer_field, bound_entity=entity,
                          answer=answer)
    for doc_id, text in (
            ("design-a", "Ada designed Engine."),
            ("design-g", "Grace designed Compiler."),
            ("build-a", "Ada built Widget."),
            ("build-e", "Engine built Rotor.")):
        index.add_document(doc_id, doc_id, text,
                           f"https://research.test/{doc_id}")
    return kb, index


def main() -> None:
    kb, _index = build()
    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who designed Engine?")
    if first.status != "answered":
        raise SystemExit("could not establish the two grounded antecedents")
    group = dialogue.turn("What did they each build?")
    if (group.status != "answered" or group.response is None
            or group.response.answer != "Ada: Widget; Engine: Rotor"
            or len(group.grouped_results or []) != 2
            or "Ada: Widget." not in group.text
            or "Engine: Rotor." not in group.text):
        raise SystemExit(f"distributive plural answers were not combined: {group}")
    source_sets = [
        {source for fact in (item["response"].evidence or [])
         for source in fact.get("sources", ())}
        for item in group.grouped_results or []
    ]
    if source_sets != [{"build-a"}, {"build-e"}]:
        raise SystemExit(f"grouped answers lost their individual evidence: {source_sets}")

    kb, index = build()
    research_dialogue = CRMSDialogue(kb)
    if research_dialogue.turn("Who designed Engine?",
                              research_index=index).status != "answered":
        raise SystemExit("research path could not establish antecedents")
    researched = research_dialogue.turn(
        "What did each of them build?", research_index=index)
    if (researched.status != "answered"
            or researched.research is None
            or len(researched.grouped_results or []) != 2
            or any(item["research"] is None
                   or not item["research"].passages
                   for item in researched.grouped_results or [])
            or not {
                passage["citation"]
                for passage in researched.research.passages or []
            }.issuperset({
                passage["citation"]
                for item in researched.grouped_results or []
                for passage in item["research"].passages or []
            })
            or "https://research.test/build-a" not in researched.text
            or "https://research.test/build-e" not in researched.text):
        raise SystemExit(f"grouped research lost answer citations: {researched}")

    kb, _index = build()
    ambiguous_dialogue = CRMSDialogue(kb)
    ambiguous_dialogue.turn("Who designed Engine?")
    kb.add_fact("Ada", "built", "Crane", "build-a-second")
    incomplete = ambiguous_dialogue.turn("What did they each build?")
    if (incomplete.status != "unknown" or incomplete.response is None
            or incomplete.response.answer is not None
            or incomplete.grouped_results is not None
            or "one supported answer for each entity" not in incomplete.text):
        raise SystemExit(f"partial grouped answer escaped ambiguity gate: {incomplete}")

    kb, _index = build()
    singular_dialogue = CRMSDialogue(kb)
    singular_dialogue.turn("Who designed Engine?")
    singular = singular_dialogue.turn("What did they build?")
    if singular.status != "unknown" or "multiple bindings" not in singular.text:
        raise SystemExit("singular/plural ambiguity was silently converted to a group")

    print("distributive plural dialogue diagnostic: PASS")
    print("explicit each-binding, complete-only aggregation, evidence retention, research citations, ambiguity abstention: PASS")


if __name__ == "__main__":
    main()
