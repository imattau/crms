"""Answer compound WH questions from separate, separately cited sentences."""
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
    with tempfile.TemporaryDirectory(prefix="crms-compound-evidence-") as folder:
        root = Path(folder)
        (root / "travel.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        switched = respond(dialogue, "Where is the Colosseum?",
                           research_index=index)
        require(switched.status == "sources_found" and "Rome" in switched.text,
                f"failed to establish the prior topic: {switched!r}")

        compound = respond(
            dialogue,
            "Who designed the Eiffel Tower and when was it completed?",
            research_index=index)
        require(compound.status == "sources_found"
                and "Gustave Eiffel" in compound.text
                and "1889" in compound.text
                and "80 CE" not in compound.text
                and len(compound.research.source_sentences) == 2,
                f"compound answer omitted a part or leaked the old topic: "
                f"{compound!r}")
        cited_texts = {item["text"] for item in compound.research.source_sentences}
        require(any("designed and built by Gustave Eiffel" in text
                    for text in cited_texts)
                and any("completed in 1889" in text for text in cited_texts),
                f"separate requested parts did not retain distinct evidence: "
                f"{cited_texts}")
        for item in compound.research.source_sentences:
            require(index.resolve_citation(item["citation"]) == item["text"],
                    f"compound answer citation did not resolve exactly: {item!r}")

        explanation = respond(dialogue, "Why?", research_index=index)
        require("designed and built by Gustave Eiffel" in explanation.text
                and "completed in 1889" in explanation.text
                and all(item["citation"] in explanation.text
                        for item in compound.research.source_sentences),
                f"why? did not show both validated source spans: {explanation!r}")

        followup = respond(dialogue, "How tall is it?", research_index=index)
        require(followup.status == "sources_found"
                and "330 metres" in followup.text
                and "80 CE" not in followup.text,
                f"compound answer failed to preserve its named topic: {followup!r}")

        partial_dialogue = CRMSDialogue(CRMSKnowledgeBase())
        partial = respond(
            partial_dialogue,
            "Who designed the Eiffel Tower and when did it open?",
            research_index=index)
        require(partial.status == "unknown"
                and "only partial evidence" in partial.text.casefold()
                and "Gustave Eiffel" in partial.text
                and "1889" not in partial.text
                and "can't answer every part" in partial.text,
                f"missing compound clause was presented as answered: {partial!r}")
        partial_why = respond(partial_dialogue, "Why?", research_index=index)
        require(partial_why.status == "unknown"
                and "designed and built by Gustave Eiffel" in partial_why.text
                and "No source evidence was found for: when did it open"
                    in partial_why.text
                and "1889" not in partial_why.text,
                f"explanation hid which compound clause lacked support: "
                f"{partial_why!r}")
        partial_followup = respond(
            partial_dialogue, "How tall is it?", research_index=index)
        require(partial_followup.status == "sources_found"
                and "330 metres" in partial_followup.text,
                f"visible partial evidence did not retain the grounded topic: "
                f"{partial_followup!r}")

        ambiguous = respond(
            CRMSDialogue(CRMSKnowledgeBase()),
            "When was the Eiffel Tower completed and how tall is it compared "
            "with the Colosseum?", research_index=index)
        require(ambiguous.status == "unknown"
                and "multiple possible entities" in ambiguous.text
                and "1889" not in ambiguous.text
                and "50,000" not in ambiguous.text,
                f"compound splitting bypassed whole-utterance ambiguity: "
                f"{ambiguous!r}")

    print("separate compound clauses return separately cited source evidence: PASS")
    print("why? revalidates and explains both source spans: PASS")
    print("source-only topic supports a later follow-up: PASS")
    print("missing clause produces an explicit partial-evidence abstention: PASS")
    print("partial explanation identifies missing clause and preserves visible topic: PASS")
    print("whole-question entity ambiguity prevents unsafe clause splitting: PASS")


if __name__ == "__main__":
    main()
