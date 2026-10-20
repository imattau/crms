"""A coordinated WH follow-up should keep the current grounded topic."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


CORPUS = (
    "The Eiffel Tower is a landmark in Paris. It was completed in 1889 and "
    "stands 330 metres tall. The tower was designed and built by Gustave Eiffel.\n\n"
    "The Colosseum is an amphitheatre in Rome. It was completed in 80 CE and "
    "could hold 50,000 spectators."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-coordinated-followup-") as folder:
        root = Path(folder)
        (root / "travel.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)

        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        first = respond(dialogue, "Where is the Eiffel Tower?",
                        research_index=index)
        completed = respond(dialogue, "and when was it completed?",
                            research_index=index)
        height = respond(dialogue, "and how tall is it?",
                         research_index=index)
        require(first.status == "sources_found"
                and "Paris" in first.text,
                f"expected the initial source-only topic answer: {first!r}")
        require(completed.status == "sources_found"
                and completed.resolved_question
                    .casefold() == "when was eiffel tower completed?"
                and completed.question == "and when was it completed?"
                and "1889" in completed.text
                and completed.research.source_sentences,
                f"coordinated date follow-up lost its topic or answer scope: "
                f"{completed!r}")
        require(height.status == "sources_found"
                and height.resolved_question.casefold()
                    == "how tall is eiffel tower?"
                and height.question == "and how tall is it?"
                and "330 metres" in height.text
                and height.research.source_sentences,
                f"second coordinated follow-up did not use current topic: "
                f"{height!r}")
        for turn, expected in ((completed, "1889"), (height, "330 metres")):
            sentence = turn.research.source_sentences[0]
            require(expected in sentence["text"]
                    and index.resolve_citation(sentence["citation"])
                    == sentence["text"],
                    f"follow-up evidence was not cited exactly: {turn!r}")

        # The conjunction is contextual. Without a current grounded topic, it
        # must not be stripped into an answerable-looking standalone query.
        unanchored = respond(CRMSDialogue(CRMSKnowledgeBase()),
                             "And when was it completed?",
                             research_index=index)
        require(unanchored.status == "unknown"
                and "name an entity" in unanchored.text.casefold()
                and "1889" not in unanchored.text,
                f"unanchored continuation guessed a referent: {unanchored!r}")

    print("source-only answer retains topic for natural 'and when/how' follow-ups: PASS")
    print("follow-up question scope and exact citations remain grounded: PASS")
    print("same wording without a grounded prior topic still abstains: PASS")


if __name__ == "__main__":
    main()
