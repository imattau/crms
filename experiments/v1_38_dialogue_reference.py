"""Check short-turn entity reference resolution over grounded QA frames.

Run from the project root with:
    python3 experiments/v1_38_dialogue_reference.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    facts = [
        ("Ada Lovelace", "designed", "the Analytical Engine", "src-a"),
        ("Grace Hopper", "designed", "the Compiler", "src-b"),
    ]
    for fact in facts:
        kb.add_fact(*fact)

    # Learn both answer directions from varied, explicit fact-backed examples.
    for subject, relation, obj, _source in facts[:2]:
        kb.teach_question(f"Who designed {obj}?", relation=relation,
                          answer_field="subject", bound_entity=obj, answer=subject)
        kb.teach_question(f"What did {subject} design?", relation=relation,
                          answer_field="object", bound_entity=subject, answer=obj)

    dialogue = CRMSDialogue(kb)
    no_context = dialogue.turn("What did she design?")
    if no_context.status != "unknown" or "name the entity" not in no_context.text:
        raise SystemExit(f"dialogue guessed without an antecedent: {no_context}")

    first = dialogue.turn("Who designed the Analytical Engine?")
    if first.response is None or first.response.answer != "Ada Lovelace":
        raise SystemExit(f"first grounded turn failed: {first}")
    followup = dialogue.turn("What did she design?")
    if (followup.resolved_question != "What did Ada Lovelace design?"
            or followup.response is None
            or followup.response.answer != "the Analytical Engine"):
        raise SystemExit(f"grounded pronoun follow-up failed: {followup}")

    # A reverse role question can generalize from the stored relation and
    # fact even when that exact frame was not taught separately.
    partial_kb = CRMSKnowledgeBase()
    for subject, relation, obj, source in facts:
        partial_kb.add_fact(subject, relation, obj, source)
        partial_kb.teach_question(
            f"Who designed {obj}?", relation=relation,
            answer_field="subject", bound_entity=obj, answer=subject)
    partial_dialogue = CRMSDialogue(partial_kb)
    partial_dialogue.turn("Who designed the Analytical Engine?")
    unlearned_frame = partial_dialogue.turn("What did she design?")
    if (unlearned_frame.status != "answered"
            or unlearned_frame.resolved_question
            != "What did Ada Lovelace design?"
            or unlearned_frame.response is None
            or unlearned_frame.response.answer != "the Analytical Engine"
            or not unlearned_frame.response.evidence):
        raise SystemExit(
            f"reverse question did not use its grounded relation and fact: "
            f"{unlearned_frame}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "dialogue.json"
        dialogue.save(str(path))
        restored = CRMSDialogue.load(kb, str(path))
        turn = restored.turn("Who designed it?")
    # Last answer from the follow-up is the engine, so this should resolve.
    if (turn.resolved_question != "Who designed the Analytical Engine?"
            or turn.response is None or turn.response.answer != "Ada Lovelace"):
        raise SystemExit(f"persisted context did not resolve pronoun: {turn}")

    index = CRMSResearchIndex()
    index.add_document("a", "Ada", "Ada Lovelace designed the Analytical Engine.",
                       "sources/ada.txt")
    index.add_document("g", "Grace", "Grace Hopper designed the Compiler.",
                       "sources/grace.txt")
    research_dialogue = CRMSDialogue(kb)
    first_research = research_dialogue.turn(
        "Who designed the Analytical Engine?", research_index=index)
    followup_research = research_dialogue.turn(
        "What did she design?", research_index=index)
    if (first_research.status != "answered"
            or followup_research.resolved_question != "What did Ada Lovelace design?"
            or followup_research.status != "answered"):
        raise SystemExit(f"research-backed dialogue lost its referent: {followup_research}")

    topic_index = CRMSResearchIndex()
    topic_index.add_document(
        "crms-retrieval", "CRMS retrieval",
        "CRMS ranks retrieved source evidence by direct topic relevance.",
        "sources/crms-retrieval.txt")
    topic_index.add_document(
        "crms-conflicts", "CRMS conflicts",
        "CRMS handles conflicts by flagging inconsistent claims for review.",
        "sources/crms-conflicts.txt")
    topic_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    topic_first = topic_dialogue.turn(
        "What does CRMS say about retrieval?", research_index=topic_index)
    if topic_first.status != "sources_found":
        raise SystemExit(f"explicit research topic was not found: {topic_first}")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "dialogue.json"
        topic_dialogue.save(str(path))
        topic_dialogue = CRMSDialogue.load(CRMSKnowledgeBase(), str(path))
    topic_followup = topic_dialogue.turn(
        "How does it handle conflicts?", research_index=topic_index)
    if (topic_followup.resolved_question
            != "How does CRMS handle conflicts?"
            or topic_followup.status != "sources_found"):
        raise SystemExit(
            f"saved research-topic pronoun did not resolve: {topic_followup}")

    unrelated = research_dialogue.turn("Who discovered quantum telepathy?")
    if unrelated.status != "unknown":
        raise SystemExit(f"unsupported unrelated question unexpectedly answered: {unrelated}")
    after_unrelated = research_dialogue.turn("What did she design?")
    if "name the entity" not in after_unrelated.text:
        raise SystemExit("unrelated unanswered turn left a stale pronoun referent")

    dialogue.clear()
    ambiguous = dialogue.turn("What did she and he design?")
    if ambiguous.status != "unknown" or "name the entity" not in ambiguous.text:
        raise SystemExit(f"multiple pronouns were guessed: {ambiguous}")

    clarification_kb = CRMSKnowledgeBase()
    clarification_facts = [
        ("Ada Lovelace", "designed", "the Analytical Engine", "a"),
        ("Ada Lovelace", "designed", "the Difference Engine", "b"),
        ("Grace Hopper", "designed", "the Compiler", "c"),
    ]
    for fact in clarification_facts:
        clarification_kb.add_fact(*fact)
    for subject, obj in (("Ada Lovelace", "the Analytical Engine"),
                         ("Grace Hopper", "the Compiler")):
        clarification_kb.teach_question(
            f"What did {subject} design?", relation="designed",
            answer_field="object", bound_entity=subject, answer=obj)
        clarification_kb.teach_question(
            f"Who designed {obj}?", relation="designed",
            answer_field="subject", bound_entity=obj, answer=subject)
    chooser = CRMSDialogue(clarification_kb)
    ambiguous_answer = chooser.turn("What did Ada Lovelace design?")
    if ambiguous_answer.status != "ambiguous" or not chooser.pending_result:
        raise SystemExit(f"ambiguous response did not open clarification: {ambiguous_answer}")
    with tempfile.TemporaryDirectory() as folder:
        pending_path = Path(folder) / "pending.json"
        chooser.save(str(pending_path))
        chooser = CRMSDialogue.load(clarification_kb, str(pending_path))
    invalid = chooser.turn("third one")
    if invalid.status != "ambiguous" or not chooser.pending_result:
        raise SystemExit("invalid ordinal did not preserve the pending clarification")
    selected = chooser.turn("the second one")
    if selected.response is None or selected.response.answer != "the Difference Engine":
        raise SystemExit(f"ordinal clarification selected the wrong answer: {selected}")
    coreferent = chooser.turn("Who designed it?")
    if coreferent.response is None or coreferent.response.answer != "Ada Lovelace":
        raise SystemExit(f"selected answer did not become the dialogue referent: {coreferent}")

    print("dialogue reference diagnostic: PASS")
    print("context abstention, entity follow-up, ambiguity selection, object/subject alternation, persistence: PASS")


if __name__ == "__main__":
    main()
