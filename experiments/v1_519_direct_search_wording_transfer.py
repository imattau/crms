"""Check common direct-search wording reaches constrained source presentation."""

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
REPORT = PROJECT / "experiments" / "reports" / "v1_519_direct_search_wording_transfer.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def build_index() -> CRMSResearchIndex:
    index = CRMSResearchIndex()
    sources = (
        ("sf-chinese", "Golden Dragon",
         "Golden Dragon is a Chinese restaurant in San Francisco, California."),
        ("oakland-chinese", "Harbor Noodle",
         "Harbor Noodle is a Chinese restaurant in Oakland, California."),
        ("sf-italian", "Little Napoli",
         "Little Napoli is an Italian restaurant in San Francisco, California."),
    )
    for document_id, title, sentence in sources:
        index.add_document(document_id, title, sentence,
                           f"{document_id}.txt")
    return index


def main() -> None:
    queries = (
        "I need to find a Chinese restaurant in San Francisco, California.",
        "I'm looking for a Chinese restaurant in San Francisco, California.",
        "Can you find a Chinese restaurant in San Francisco, California?",
        "Find me a Chinese restaurant in San Francisco, California.",
        "Where can I find a Chinese restaurant in San Francisco, California?",
        "I want a Chinese restaurant in San Francisco, California.",
        "Could you look for Chinese restaurants in San Francisco, California?",
    )
    index = build_index()
    cases = []
    for query in queries:
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        result = respond(dialogue, query, research_index=index)
        expected_sentence = (
            "Golden Dragon is a Chinese restaurant in San Francisco, California.")
        require(result.status == "sources_found"
                and result.intent_hypothesis is not None
                and result.intent_hypothesis.matched_frame
                    == "explicit-search-request"
                and expected_sentence in result.text
                and "Harbor Noodle" not in result.text
                and "Little Napoli" not in result.text,
                f"search wording did not present only the matching source: "
                f"{query!r}: {result.text!r}")
        require("not verified recommendations" in result.text.casefold()
                and not dialogue.knowledge.facts(),
                f"search result was overclaimed or learned as fact: {query!r}")
        cases.append({
            "query": query,
            "matched_frame": result.intent_hypothesis.matched_frame,
            "status": result.status,
            "expected_source_present": expected_sentence in result.text,
            "wrong_city_excluded": "Harbor Noodle" not in result.text,
            "wrong_cuisine_excluded": "Little Napoli" not in result.text,
            "accepted_fact_count": len(dialogue.knowledge.facts()),
        })

    no_match_query = "Can you find a French restaurant in San Francisco, California?"
    no_match_dialogue = CRMSDialogue(CRMSKnowledgeBase())
    no_match = respond(no_match_dialogue, no_match_query,
                       research_index=index)
    require(("couldn't find a source excerpt" in no_match.text.casefold()
             or "does not name french" in no_match.text.casefold())
            and "Golden Dragon" not in no_match.text
            and "Harbor Noodle" not in no_match.text
            and "Little Napoli" not in no_match.text,
            f"unsupported cuisine request did not abstain: {no_match.text!r}")
    cases.append({
        "query": no_match_query,
        "status": no_match.status,
        "abstained_without_partial_results": True,
        "accepted_fact_count": len(no_match_dialogue.knowledge.facts()),
    })

    report = {
        "experiment": "v1_519_direct_search_wording_transfer",
        "label_provenance": "Codex-authored development controls",
        "independent_validation": False,
        "result": "8/8 direct-search wording and abstention controls passed",
        "cases": cases,
        "limitations": [
            "One three-source synthetic index and one cuisine/location combination; this is not a natural-language search accuracy estimate.",
            "Wording coverage uses explicit forms and regular English plural matching, not open-ended paraphrase or semantic synonym understanding.",
            "All result judgments and expected answers were authored by Codex; no independent labeler or 70B comparator was used.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("PASS: seven common direct-search forms reach constrained source presentation")
    print("PASS: singular/plural restaurant wording retains the matching source")
    print("PASS: unsupported cuisine abstains without presenting partial results")
    print("LIMIT: synthetic development controls, not a search benchmark")
    print(f"REPORT: {REPORT}")


if __name__ == "__main__":
    main()
