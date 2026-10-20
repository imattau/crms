"""Conversation-held-out probe for source-only topic and pronoun transfer.

All entities and source passages below are new fixtures authored for this
evaluation. The expected answers are Codex-labeled, so this is a frozen
regression/transfer probe, not an independent human benchmark.
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


CASES = (
    {
        "name": "single-paragraph adjacent referents",
        "text": (
            "The Harbor Archive is a maritime museum in Lydon. "
            "It opened in 1964. The Moss Theatre is a performing arts hall "
            "in Veyra. It opened in 1987."
        ),
        "first": "Harbor Archive",
        "first_date": "1964",
        "target": "Moss Theatre",
        "target_date": "1987",
    },
    {
        "name": "separate paragraphs with intervening third entity",
        "text": (
            "The Alder Observatory is perched above Norvale. It opened in 1932.\n\n"
            "The Juniper Baths are a public pool complex in Westmere. "
            "They opened in 1958.\n\n"
            "The Sable Gallery displays regional art in Ilyra. "
            "It opened in 1976."
        ),
        "first": "Alder Observatory",
        "first_date": "1932",
        "target": "Juniper Baths",
        "target_date": "1958",
        "pronoun_question": "When did they open?",
    },
    {
        "name": "line-wrapped source paragraph",
        "text": (
            "The Kestrel Station is a rail stop in Orin.\n"
            "It opened in 1949.\n"
            "The Willow Library is in the university quarter of Belden.\n"
            "It opened in 2003."
        ),
        "first": "Kestrel Station",
        "first_date": "1949",
        "target": "Willow Library",
        "target_date": "2003",
    },
    {
        "name": "reverse-order topic switch",
        "text": (
            "The Ember Pavilion is beside Lake Aven. It opened in 1998.\n\n"
            "The Quartz Hall is the civic auditorium of Merrow. "
            "It opened in 1911."
        ),
        "first": "Quartz Hall",
        "first_date": "1911",
        "target": "Ember Pavilion",
        "target_date": "1998",
    },
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_case(case: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory(prefix="crms-dialogue-transfer-") as folder:
        source = Path(folder) / "places.txt"
        source.write_text(case["text"], encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())

        initial = respond(
            dialogue, f"When did the {case['first']} open?",
            research_index=index)
        require(initial.status == "sources_found"
                and case["first_date"] in initial.text,
                f"{case['name']}: initial named answer failed: {initial!r}")

        switched = respond(
            dialogue, f"And the {case['target']}?", research_index=index)
        require(switched.resolved_question
                == f"When did the {case['target']} open?"
                and case["target_date"] in switched.text
                and case["first_date"] not in switched.text,
                f"{case['name']}: named topic switch misbound: {switched!r}")

        pronoun = respond(
            dialogue, case.get("pronoun_question", "When did it open?"),
            research_index=index)
        require(pronoun.status == "sources_found"
                and case["target_date"] in pronoun.text
                and case["first_date"] not in pronoun.text,
                f"{case['name']}: pronoun follow-up misbound: {pronoun!r}")
        cited = pronoun.research.source_sentences[0]
        require(case["target_date"] in cited["text"]
                and index.resolve_citation(cited["citation"]) == cited["text"],
                f"{case['name']}: answer citation does not support target date")

        explanation = respond(dialogue, "why?", research_index=index)
        require(case["target_date"] in explanation.text
                and case["first_date"] not in explanation.text,
                f"{case['name']}: why? drifted to an earlier topic: {explanation!r}")

        # A recoverable abstention should not discard a still-grounded topic.
        # The next pronoun must continue to refer to the named target, and
        # "why?" must explain that follow-up rather than the failed request.
        unsupported = respond(
            dialogue, "When did it close?", research_index=index)
        require(unsupported.status not in {"answered", "sources_found"}
                and case["target_date"] not in unsupported.text,
                f"{case['name']}: unsupported closing date was answered: "
                f"{unsupported!r}")
        after_abstention = respond(
            dialogue, case.get("pronoun_question", "When did it open?"),
            research_index=index)
        require(after_abstention.status == "sources_found"
                and case["target_date"] in after_abstention.text
                and case["first_date"] not in after_abstention.text,
                f"{case['name']}: recoverable abstention lost current topic: "
                f"{after_abstention!r}")
        after_abstention_why = respond(
            dialogue, "why?", research_index=index)
        require(case["target_date"] in after_abstention_why.text
                and case["first_date"] not in after_abstention_why.text,
                f"{case['name']}: why? explained the wrong turn after abstention: "
                f"{after_abstention_why!r}")

        state = Path(folder) / "dialogue.json"
        dialogue.save(str(state))
        restored = CRMSDialogue.load(CRMSKnowledgeBase(), str(state),
                                     research_index=index)
        after_reload = respond(
            restored, case.get("pronoun_question", "When did it open?"),
            research_index=index)
        require(case["target_date"] in after_reload.text
                and case["first_date"] not in after_reload.text,
                f"{case['name']}: topic grounding failed after reload: {after_reload!r}")
        unsupported = respond(
            restored, f"When did the {case['target']} close?",
            research_index=index)
        require(unsupported.status not in {"answered", "sources_found"}
                and case["target_date"] not in unsupported.text,
                f"{case['name']}: opening date answered a closing question: "
                f"{unsupported!r}")


def main() -> None:
    for case in CASES:
        run_case(case)
        print(f"{case['name']}: topic switch, pronoun, citation, interrupted "
              "follow-up, why?, reload: PASS")
    supported_steps = 8 * len(CASES)
    expected_abstentions = 2 * len(CASES)
    print(f"held-out-style authored fixtures: {len(CASES)}; target-evidence "
          f"steps: {supported_steps}/{supported_steps}; wrong answers: 0; "
          f"negative-control abstentions: {expected_abstentions}/"
          f"{expected_abstentions}; labeler: Codex")


if __name__ == "__main__":
    main()
