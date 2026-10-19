"""Named topic context must recover and rank its answer-bearing pronoun sentence."""
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-pronoun-sentence-") as folder:
        source = Path(folder) / "travel.txt"
        source.write_text(
            "The Eiffel Tower is a landmark in Paris. It was completed in 1889.\n\n"
            "The Colosseum is an amphitheatre in Rome. It was completed in 80 CE.\n\n"
            "It was completed in 1889.\n",
            encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        first = respond(dialogue, "When was the Eiffel Tower completed?",
                        research_index=index)
        require(first.status == "sources_found" and first.research is not None,
                f"Eiffel Tower query did not use source evidence: {first!r}")
        first_sentence = (first.research.source_sentences or [{}])[0].get("text")
        require(first_sentence == (
                    "The Eiffel Tower is a landmark in Paris. "
                    "It was completed in 1889."),
                f"Eiffel Tower answer and antecedent context were not selected: "
                f"{first_sentence!r}")

        switched = respond(dialogue, "And the Colosseum?", research_index=index)
        require(switched.resolved_question == "When was the Colosseum completed?",
                f"named topic switch failed: {switched!r}")
        follow_up = respond(dialogue, "When was it completed?",
                            research_index=index)
        require(follow_up.status == "sources_found" and follow_up.research is not None,
                f"Colosseum follow-up did not use source evidence: {follow_up!r}")
        sentence = (follow_up.research.source_sentences or [{}])[0].get("text")
        require(sentence == (
                    "The Colosseum is an amphitheatre in Rome. "
                    "It was completed in 80 CE."),
                f"answer-bearing pronoun sentence and context were not selected: "
                f"{sentence!r}")
        require("1889" not in follow_up.text and "80 CE" in follow_up.text,
                f"follow-up cited the wrong topic or omitted its answer: {follow_up.text!r}")
        require(follow_up.status != "answered",
                "quoted source evidence was incorrectly promoted to an accepted fact")
        require("1889" not in follow_up.text,
                "an orphan pronoun sentence from another paragraph was attributed")

        explanation = respond(dialogue, "why?", research_index=index)
        require(explanation.status == "sources_found"
                and "80 CE" in explanation.text
                and "1889" not in explanation.text,
                f"why? did not explain the latest topic-specific evidence: {explanation.text!r}")

    print("pronoun-led sentence recovers its same-paragraph entity anchor: PASS")
    print("question-type and predicate ranking select the answer-bearing date: PASS")
    print("named topic switch and why? preserve the current cited evidence: PASS")
    print("quoted source text remains distinct from accepted facts: PASS")


if __name__ == "__main__":
    main()
