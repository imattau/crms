"""Route an explicit topic switch and its following question safely."""

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
        "The Eiffel Tower was completed in 1889.\n\n"
        "The Sydney Opera House opened in 1973. "
        "Jorn Utzon designed the Sydney Opera House."
    )
    with tempfile.TemporaryDirectory(prefix="crms-topic-clause-") as folder:
        Path(folder, "places.txt").write_text(corpus, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        old_topic = respond(
            dialogue, "When was the Eiffel Tower completed?",
            research_index=index)
        switched = respond(
            dialogue,
            "Switch to the Sydney Opera House. Who designed it?",
            research_index=index)
        followup = respond(dialogue, "When did it open?",
                           research_index=index)

        require(old_topic.status == "sources_found"
                and "1889" in old_topic.text,
                f"initial topic was not established: {old_topic!r}")
        require(switched.resolved_question == "Who designed Sydney Opera House?"
                and switched.status in {"sources_found", "needs_review"}
                and "Jorn Utzon designed the Sydney Opera House" in switched.text
                and "1889" not in switched.text,
                f"topic directive did not route its question through sources: {switched!r}")
        require(followup.resolved_question
                    == "When did Sydney Opera House open?"
                and "1973" in followup.text
                and "1889" not in followup.text,
                f"topic directive did not update follow-up context: {followup!r}")

        unsupported = CRMSDialogue(CRMSKnowledgeBase())
        respond(unsupported, "When was the Eiffel Tower completed?",
                research_index=index)
        no_source = respond(
            unsupported, "Switch to Atlantis. Who designed it?",
            research_index=index)
        require(no_source.resolved_question == "Who designed Atlantis?"
                and "1889" not in no_source.text
                and no_source.status not in {"answered", "sources_found"},
                f"unsupported topic borrowed old evidence: {no_source!r}")

    print("explicit topic clause routes its question through source retrieval: PASS")
    print("follow-up uses the newly named topic without cross-topic leakage: PASS")
    print("unknown topic remains context only and receives no invented evidence: PASS")


if __name__ == "__main__":
    main()
