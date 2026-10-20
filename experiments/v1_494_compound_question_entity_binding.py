"""Bind a compound question's pronoun to its unique local named entity."""
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
    with tempfile.TemporaryDirectory(prefix="crms-compound-question-") as folder:
        root = Path(folder)
        (root / "travel.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        # The current conversation topic is Colosseum, but the explicit entity
        # in this new compound request must locally anchor the later "it".
        colosseum = respond(dialogue, "Where is the Colosseum?",
                            research_index=index)
        compound = respond(
            dialogue,
            "When was the Eiffel Tower completed and how tall is it?",
            research_index=index)
        require(colosseum.status == "sources_found" and "Rome" in colosseum.text,
                f"expected source-only Colosseum topic first: {colosseum!r}")
        require(compound.status == "sources_found"
                and "Eiffel Tower" in compound.resolved_question
                and "1889" in compound.text and "330 metres" in compound.text
                and "80 CE" not in compound.text,
                f"local entity did not anchor both compound-question claims: "
                f"{compound!r}")
        cited = compound.research.source_sentences[0]
        require("1889" in cited["text"] and "330 metres" in cited["text"]
                and index.resolve_citation(cited["citation"]) == cited["text"],
                "compound answer did not cite the sentence stating both requested values")

        ambiguous = respond(
            CRMSDialogue(CRMSKnowledgeBase()),
            "When was the Eiffel Tower completed and how tall is it compared "
            "with the Colosseum?", research_index=index)
        require(ambiguous.status == "unknown"
                and "multiple possible entities" in ambiguous.text
                and "1889" not in ambiguous.text and "80 CE" not in ambiguous.text,
                f"multiple named entities did not trigger safe clarification: "
                f"{ambiguous!r}")

    print("compound-question pronoun uses its unique local named entity: PASS")
    print("explicit current-utterance topic overrides stale conversation topic: PASS")
    print("ambiguous multi-entity pronoun abstains; exact source citation retained: PASS")


if __name__ == "__main__":
    main()
