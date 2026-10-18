"""Answer explicit distributive questions over two named stored subjects."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def build() -> tuple[CRMSKnowledgeBase, CRMSResearchIndex]:
    kb = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    for subject, relation, obj, source in (
            ("Ada", "built", "Widget", "build-a"),
            ("Engine", "built", "Rotor", "build-e"),
            ("Grace", "built", "Compiler", "build-g")):
        kb.add_fact(subject, relation, obj, source)
    for question, entity, answer in (
            ("What did Ada build?", "Ada", "Widget"),
            ("What did Engine build?", "Engine", "Rotor"),
            ("What did Grace build?", "Grace", "Compiler")):
        kb.teach_question(question, relation="built", answer_field="object",
                          bound_entity=entity, answer=answer)
    for doc_id, text in (
            ("build-a", "Ada built Widget."),
            ("build-e", "Engine built Rotor."),
            ("build-g", "Grace built Compiler.")):
        index.add_document(doc_id, doc_id, text,
                           f"https://research.test/{doc_id}")
    return kb, index


def main() -> None:
    kb, index = build()
    question = "What did Ada and Engine each build?"
    result = kb.ask(question)
    expected = "Ada: Widget; Engine: Rotor"
    evidence_sources = {
        source for fact in result.evidence or []
        for source in fact.get("sources", ())
    }
    if (result.status != "answered" or result.answer != expected
            or evidence_sources != {"build-a", "build-e"}
            or "Each entity was answered separately" not in (result.request or "")):
        raise SystemExit(f"named-subject each-question failed: {result}")

    marked = kb.ask("What did both Ada and Engine each build?")
    if marked.status != "answered" or marked.answer != expected:
        raise SystemExit(f"optional both-cue failed: {marked}")

    research = kb.research(question, index, limit=10)
    if (research.status != "answered" or research.response is None
            or research.response.answer != expected
            or not research.passages
            or not {"https://research.test/build-a",
                    "https://research.test/build-e"}.issubset(
                        {item["location"] for item in research.passages})):
        raise SystemExit(f"research did not preserve both grounded results: {research}")

    # Boolean each-questions use AND: all named subjects must have positive
    # evidence for a positive answer; an explicit negative makes the answer no.
    polar = CRMSKnowledgeBase()
    for subject, obj, source, truth in (
            ("Ada", "Widget", "polar-a", True),
            ("Engine", "Widget", "polar-e", True),
            ("Grace", "Compiler", "polar-g", True)):
        polar.add_fact(subject, "designed", obj, source)
        polar.teach_polar_question(
            f"Did {subject} design {obj}?", subject=subject,
            relation="designed", obj=obj, answer=truth)
    polar.add_negative_fact("Grace", "designed", "Widget", "polar-negative")
    yes = polar.ask("Did Ada and Engine each design Widget?")
    no = polar.ask("Did Ada and Grace each design Widget?")
    if (yes.status != "answered" or yes.truth is not True
            or no.status != "answered" or no.truth is not False):
        raise SystemExit(f"each-question Boolean semantics failed: {yes}, {no}")

    kb, _index = build()
    kb.add_fact("Ada", "built", "Crane", "build-a-second")
    ambiguous = kb.ask(question)
    if (ambiguous.status != "ambiguous" or ambiguous.answer is not None
            or not ambiguous.evidence
            or "no partial 'each' answer" not in (ambiguous.request or "")):
        raise SystemExit(f"ambiguous member leaked a partial answer: {ambiguous}")

    unknown = kb.ask("What did Ada and Engine each repair?")
    if unknown.status != "unknown" or unknown.answer is not None:
        raise SystemExit(f"unsupported member query returned a partial value: {unknown}")

    ordinary = kb.ask("What did Ada and Engine build?")
    if ordinary.status == "answered" and ordinary.answer == expected:
        raise SystemExit("the parser assumed distributive meaning without 'each'")

    print("distributive named-subject question diagnostic: PASS")
    print("frame reuse, evidence aggregation, research retrieval, Boolean AND, unknown/ambiguity abstention, no implicit distributivity: PASS")


if __name__ == "__main__":
    main()
