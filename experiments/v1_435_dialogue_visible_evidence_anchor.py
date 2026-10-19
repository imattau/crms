"""Only displayed citations may anchor a source-only answer to an entity."""

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


def run_case(corpus: str, followups: tuple[str, ...]) -> list:
    with tempfile.TemporaryDirectory(prefix="crms-visible-anchor-") as folder:
        Path(folder, "travel.txt").write_text(corpus, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        turns = [respond(dialogue, "When was the Eiffel Tower completed?",
                         research_index=index)]
        turns.extend(respond(dialogue, question, research_index=index)
                     for question in followups)
        return turns


def main() -> None:
    same_paragraph = (
        "The Eiffel Tower is in Paris. It was completed in 1889. "
        "The Colosseum is in Rome. It was completed in 80 CE.")
    turns = run_case(same_paragraph,
                     ("And the Colosseum?", "When was it completed?"))
    for number, turn in enumerate(turns[1:], 2):
        require("1889" not in turn.text,
                f"turn {number} attributed Eiffel evidence to the Colosseum: {turn!r}")
    require(turns[1].status != "sources_found",
            "an unseen Colosseum citation licensed the displayed Eiffel sentence")
    require(turns[2].status == "unknown",
            f"pronoun without a valid current topic did not abstain: {turns[2]!r}")

    separate_paragraphs = (
        "The Eiffel Tower is in Paris. It was completed in 1889.\n\n"
        "The Colosseum is in Rome. It was completed in 80 CE.")
    controls = run_case(separate_paragraphs, ("And the Colosseum?",))
    require("1889" not in controls[1].text,
            f"separate-paragraph topic switch leaked Eiffel evidence: {controls[1]!r}")

    print("unseen candidate citation cannot license displayed pronoun sentence: PASS")
    print("same-paragraph cross-topic follow-up abstains safely: PASS")
    print("separate-paragraph topic switch has no cross-topic leakage: PASS")


if __name__ == "__main__":
    main()
