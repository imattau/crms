"""Check grounded entity-only follow-ups in short-turn dialogue.

Run from the project root with:
    python3 experiments/v1_96_dialogue_entity_followup.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def build_knowledge() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for subject, obj, source in (
            ("Ada", "Engine", "source:ada"),
            ("Grace", "Compiler", "source:grace")):
        kb.add_fact(subject, "designed", obj, source)
        kb.teach_question(f"Who designed the {obj}?", relation="designed",
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    return kb


def main() -> None:
    kb = build_knowledge()
    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who designed the Engine?")
    if first.status != "answered" or first.response.answer != "Ada":
        raise SystemExit(f"initial grounded question failed: {first}")

    followup = dialogue.turn("What about the Compiler?")
    if (followup.status != "answered"
            or followup.resolved_question != "Who designed the Compiler?"
            or followup.response is None or followup.response.answer != "Grace"):
        raise SystemExit(f"what-about follow-up failed: {followup}")

    second = dialogue.turn("And the Engine?")
    if (second.status != "answered"
            or second.resolved_question != "Who designed the Engine?"
            or second.response is None or second.response.answer != "Ada"):
        raise SystemExit(f"and-entity follow-up failed: {second}")

    previous = dialogue.last_question
    unsupported = dialogue.turn("What about the Observatory?")
    if (unsupported.status == "answered"
            or dialogue.last_question != previous):
        raise SystemExit("unknown entity follow-up guessed or changed dialogue context")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        index = CRMSResearchIndex()
        sourced_kb = CRMSKnowledgeBase()
        for subject, obj in (("Ada", "Engine"), ("Grace", "Compiler")):
            sentence = f"{subject} designed the {obj}."
            document_id = f"{subject.casefold()}-design"
            index.add_document(document_id, document_id, sentence,
                               f"sources/{document_id}.txt")
            hit = next(item for item in index.search(sentence, limit=5)
                       if item.document_id == document_id)
            sourced_kb.add_fact_from_hit(subject, "designed", obj, index, hit)
            sourced_kb.teach_question(
                f"Who designed the {obj}?", relation="designed",
                answer_field="subject", bound_entity=obj, answer=subject)
        research_dialogue = CRMSDialogue(sourced_kb)
        initial_research = research_dialogue.turn(
            "Who designed the Engine?", research_index=index)
        research_followup = research_dialogue.turn(
            "What about the Compiler?", research_index=index)
        if (initial_research.status != "answered"
                or research_followup.status != "answered"
                or research_followup.response is None
                or research_followup.response.answer != "Grace"):
            raise SystemExit(
                f"research-backed entity follow-up failed: {research_followup}")

        state_path = root / "dialogue.json"
        research_dialogue.save(str(state_path))
        restored = CRMSDialogue.load(sourced_kb, str(state_path))
        persisted = restored.turn("And the Engine?", research_index=index)
        if (persisted.status != "answered" or persisted.response is None
                or persisted.response.answer != "Ada"):
            raise SystemExit(f"persisted research follow-up failed: {persisted}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        dialogue_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        cli_kb = build_knowledge()
        cli_kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(dialogue_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input="Who designed the Engine?\nWhat about the Compiler?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20)
        if ("Ada designed Engine." not in process.stdout
                or "Grace designed Compiler." not in process.stdout):
            raise SystemExit(f"terminal entity follow-up failed:\n{process.stdout}")

    print("dialogue entity follow-up diagnostic: PASS")
    print("question-frame carryover, known-entity gating, unknown-entity abstention, CLI: PASS")


if __name__ == "__main__":
    main()
