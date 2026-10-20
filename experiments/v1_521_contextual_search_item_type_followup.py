"""Recognize source-grounded item-type changes after a direct search."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_521_contextual_search_item_type_followup.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def setup() -> tuple[CRMSResearchIndex, CRMSDialogue]:
    index = CRMSResearchIndex()
    for document_id, title, sentence in (
        ("sf-chinese", "Golden Dragon",
         "Golden Dragon is a Chinese restaurant in San Francisco, California."),
        ("oakland-chinese", "Harbor Noodle",
         "Harbor Noodle is a Chinese restaurant in Oakland, California."),
        ("sf-italian", "Little Napoli",
         "Little Napoli is an Italian restaurant in San Francisco, California."),
        ("italy-chinese", "Roma Table",
         "Roma Table is a Chinese restaurant in Rome, Italy."),
    ):
        index.add_document(document_id, title, sentence,
                           f"{document_id}.txt")
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    initial = respond(
        dialogue,
        "Can you find a Chinese restaurant in San Francisco, California?",
        research_index=index)
    require(initial.status == "sources_found"
            and "Golden Dragon" in initial.text
            and "Harbor Noodle" not in initial.text
            and "Little Napoli" not in initial.text,
            f"initial search did not establish a single matching result: {initial.text!r}")
    return index, dialogue


def check_item_type_followup(phrase: str, label: str) -> dict[str, object]:
    index, dialogue = setup()
    result = respond(dialogue, phrase, research_index=index)
    expected = "Little Napoli is an Italian restaurant in San Francisco, California."
    require(result.status == "sources_found"
            and "an Italian restaurant in San Francisco, California" in result.text
            and expected in result.text
            and "Golden Dragon" not in result.text
            and "Harbor Noodle" not in result.text
            and "not verified recommendations" in result.text.casefold(),
            f"{label} did not replace cuisine and preserve locality: {result.text!r}")
    require(dialogue.last_intent_hypothesis is not None
            and dialogue.last_intent_hypothesis.matched_frame
                == "explicit-search-request"
            and [item["title"] for item in dialogue.presented_sources]
                == ["Little Napoli"],
            f"{label} did not replace the displayed source context")
    require(not dialogue.knowledge.facts(),
            f"{label} stored quoted source text as an accepted fact")
    why = respond(dialogue, "why?", research_index=index)
    require("Little Napoli" in why.text and "Golden Dragon" not in why.text,
            f"why? after {label} did not explain the latest result: {why.text!r}")
    return {"phrase": phrase,
            "result": result.text,
            "why": why.text,
            "accepted_fact_count": len(dialogue.knowledge.facts())}


def main() -> None:
    item_type_cases = [
        check_item_type_followup("What about Italian?", "bare cuisine follow-up"),
        check_item_type_followup("And the Italian one?", "elliptical item follow-up"),
    ]

    index, dialogue = setup()
    location = respond(dialogue, "And Italy?", research_index=index)
    require(location.status == "sources_found"
            and "Chinese restaurant in Italy" in location.text
            and "Roma Table is a Chinese restaurant in Rome, Italy." in location.text
            and "Golden Dragon" not in location.text
            and "Little Napoli" not in location.text,
            f"a place-name follow-up was mistaken for a cuisine change: {location.text!r}")

    report = {
        "experiment": "v1_521_contextual_search_item_type_followup",
        "label_provenance": "Codex-authored development controls",
        "independent_validation": False,
        "result": "12/12 source-grounded item-type and locality assertions passed",
        "item_type_cases": item_type_cases,
        "location_case": {"phrase": "And Italy?", "result": location.text},
        "limitations": [
            "One synthetic restaurant index; source grammar is used to distinguish a type modifier from a location.",
            "Only one-word item modifiers before restaurant/place/option are supported; arbitrary preferences and multi-slot changes remain open.",
            "Labels and expected outputs are Codex-authored; this is not independent dialogue-transfer evidence.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("PASS: ‘What about Italian?’ changes cuisine and keeps San Francisco")
    print("PASS: ‘And the Italian one?’ reaches the same source-grounded route")
    print("PASS: ‘And Italy?’ changes locality and keeps Chinese restaurant")
    print("PASS: why? remains anchored to the newest result")
    print("LIMIT: narrow, source-pattern and corpus-bound controls")
    print(f"REPORT: {REPORT}")


if __name__ == "__main__":
    main()
