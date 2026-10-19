"""Reject source-only answers whose visible evidence names another entity.

Run with ``python3 experiments/v1_425_named_entity_evidence_guard.py``.
"""
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
    with tempfile.TemporaryDirectory(prefix="crms-entity-evidence-") as folder:
        source = Path(folder) / "facts.txt"
        source.write_text(
            "Marie Curie won two Nobel Prizes. Albert Einstein won the Nobel "
            "Prize in Physics in 1921.\n\n"
            "The Eiffel Tower is a landmark in Paris. It was completed in 1889.\n\n"
            "The Colosseum is an amphitheatre in Rome. It was completed in "
            "80 CE. Rome is the capital of Italy.\n",
            encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)

        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        curie = respond(dialogue,
                        "How many Nobel Prizes did Marie Curie win?",
                        research_index=index)
        require(curie.status == "sources_found"
                and "Marie Curie" in curie.text,
                f"retrieval did not select Curie's own source sentence: {curie!r}")
        require("Albert Einstein" not in curie.text,
                "unrelated evidence should not be presented as the answer")
        rejected = dialogue._reject_unanchored_source_answer(
            "How many Nobel Prizes did Marie Curie win?",
            "How many Nobel Prizes did Marie Curie win?",
            "Source text: Albert Einstein won the Nobel Prize in Physics in 1921.")
        require(rejected is not None and rejected.status == "unknown"
                and "Albert Einstein" not in rejected.text,
                "guard must refuse a wrong-entity Nobel quotation")

        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        tower = respond(dialogue, "When was the Eiffel Tower completed?",
                        research_index=index)
        require(tower.status == "sources_found" and "1889" in tower.text,
                f"named matching evidence regressed: {tower!r}")
        italy = respond(dialogue, "And Italy?", research_index=index)
        require(italy.status == "unknown" and "80 CE" not in italy.text,
                f"orphan Colosseum date was attributed to Italy: {italy!r}")
        why = respond(dialogue, "why?", research_index=index)
        require(why.status == "unknown"
                and "no previous grounded answer" in why.text.casefold(),
                f"rejected source turn left a stale explanation target: {why!r}")

        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        respond(dialogue, "When was the Eiffel Tower completed?",
                research_index=index)
        colosseum = respond(dialogue, "And the Colosseum?",
                            research_index=index)
        require(colosseum.status == "sources_found"
                and "80 CE" in colosseum.text
                and "Colosseum" in colosseum.text,
                f"valid named topic switch regressed: {colosseum!r}")

    print("named-entity retrieval selects Curie's own source sentence")
    print("named matching evidence remains answerable")
    print("elliptical entity mismatch cannot borrow another entity's sentence")
    print("rejected source answer clears the previous explanation target")
    print("valid named topic switch remains answerable")


if __name__ == "__main__":
    main()
