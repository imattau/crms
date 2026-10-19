"""Keep a single follow-up pronoun anchored to the current dialogue topic."""

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
        "Alan Turing worked at Bletchley Park during the Second World War.\n\n"
        "The Sydney Opera House opened in 1973. "
        "Jorn Utzon designed it, and the building stands beside Sydney Harbour."
    )
    with tempfile.TemporaryDirectory(prefix="crms-topic-pronoun-") as folder:
        Path(folder, "places-and-people.txt").write_text(
            corpus, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        first = respond(dialogue, "When was the Eiffel Tower completed?",
                        research_index=index)
        switch = respond(dialogue, "What about Alan Turing?",
                         research_index=index)
        followup = respond(dialogue, "Where did he work?",
                            research_index=index)
        require(first.status == "sources_found"
                and "1889" in first.text,
                f"initial source-backed topic was not established: {first!r}")
        require(switch.status == "sources_found"
                and "Alan Turing" in switch.text,
                f"named person switch did not surface its source: {switch!r}")
        require(followup.status == "sources_found"
                and followup.resolved_question == "Where did Alan Turing work?"
                and "Bletchley Park" in followup.text
                and "1889" not in followup.text,
                f"single pronoun did not stay with the current person: {followup!r}")

        # The user may explicitly name a topic absent from the loaded corpus.
        # That name is dialogue state, not evidence: it may bind the next
        # pronoun, but it cannot make an unsupported answer appear.
        unsupported = CRMSDialogue(CRMSKnowledgeBase())
        respond(unsupported, "When was the Eiffel Tower completed?",
                research_index=index)
        named = respond(unsupported, "What about Ada Lovelace?",
                        research_index=index)
        no_evidence = respond(unsupported, "What did she write?",
                              research_index=index)
        require(no_evidence.resolved_question == "What did Ada Lovelace write?"
                and "1889" not in no_evidence.text
                and no_evidence.status not in {"answered", "sources_found"},
                f"a user-named topic created unsupported evidence: {no_evidence!r}")
        require(named.status not in {"answered", "sources_found"}
                or "Ada Lovelace" in named.text,
                f"an unrelated source was attributed to Ada Lovelace: {named!r}")

        # Check that an entity switch still steers a neutral pronoun to the
        # latest topic even when older entities have stronger stored matches.
        places = respond(dialogue, "What about the Sydney Opera House?",
                         research_index=index)
        open_followup = respond(dialogue, "When did it open?",
                                research_index=index)
        require(open_followup.resolved_question
                    == "When did Sydney Opera House open?"
                and "1973" in open_followup.text
                and "1889" not in open_followup.text,
                f"neutral pronoun reverted to an older topic: {open_followup!r}")

    print("single pronoun follows the explicitly current person topic: PASS")
    print("user-named topic resolves dialogue context without adding evidence: PASS")
    print("new topic survives older answerable entities without cross-topic leakage: PASS")


if __name__ == "__main__":
    main()
