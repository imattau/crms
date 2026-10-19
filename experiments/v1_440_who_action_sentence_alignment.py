"""Named-entity action questions select the relation-bearing sentence only."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def answer_for(text: str, question: str):
    folder = tempfile.TemporaryDirectory(prefix="crms-who-action-")
    source = Path(folder.name) / "facts.txt"
    source.write_text(text, encoding="utf-8")
    index = CRMSResearchIndex()
    index.add_directory(folder.name)
    result = respond(CRMSDialogue(CRMSKnowledgeBase()), question,
                     research_index=index)
    return folder, index, result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    question = "Who designed the Sydney Opera House?"
    folder, index, result = answer_for(
        "The Eiffel Tower was completed in 1889.\n\n"
        "The Sydney Opera House opened in 1973. Jorn Utzon designed it.\n",
        question)
    try:
        require(result.status == "sources_found" and result.research is not None,
                f"answer-bearing action sentence was not found: {result!r}")
        sentences = result.research.source_sentences
        require(sentences and "Jorn Utzon designed it." in sentences[0]["text"],
                f"the designer sentence did not win selection: {sentences!r}")
        require("The Sydney Opera House opened in 1973." in sentences[0]["text"],
                "object-pronoun answer lacks its local entity antecedent")
        require(index.resolve_citation(sentences[0]["citation"])
                == sentences[0]["text"],
                "combined answer evidence does not resolve to its citation")
        require("1889" not in result.text and "1973" in result.text,
                "answer should cite its local antecedent, not a remote paragraph")
    finally:
        folder.cleanup()

    folder, _index, result = answer_for(
        "Jorn Utzon designed the Sydney Opera House.\n", question)
    try:
        require(result.status in {"sources_found", "needs_review"}
                and "Jorn Utzon designed the Sydney Opera House." in result.text,
                f"direct entity-bearing relation regressed: {result!r}")
    finally:
        folder.cleanup()

    folder, _index, result = answer_for(
        "The Sydney Opera House opened in 1973.\n", question)
    try:
        require(result.status == "unknown" and result.research is not None
                and not result.research.source_sentences,
                f"entity-only sentence was presented as an action answer: {result!r}")
    finally:
        folder.cleanup()

    folder, _index, result = answer_for(
        "The Sydney Opera House opened in 1973.\n\n"
        "Jorn Utzon designed it.\n", question)
    try:
        require(result.status == "unknown" and result.research is not None
                and not result.research.source_sentences,
                f"pronoun answer borrowed an antecedent across paragraphs: {result!r}")
    finally:
        folder.cleanup()

    folder, _index, result = answer_for(
        "The Sydney Opera House opened in 1973. The Colosseum is in Rome. "
        "Jorn Utzon designed it.\n", question)
    try:
        require(result.status == "unknown" and result.research is not None
                and not result.research.source_sentences,
                f"pronoun answer borrowed the wrong local entity: {result!r}")
    finally:
        folder.cleanup()

    folder, _index, result = answer_for(
        "The tower was designed and built by Gustave Eiffel.\n",
        "Who built the tower?")
    try:
        require(result.status == "sources_found"
                and "Gustave Eiffel" in result.text,
                f"direct compound relation wording regressed: {result!r}")
    finally:
        folder.cleanup()

    print("named action selects the answer-bearing object-pronoun sentence: PASS")
    print("direct entity-bearing action and compound predicate: PASS")
    print("entity-only, cross-paragraph, and wrong-antecedent negatives: PASS")


if __name__ == "__main__":
    main()
