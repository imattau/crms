"""An unsupported topic switch must not leave the prior answer explainable."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    # The initial answer is source-only, so it must not become an accepted
    # fact. The unsupported named switch must still replace the old QUD.
    index = CRMSResearchIndex()
    index.add_document(
        "travel", "travel.txt",
        "The Eiffel Tower is in Paris. It was completed in 1889.")
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    first = dialogue.turn("When was the Eiffel Tower completed?",
                          research_index=index)
    require(first.status == "sources_found" and "1889" in first.text,
            f"expected source-only Eiffel answer, got {first!r}")
    switched = dialogue.turn("And the Colosseum?", research_index=index)
    require(switched.status == "unknown"
            and "Colosseum" in switched.resolved_question,
            f"unsupported topic switch kept the wrong topic: {switched!r}")
    explanation = dialogue.turn("Why?", research_index=index)
    require(explanation.status == "unknown"
            and "no previous grounded answer" in explanation.text.casefold()
            and "1889" not in explanation.text,
            f"why? explained the stale Eiffel answer: {explanation!r}")

    # When the new topic is supported, both answer and explanation must stay
    # on that topic, despite the previous Eiffel completion sentence.
    paired = CRMSResearchIndex()
    paired.add_document(
        "travel", "travel.txt",
        "The Eiffel Tower is in Paris. It was completed in 1889.\n\n"
        "The Colosseum is in Rome. It was completed in 80 CE.")
    supported = CRMSDialogue(CRMSKnowledgeBase())
    supported.turn("When was the Eiffel Tower completed?",
                   research_index=paired)
    switched_supported = supported.turn(
        "And the Colosseum?", research_index=paired)
    require("Colosseum" in switched_supported.resolved_question
            and "80 CE" in switched_supported.text
            and "1889" not in switched_supported.text,
            f"supported switch returned evidence from the prior topic: "
            f"{switched_supported!r}")
    explanation_supported = supported.turn("Why?", research_index=paired)
    require("Colosseum" in explanation_supported.resolved_question
            and "80 CE" in explanation_supported.text
            and "1889" not in explanation_supported.text,
            f"why? did not explain the current topic: {explanation_supported!r}")

    print("unsupported topic switch clears stale explanation target: PASS")
    print("supported topic switch and why? stay on current entity: PASS")


if __name__ == "__main__":
    main()
