"""Source-backed follow-ups keep the user-named topic and gate on it."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

TEXT = (
    "Rome is the capital of Italy. The Colosseum is an amphitheatre in Rome. "
    "It was completed in 80 AD under Emperor Titus.\n\n"
    "Paris is the capital of France. The Eiffel Tower is located in Paris. "
    "It was completed in 1889.")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document("cities", "cities.txt", TEXT)
    dialogue = CRMSDialogue(CRMSKnowledgeBase())

    dialogue.turn("Where is the Eiffel Tower?", research_index=index)
    names = [item["entity"] for item in dialogue.source_mentions]
    require(names[:1] == ["Eiffel Tower"],
            f"sentence-initial 'The X' was not kept as a referent: {names}")

    dialogue.turn("Where is the Colosseum?", research_index=index)
    pronoun = dialogue.turn("when was it completed?", research_index=index)
    require("Colosseum" in pronoun.resolved_question
            and "Eiffel" not in pronoun.resolved_question,
            f"'it' did not bind to the entity the user asked about: "
            f"{pronoun.resolved_question!r}")

    dialogue.turn("Where is the Eiffel Tower?", research_index=index)
    swapped = dialogue.turn("and the Colosseum?", research_index=index)
    require(swapped.resolved_question == "Where is the Colosseum?",
            f"entity follow-up after a source-only answer failed: {swapped}")

    dialogue.turn("what is the capital of France?", research_index=index)
    italy = dialogue.turn("and Italy?", research_index=index)
    require(italy.resolved_question == "what is the capital of Italy?",
            f"'and Italy?' was not carried to the new entity: {italy}")

    recall = dialogue.turn("what did I just ask?", research_index=index)
    require("capital of Italy" in recall.text,
            f"last-question recall failed: {recall.text!r}")
    require(CRMSDialogue(CRMSKnowledgeBase()).turn(
        "what did I just ask?").text.startswith("I have no earlier"),
        "recall with no history should say so")

    # The terminal must judge evidence against the resolved question: the
    # Colosseum has no completion year in the Colosseum sentence set that
    # matches, but a bare "It was completed in 1889." names no entity and
    # must not be offered as the Colosseum's answer.
    with tempfile.TemporaryDirectory(prefix="crms-topic-followup-") as folder:
        root = Path(folder)
        CRMSKnowledgeBase().save(root / "knowledge.json")
        shared = CRMSResearchIndex()
        shared.add_document(
            "cities", "cities.txt",
            "The Colosseum is an amphitheatre in Rome.\n\n"
            "The Eiffel Tower is located in Paris. It was completed in 1889.")
        shared.save(root / "index.json")
        project = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [sys.executable, str(project / "crms_chat.py"),
             "--knowledge", str(root / "knowledge.json"),
             "--index", str(root / "index.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json"),
             "--rule-session", str(root / "session.json")],
            input="Where is the Colosseum?\nwhen was it completed?\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=120)
        require(process.returncode == 0, process.stderr)
        require("It was completed in 1889" not in process.stdout.split(
            "when was it completed?")[-1],
            "a pronoun-led sentence about another entity answered the "
            f"Colosseum follow-up:\n{process.stdout}")
    print("source topic follow-ups ok")


if __name__ == "__main__":
    main()
