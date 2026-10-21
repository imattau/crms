"""Phase 11 Stage A: source-to-proposition intake feeding generation.

Questions are answered from a request's own source documents with relation
specs; verified matches become facts for the Phase 10 planner. Checks that facts
carry real source sentences, pronoun and unsupported questions abstain, the
composed text is not a quote, results are deterministic, and a request with no
answerable question does not invent content.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generate import request_from_mapping  # noqa: E402
from crms_generation import GenerationEngine, copy_ratio  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402
from crms_source_intake import intake_facts  # noqa: E402

DOCS = [
    {"name": "film.txt", "text": "Lantern Bay is a film directed by Rafe Ostin. It was released in 1999. Critics praised the photography."},
    {"name": "firm.txt", "text": "Binago Works was founded in 1934 by Anna Rossi. Binago Works is a toolmaker in Como."},
    {"name": "press.txt", "text": "Aldo Press is a publisher. Aldo Press was established in 1960."},
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    questions = [
        {"question": "Who directed Lantern Bay?", "role": "main"},
        {"question": "When was Binago Works founded?", "role": "support"},
        {"question": "When was Aldo Press established?", "role": "support"},
        {"question": "When was Lantern Bay released?", "role": "support"},     # pronoun-only sentence
        {"question": "Who wrote The Missing Book?", "role": "support"},        # no source
    ]
    documents = [(d["name"], d["text"]) for d in DOCS]
    facts, report = intake_facts(questions, documents)
    status = {r["question"]: r["status"] for r in report}
    require(len(facts) == 3, f"expected 3 facts, got {len(facts)}: {report}")
    require(status["When was Lantern Bay released?"] == "abstained",
            "a pronoun-only sentence must not answer for a named entity")
    require(status["Who wrote The Missing Book?"] == "abstained", "unsupported question answered")
    corpus = " ".join(text for _n, text in documents)
    for fact in facts:
        require(fact.source_text in corpus, f"fact source sentence not in the documents: {fact}")
        require(fact.span in fact.source_text, f"fact span not in its sentence: {fact}")
        require("intake" in fact.tags, "fact is not tagged as intake")

    raw = {"prompt": "Summarise the sources on Lantern Bay, Binago Works and Aldo Press.",
           "genre": "summary", "audience": "general", "style": "plain",
           "source_documents": DOCS, "intake": {"questions": questions}}
    engine = GenerationEngine(load_rules())
    result = engine.generate(request_from_mapping(raw))
    require(result.status == "ok", f"generation did not pass: {result.status} {result.message}")
    require("Rafe Ostin directed Lantern Bay" in result.text and "1934" in result.text and "1960" in result.text,
            f"intake facts missing from the composed text: {result.text!r}")
    require(copy_ratio(result.text, [d["text"] for d in DOCS]) < 0.7,
            "composed text is too close to the sources")
    again = engine.generate(request_from_mapping(raw))
    require(again.text == result.text, "intake generation is not deterministic")

    # without an intake key nothing changes
    plain = {k: v for k, v in raw.items() if k != "intake"}
    require(request_from_mapping(plain).facts == (), "a request without intake gained facts")

    # nothing answerable -> no facts, and generation declines instead of inventing
    empty_facts, empty_report = intake_facts(["Who wrote The Missing Book?"], documents)
    require(not empty_facts and empty_report[0]["status"] == "abstained", "empty intake produced facts")
    declined = engine.generate(request_from_mapping(
        {**raw, "intake": {"questions": ["Who wrote The Missing Book?"]}}))
    require(declined.status in {"abstain", "clarify"} and not declined.text,
            f"generation invented content from nothing: {declined.status}")
    print("Phase 11 source intake contract passed")


if __name__ == "__main__":
    main()
