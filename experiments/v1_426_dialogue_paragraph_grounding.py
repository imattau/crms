"""A source-only follow-up may use a local paragraph antecedent, never a remote one."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    corpus = (
        "The Eiffel Tower is a landmark in Paris. "
        "It was completed in 1889 and stands 330 metres tall. "
        "The tower was designed and built by Gustave Eiffel.\n\n"
        "The Colosseum is an amphitheatre in Rome. "
        "It was completed in 80 CE and could hold 50,000 spectators. "
        "Rome is the capital of Italy."
    )
    with tempfile.TemporaryDirectory(prefix="crms-dialogue-paragraph-") as folder:
        source = Path(folder) / "travel.txt"
        source.write_text(corpus, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        first = respond(dialogue, "When was the Eiffel Tower completed?",
                        research_index=index)
        switch = respond(dialogue, "And the Colosseum?", research_index=index)
        require(first.status == "sources_found" and
                switch.resolved_question == "When was the Colosseum completed?",
                f"source-only entity switch failed: {first!r}; {switch!r}")

        followup = respond(dialogue, "How many people could it hold?",
                           research_index=index)
        require(followup.status == "sources_found"
                and "80 CE" in followup.text
                and "1889" not in followup.text,
                f"same-paragraph antecedent did not stay on topic: {followup!r}")
        answer_sentence = followup.research.source_sentences[0]
        require("The Colosseum" in answer_sentence["text"]
                and "50,000 spectators" in answer_sentence["text"]
                and index.resolve_citation(answer_sentence["citation"])
                == answer_sentence["text"],
                "accepted pronoun evidence lacks its exact cited local antecedent")

        explanation = respond(dialogue, "Why?", research_index=index)
        require("50,000 spectators" in explanation.text
                and "1889" not in explanation.text,
                f"why? explained an older topic instead of the latest one: {explanation!r}")

        state = Path(folder) / "dialogue.json"
        dialogue.save(str(state))
        restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state),
                                     research_index=index)
        restored_followup = respond(
            restored, "How many people could it hold?", research_index=index)
        require("Colosseum" in restored_followup.resolved_question
                and "50,000 spectators" in restored_followup.text,
                f"paragraph anchor did not survive dialogue reload: {restored_followup!r}")

        mismatched_switch = respond(dialogue, "And Italy?", research_index=index)
        require(mismatched_switch.status != "answered"
                and "quoted sentence I found does not name Italy"
                    in mismatched_switch.text
                and "50,000 spectators" not in mismatched_switch.text,
                f"an incompatible entity switch reused the prior answer: {mismatched_switch!r}")

        height_dialogue = CRMSDialogue(CRMSKnowledgeBase())
        respond(height_dialogue, "Where is the Eiffel Tower?",
                research_index=index)
        height = respond(height_dialogue, "How tall is it?",
                         research_index=index)
        require("330 metres" in height.text
                and "designed and built" not in height.text,
                f"measurement request selected a neighboring sentence: {height!r}")

        recall_dialogue = CRMSDialogue(CRMSKnowledgeBase())
        previous = respond(recall_dialogue, "What is Atlantis known for?",
                           research_index=index)
        recalled = respond(recall_dialogue, "What did I just ask?",
                           research_index=index)
        require("What is Atlantis known for?" in recalled.text,
                f"conversation history lost the last failed question: {previous!r}; "
                f"{recalled!r}")
        ordinal = respond(recall_dialogue, "The first one",
                          research_index=index)
        require(ordinal.status == "clarify"
                and "numbered source list" in ordinal.text,
                f"ordinal without an open source list did not clarify: {ordinal!r}")

    print("source-only topic switch and local paragraph grounding: PASS")
    print("remote-paragraph answer leakage: REJECTED")
    print("latest-answer explanation and save/reload follow-up: PASS")


if __name__ == "__main__":
    main()
