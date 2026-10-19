"""Persist a source-backed topic only while its citation remains valid."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-persisted-topic-") as folder:
        root = Path(folder)
        source_text = (
            "The Eiffel Tower is located in Paris, while the Colosseum is "
            "an amphitheatre in Rome. The Colosseum was completed in 80 CE. "
            "The Eiffel Tower was completed in 1889.")
        index = CRMSResearchIndex()
        index.add_document("cities", "cities.txt", source_text)
        state_path = root / "dialogue.json"
        knowledge = CRMSKnowledgeBase()

        dialogue = CRMSDialogue(knowledge)
        first = dialogue.turn("Where is the Colosseum?", research_index=index)
        require(first.status == "sources_found" and
                dialogue.topic_entity == "Colosseum",
                f"setup failed to establish Colosseum as topic: {first!r}")
        require(any(item["entity"] == "Eiffel Tower"
                    for item in dialogue.source_mentions),
                "setup did not create a competing entity referent")
        dialogue.save(str(state_path))
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        require(payload["format_version"] == 21
                and payload["topic_reference"]["entity"] == "Colosseum",
                f"topic was not saved as a cited reference: {payload!r}")

        restored = CRMSDialogue.load(
            knowledge, str(state_path), research_index=index)
        require(restored.topic_entity == "Colosseum",
                "valid cited topic was not restored")
        question, clarification = restored._resolve_pronoun(
            "When was it completed?")
        require(question == "When was Colosseum completed?"
                and clarification is None,
                f"restored topic did not anchor the follow-up: {question!r}, "
                f"{clarification!r}")

        empty_index = CRMSResearchIndex()
        stale = CRMSDialogue.load(
            knowledge, str(state_path), research_index=empty_index)
        require(stale.topic_entity is None and not stale.source_mentions,
                "topic survived after its source citation became unavailable")
        unresolved, request = stale._resolve_pronoun(
            "When was it completed?")
        require(unresolved is None and request is not None,
                "stale source context was used to resolve a pronoun")

    print("cited source topic survives save/load and anchors follow-up: PASS")
    print("unresolvable source citation clears topic context: PASS")


if __name__ == "__main__":
    main()
