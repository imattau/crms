"""Retain quoted-source names as referents without promoting them to facts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sourced_index() -> CRMSResearchIndex:
    index = CRMSResearchIndex()
    index.add_document(
        "ada-babbage", "Lovelace biography",
        "Ada Lovelace worked with Charles Babbage.",
        "biographies/lovelace.txt")
    return index


def main() -> None:
    index = sourced_index()
    kb = CRMSKnowledgeBase()
    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who worked with Charles Babbage?", research_index=index)
    require(first.status == "sources_found"
            and "quoted evidence, not an accepted fact" in first.text,
            f"source-only question did not produce the expected evidence label: {first}")
    require({item["entity"] for item in dialogue.source_mentions}
            == {"Ada Lovelace", "Charles Babbage"}
            and not kb.facts(),
            "quoted names were not retained separately from accepted facts")

    pronoun = dialogue.turn("Where did she work?", research_index=index)
    require(pronoun.status == "unknown"
            and "Ada Lovelace" in pronoun.text
            and "Charles Babbage" in pronoun.text
            and "Lovelace biography" in pronoun.text
            and pronoun.response is not None
            and pronoun.response.status == "unknown",
            f"ambiguous source-only referent was guessed or hidden: {pronoun}")
    require(not kb.facts(),
            "dialogue referent candidates were promoted into the fact store")

    # Once the required question frames are licensed, existing evidence can
    # resolve subject/object pronouns by supported substitution.
    framed = CRMSKnowledgeBase()
    rows = (
        ("Ada Lovelace", "worked with", "Charles Babbage", "fact:ada-babbage"),
        ("Grace Hopper", "worked with", "Charles Dickens", "fact:grace-dickens"),
        ("Ada Lovelace", "worked at", "Somerville College", "fact:ada-work"),
        ("Grace Hopper", "worked at", "NASA", "fact:grace-work"),
    )
    for subject, relation, obj, source in rows:
        framed.add_fact(subject, relation, obj, source)
    for subject, obj in (("Ada Lovelace", "Charles Babbage"),
                         ("Grace Hopper", "Charles Dickens")):
        framed.teach_question(
            f"Who worked with {obj}?", relation="worked with",
            answer_field="subject", bound_entity=obj, answer=subject)
    for subject, obj in (("Ada Lovelace", "Somerville College"),
                         ("Grace Hopper", "NASA")):
        framed.teach_question(
            f"Where did {subject} work?", relation="worked at",
            answer_field="object", bound_entity=subject, answer=obj)

    resolved_dialogue = CRMSDialogue(framed)
    answer = resolved_dialogue.turn("Who worked with Charles Babbage?")
    followup = resolved_dialogue.turn("Where did she work?")
    if (answer.status != "answered" or followup.status != "answered"
            or followup.resolved_question != "Where did Ada Lovelace work?"
            or followup.response is None
            or followup.response.answer != "Somerville College"):
        raise SystemExit(f"supported 'she' follow-up failed: {followup}")
    object_dialogue = CRMSDialogue(framed)
    object_dialogue.turn("Who worked with Charles Babbage?")
    object_pronoun = object_dialogue.turn("Who worked with him?")
    if (object_pronoun.status != "answered"
            or object_pronoun.resolved_question !=
            "Who worked with Charles Babbage?"
            or object_pronoun.response is None
            or object_pronoun.response.answer != "Ada Lovelace"):
        raise SystemExit(f"supported 'him' follow-up failed: {object_pronoun}")

    print("source-only names stay cited referent candidates, never accepted facts: PASS")
    print("ambiguous follow-up asks for a named choice instead of guessing: PASS")
    print("licensed fact frames still resolve supported she/him substitutions: PASS")


if __name__ == "__main__":
    main()
