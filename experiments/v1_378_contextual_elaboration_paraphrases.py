"""Polite continuation requests should use the active dialogue context."""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_act, classify_user_intent, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    variants = (
        "Could you tell me more?",
        "Please tell me more",
        "Can you say more?",
        "Could you elaborate?",
        "Would you go into more detail, please?",
    )
    for text in variants:
        require(classify_act(text) == "elaboration",
                f"continuation paraphrase missed the elaboration route: {text}")

    # A continuation request must not swallow a content-bearing question.
    require(classify_act("Can you tell me more about Python?") is None,
            "an elaboration request naming a topic was treated as content-free")
    require(classify_act("Could you tell me which engine Ada designed?") is None,
            "an ordinary information request was treated as elaboration")

    knowledge = CRMSKnowledgeBase()
    knowledge.add_fact("Ada Lovelace", "wrote", "the first algorithm", "source-a")
    dialogue = CRMSDialogue(knowledge)
    first = respond(dialogue, "Who wrote the first algorithm?")
    require(first.status == "answered", f"test setup failed: {first.text}")

    hypothesis = classify_user_intent(dialogue, "Could you tell me more?")
    require(hypothesis is not None
            and hypothesis.dialogue_act == "continuation-request"
            and hypothesis.task_intent == "continue-current-task"
            and hypothesis.decision == "selected"
            and "current_topic_available" in hypothesis.context_predicates,
            "polite elaboration did not use the active topic")
    elaborated = respond(dialogue, "Could you tell me more?")
    require(elaborated.status == "elaborated"
            and "Ada Lovelace — wrote → the first algorithm" in elaborated.text,
            f"polite elaboration did not return the grounded overview: {elaborated}")

    no_topic = CRMSDialogue(knowledge)
    prompt = respond(no_topic, "Could you tell me more?")
    require(prompt.status == "clarify"
            and no_topic.pending_dialogue_slot == "elaboration_topic",
            "polite elaboration without a topic did not ask for one")
    clarification = classify_user_intent(no_topic, "Ada Lovelace")
    require(clarification is not None
            and clarification.dialogue_act == "answer-clarification"
            and clarification.selected_value == "Ada Lovelace",
            "topic answer was not interpreted against the open elaboration slot")
    overview = respond(no_topic, "Ada Lovelace")
    require(overview.status == "elaborated"
            and "Ada Lovelace — wrote → the first algorithm" in overview.text,
            "polite elaboration clarification did not complete the task")

    with tempfile.TemporaryDirectory(prefix="crms-elaboration-paraphrase-") as folder:
        root = Path(folder)
        knowledge.save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--rules", str(root / "rules.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        completed = subprocess.run(
            command,
            input="Who wrote the first algorithm?\nCould you tell me more?\nGoodbye\n",
            text=True, capture_output=True, check=True, timeout=30)
        require("About Ada Lovelace:" in completed.stdout
                and "Ada Lovelace — wrote → the first algorithm" in completed.stdout,
                f"interactive chat missed the contextual elaboration: {completed.stdout}")

    print("polite continuation forms use the elaboration route: PASS")
    print("named-topic and ordinary information requests remain content turns: PASS")
    print("current topic controls elaboration and its cited overview: PASS")
    print("missing topic opens and resolves a contextual clarification: PASS")
    print("interactive chat routes polite elaboration to the grounded overview: PASS")


if __name__ == "__main__":
    main()
