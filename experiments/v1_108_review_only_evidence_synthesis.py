"""Group repeated learned fact candidates across sources without auto-commit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_knowledge import CRMSKnowledgeBase
from crms_dialogue import CRMSDialogue
from crms_research import CRMSResearchIndex


def main() -> None:
    source_index = CRMSResearchIndex()
    exact_sentence = "The Helion probe measured plasma temperature."
    source_index.add_document(
        "sentence-first", "Helion probe notes",
        exact_sentence + " The probe was assembled by the university team.",
        "https://research.test/sentence-first")
    sentence_result = CRMSKnowledgeBase().research(
        "Helion probe plasma temperature", source_index)
    if not sentence_result.source_sentences:
        raise SystemExit("research did not return an exact matching source sentence")
    best_sentence = sentence_result.source_sentences[0]
    if best_sentence["text"] != exact_sentence:
        raise SystemExit(
            f"research did not select the exact best sentence: {best_sentence}")
    sentence_render = CRMSKnowledgeBase().render_research(sentence_result)
    if exact_sentence not in sentence_render or "assembled by the university" in sentence_render:
        raise SystemExit(
            f"research output was not sentence-first and concise: {sentence_render}")
    chat_turn = CRMSDialogue(CRMSKnowledgeBase()).turn(
        "How did the Helion probe measure plasma temperature?",
        research_index=source_index)
    if exact_sentence not in chat_turn.text:
        raise SystemExit(
            f"ordinary chat did not surface its best source sentence: {chat_turn}")

    grouped_index = CRMSResearchIndex()
    grouped_kb = CRMSKnowledgeBase()
    for document_id, sentence, subject, obj in (
            ("group-engine", "Ada Lovelace designed the Engine.",
             "Ada Lovelace", "the Engine"),
            ("group-compiler", "Grace Hopper designed the Compiler.",
             "Grace Hopper", "the Compiler")):
        grouped_index.add_document(document_id, document_id, sentence,
                                   f"https://research.test/{document_id}")
        hit = grouped_index.search(sentence, limit=1)[0]
        grouped_kb.add_fact_from_hit(subject, "designed", obj,
                                     grouped_index, hit)
        grouped_kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            research_index=grouped_index, hit=hit)
        grouped_kb.teach_question(
            f"Who designed {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
    grouped_dialogue = CRMSDialogue(grouped_kb)
    grouped_dialogue.subject_entity = "the Engine"
    grouped_dialogue.object_entity = "the Compiler"
    grouped_turn = grouped_dialogue._resolve_distributive_plural(
        "Who designed they each?", research_index=grouped_index)
    if (grouped_turn is None or grouped_turn.research is None
            or len(grouped_turn.research.source_sentences or []) != 2):
        raise SystemExit(
            f"grouped chat discarded its sentence evidence: {grouped_turn}")

    index = CRMSResearchIndex()
    training = [
        ("teach-a", "Ada Lovelace designed the Analytical Engine."),
        ("teach-b", "Grace Hopper designed the Compiler."),
    ]
    for document_id, sentence in training:
        index.add_document(document_id, document_id, sentence,
                           f"https://research.test/{document_id}")
    kb = CRMSKnowledgeBase()
    for document_id, sentence in training:
        hit = index.search(sentence, limit=1)[0]
        subject, obj = ("Ada Lovelace", "the Analytical Engine") if document_id == "teach-a" else ("Grace Hopper", "the Compiler")
        kb.add_fact_from_hit(subject, "designed", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            research_index=index, hit=hit)

    repeated = "Katherine Johnson designed the turbine."
    for document_id in ("research-c", "research-d"):
        index.add_document(document_id, document_id, repeated,
                           f"https://research.test/{document_id}")
    result = kb.research("Who designed the turbine?", index)
    if result.status != "needs_review" or len(result.candidates or []) != 2:
        raise SystemExit(f"expected two review-only source candidates: {result}")
    if len(kb.facts()) != 2:
        raise SystemExit("evidence synthesis promoted a candidate without review")
    rendered = kb.render_research(result)
    required = (
        "Proposed for review (fact): Candidate claim (supports; 2 indexed source(s), not yet accepted)",
        "Katherine Johnson — designed → the turbine",
        "https://research.test/research-c",
        "https://research.test/research-d",
        repeated,
    )
    if any(value not in rendered for value in required):
        raise SystemExit(f"synthesized claim omitted source support: {rendered}")
    if rendered.count("Candidate claim (") != 1:
        raise SystemExit(f"identical claims were not grouped: {rendered}")
    for candidate in result.candidates or []:
        if index.resolve_citation(candidate.source) != repeated:
            raise SystemExit("candidate evidence citation failed exact resolution")

    print("review-only evidence synthesis diagnostic: PASS")
    print("cross-source grouping, claim attribution, exact citations, no auto-commit: PASS")


if __name__ == "__main__":
    main()
