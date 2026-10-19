"""Only displayed citations may anchor a source-only answer to an entity."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase, ResearchResult
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
                     ("And the Colosseum?", "When was it completed?",
                      "And the Eiffel Tower?", "When was it completed?"))
    for number, turn in enumerate(turns[1:3], 2):
        require("80 CE" in turn.text and "1889" not in turn.text,
                f"turn {number} did not keep the nearest Colosseum antecedent: {turn!r}")
    for number, turn in enumerate(turns[3:], 4):
        require("1889" in turn.text and "80 CE" not in turn.text,
                f"turn {number} did not return to the Eiffel Tower evidence: {turn!r}")

    with tempfile.TemporaryDirectory(prefix="crms-visible-anchor-gate-") as folder:
        Path(folder, "travel.txt").write_text(same_paragraph, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        knowledge = CRMSKnowledgeBase()
        retrieved = knowledge.research("When was the Colosseum completed?", index)
        right = next((item for item in retrieved.source_sentences or []
                      if "80 CE" in item["text"]), None)
        wrong_result = knowledge.research(
            "When was the Eiffel Tower completed?", index)
        wrong = next((item for item in wrong_result.source_sentences or []
                      if "1889" in item["text"]), None)
        require(wrong is not None and right is not None,
                "fixture did not retrieve the wrong and correct citations")
        synthetic_candidates = ResearchResult(
            status="sources_found", source_sentences=[wrong, right])
        checked = CRMSDialogue(knowledge)._reject_unanchored_source_answer(
            "When was it completed?", "When was Colosseum completed?",
            "Source text: " + wrong["text"], synthetic_candidates, index)
        require(checked is not None and checked.status == "unknown",
                "an undisplayed correct citation licensed the visible wrong date")

    separate_paragraphs = (
        "The Eiffel Tower is in Paris. It was completed in 1889.\n\n"
        "The Colosseum is in Rome. It was completed in 80 CE.")
    controls = run_case(separate_paragraphs, ("And the Colosseum?",))
    require("80 CE" in controls[1].text and "1889" not in controls[1].text,
            f"separate-paragraph topic switch did not select Colosseum evidence: {controls[1]!r}")

    print("nearest explicit subject selects the correct same-paragraph date: PASS")
    print("undisplayed citation cannot license the visible wrong date: PASS")
    print("separate-paragraph topic switch selects the correct evidence: PASS")


if __name__ == "__main__":
    main()
