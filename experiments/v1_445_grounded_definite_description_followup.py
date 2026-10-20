"""Resolve a source description only when its local type link is explicit."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


POSITIVE = (
    "Python is a programming language. It was created by Guido van Rossum. "
    "The language was first released in 1991.")
AMBIGUOUS = (
    "Python is a programming language. Java is another programming language. "
    "The language was first released in 1991.")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_index(folder: Path, text: str) -> CRMSResearchIndex:
    folder.mkdir(parents=True)
    source = folder / "language_history.txt"
    source.write_text(text, encoding="utf-8")
    index = CRMSResearchIndex()
    index.add_directory(folder)
    return index


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-definite-description-") as tmp:
        root = Path(tmp)
        positive = make_index(root / "positive", POSITIVE)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        initial = respond(dialogue, "What type of language is Python?",
                          research_index=positive)
        require(initial.status in {"sources_found", "needs_review"}
                and "programming language" in initial.text.casefold(),
                f"explicit type statement was not surfaced: {initial!r}")

        followup = respond(
            dialogue, "Tell me when it was first released",
            research_index=positive)
        require(followup.status in {"sources_found", "needs_review"}
                and "1991" in followup.text
                and followup.resolved_question
                    == "When was Python first released?"
                and followup.question == "Tell me when it was first released",
                f"grounded descriptive follow-up did not resolve: {followup!r}")
        source_item = next((item for item in
                            (followup.research.source_sentences or [])
                            if "1991" in item["text"]), None)
        require(source_item is not None
                and positive.resolve_citation(source_item["citation"])
                    == source_item["text"]
                and "Python is a programming language." in source_item["text"]
                and "1991" in source_item["text"],
                "answer did not cite the exact date and its local entity link")

        ambiguous = make_index(root / "ambiguous", AMBIGUOUS)
        refused = respond(CRMSDialogue(CRMSKnowledgeBase()),
                          "When was Python first released?",
                          research_index=ambiguous)
        require("1991" not in refused.text,
                f"a later Java description was attributed to Python: {refused!r}")

    print("explicit local type link resolves a definite-description follow-up: PASS")
    print("nearer competing entity blocks cross-topic attribution: PASS")
    print("answer retains exact citation and original user wording: PASS")


if __name__ == "__main__":
    main()
