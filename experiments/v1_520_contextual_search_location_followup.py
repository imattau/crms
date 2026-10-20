"""Keep source-only search context when a user changes the requested locality."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "experiments" / "reports" / "v1_520_contextual_search_location_followup.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_index() -> CRMSResearchIndex:
    index = CRMSResearchIndex()
    for document_id, title, sentence in (
        ("sf-chinese", "Golden Dragon",
         "Golden Dragon is a Chinese restaurant in San Francisco, California."),
        ("oakland-chinese", "Harbor Noodle",
         "Harbor Noodle is a Chinese restaurant in Oakland, California."),
        ("sf-italian", "Little Napoli",
         "Little Napoli is an Italian restaurant in San Francisco, California."),
    ):
        index.add_document(document_id, title, sentence,
                           f"{document_id}.txt")
    return index


def main() -> None:
    index = build_index()
    dialogue = CRMSDialogue(CRMSKnowledgeBase())
    first = respond(
        dialogue,
        "Can you find a Chinese restaurant in San Francisco, California?",
        research_index=index)
    require(first.status == "sources_found"
            and "Golden Dragon" in first.text
            and "Harbor Noodle" not in first.text,
            f"initial search did not show only its matching source: {first.text!r}")

    with tempfile.TemporaryDirectory(prefix="crms-v1-520-state-") as folder:
        state_path = Path(folder) / "dialogue.json"
        dialogue.save(str(state_path))
        dialogue = CRMSDialogue.load(
            dialogue.knowledge, str(state_path), research_index=index)
    require(dialogue.last_intent_hypothesis is not None
            and dialogue.last_intent_hypothesis.matched_frame
                == "explicit-search-request"
            and [item["title"] for item in dialogue.presented_sources]
                == ["Golden Dragon"],
            "visible search intent/source context did not survive reload")

    followup = respond(dialogue, "What about Oakland?",
                       research_index=index)
    require(followup.status == "sources_found"
            and "Continuing your search" in followup.text
            and "chinese restaurant in oakland" in followup.text.casefold()
            and "Harbor Noodle is a Chinese restaurant in Oakland" in followup.text
            and "Golden Dragon" not in followup.text
            and "Little Napoli" not in followup.text,
            f"locality follow-up did not retain the task and change its locality: "
            f"{followup.text!r}")
    require(dialogue.last_intent_hypothesis is not None
            and dialogue.last_intent_hypothesis.matched_frame
                == "explicit-search-request"
            and dialogue.active_task_intent == "seek-information"
            and [item["title"] for item in dialogue.presented_sources]
                == ["Harbor Noodle"],
            "the contextual search intent or visible source state was not updated")

    explanation = respond(dialogue, "why?", research_index=index)
    require("Harbor Noodle" in explanation.text
            and "Golden Dragon" not in explanation.text
            and "not verified recommendations" in explanation.text,
            f"why? did not explain the latest source-only result: {explanation.text!r}")
    require(not dialogue.knowledge.facts(),
            "source-only search or follow-up was stored as an accepted fact")

    no_match_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    respond(no_match_dialogue,
            "Can you find a Chinese restaurant in San Francisco, California?",
            research_index=index)
    ambiguous = respond(no_match_dialogue, "What about French?",
                         research_index=index)
    require(ambiguous.status == "help"
            and "can't tell whether that changes the location" in
                ambiguous.text.casefold()
            and [item["title"] for item in no_match_dialogue.presented_sources]
                == ["Golden Dragon"],
            f"an untyped cuisine/location term was guessed or cleared context: "
            f"{ambiguous.text!r}")
    ambiguous_why = respond(no_match_dialogue, "why?", research_index=index)
    require("Golden Dragon" in ambiguous_why.text
            and "not verified recommendations" in ambiguous_why.text,
            f"why? after the clarification did not stay on visible evidence: "
            f"{ambiguous_why.text!r}")

    no_match = respond(no_match_dialogue, "What about in Miami?",
                       research_index=index)
    require(no_match.status == "unknown"
            and "couldn't find a source excerpt" in no_match.text.casefold()
            and "Golden Dragon" not in no_match.text
            and not no_match_dialogue.presented_sources,
            f"unmatched locality retained or displayed stale search results: "
            f"{no_match.text!r}")
    no_match_why = respond(no_match_dialogue, "why?", research_index=index)
    require("Golden Dragon" not in no_match_why.text
            and "no previous grounded answer" in no_match_why.text.casefold(),
            f"why? after a search miss reused the old result: {no_match_why.text!r}")
    stale_selection = respond(no_match_dialogue, "What about the first one?",
                               research_index=index)
    require(stale_selection.status == "clarify"
            and "don't have a numbered source list open" in stale_selection.text,
            f"a source from before the miss remained selectable: {stale_selection.text!r}")

    report = {
        "experiment": "v1_520_contextual_search_location_followup",
        "label_provenance": "Codex-authored development controls",
        "independent_validation": False,
        "result": "11/11 contextual search and stale-context assertions passed",
        "cases": [
            {"case": "retain cuisine and replace locality",
             "turns": [first.text, followup.text],
             "dialogue_state_reloaded_before_followup": True,
             "visible_after_followup": ["Harbor Noodle"],
             "accepted_fact_count": len(dialogue.knowledge.facts())},
            {"case": "why is anchored to latest search result",
             "response": explanation.text},
            {"case": "miss clears old displayed results",
             "response": no_match.text,
             "remaining_visible_sources": len(no_match_dialogue.presented_sources)},
            {"case": "untyped term asks for disambiguation",
             "response": ambiguous.text,
             "visible_source_preserved": True},
            {"case": "why after disambiguation stays with visible evidence",
             "response": ambiguous_why.text},
            {"case": "why after miss does not replay stale answer",
             "response": no_match_why.text},
            {"case": "stale ordinal selection is refused",
             "response": stale_selection.text},
        ],
        "limitations": [
            "One synthetic restaurant corpus; only a short locality substitution after a direct search is covered.",
            "The user utterance is transformed into a bounded search query; general entity, cuisine, time, and preference updates are not implemented by this experiment.",
            "Labels and expected outcomes are Codex-authored, not independent dialogue-transfer evidence.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("PASS: a locality follow-up retains the prior cuisine constraint")
    print("PASS: the new source list replaces the previous visible result")
    print("PASS: why? explains the latest search only")
    print("PASS: a search miss clears stale results and prevents stale why?/selection")
    print("PASS: search context survives save/reload before the follow-up")
    print("PASS: unknown cuisine/location terms prompt clarification")
    print("PASS: all 11 contextual search and stale-context assertions")
    print("LIMIT: narrow, Codex-authored dialogue controls")
    print(f"REPORT: {REPORT}")


if __name__ == "__main__":
    main()
