"""An ambiguous pronoun offers a numbered choice, and 'what do you know about X' lists cited facts."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


SOURCE_TEXT = (
    "Ada Lovelace worked with Charles Babbage. "
    "Charles Babbage designed the Analytical Engine. "
    "Grace Hopper worked at Harvard.")


def make_index(folder: Path) -> CRMSResearchIndex:
    path = folder / "history.txt"
    path.write_text(SOURCE_TEXT, encoding="utf-8")
    index = CRMSResearchIndex()
    index.add_file(str(path))
    return index


FACTS = (
    ("Charles Babbage", "designed", "the Analytical Engine", "a.txt"),
    ("Charles Babbage", "worked with", "Ada Lovelace", "b.txt"),
    ("Charles Babbage", "born in", "London", "c.txt"),
    ("Charles Babbage", "studied at", "Cambridge", "d.txt"),
    ("Charles Babbage", "wrote", "On the Economy of Machinery", "e.txt"),
    ("Charles Babbage", "died in", "London", "f.txt"),
    ("Ada Lovelace", "wrote", "the first published algorithm", "g.txt"),
)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-binding-") as folder:
        index = make_index(Path(folder))
        knowledge = CRMSKnowledgeBase()

        # An ambiguous pronoun keeps its candidates; a number or name picks one.
        dialogue = CRMSDialogue(knowledge)
        respond(dialogue, "Who designed the Analytical Engine?", research_index=index)
        asked = respond(dialogue, "Who worked with him?", research_index=index)
        require(asked.status == "unknown" and dialogue.pending_binding is not None
                and "Which entity do you mean?" in asked.text
                and "Or reply with a number or a name: 1." in asked.text
                and "Charles Babbage" in asked.text,
                f"ambiguous pronoun gave no numbered choice: {asked.text!r}")
        require(asked.intent_hypothesis is not None
                and asked.intent_hypothesis.decision == "ambiguous"
                and asked.intent_hypothesis.matched_frame == "pronoun-binding-request",
                "ambiguous pronoun did not expose its alternatives")
        names = [option["entity"] for option in dialogue.pending_binding["options"]]
        number = names.index("Charles Babbage") + 1
        picked = respond(dialogue, str(number), research_index=index)
        require("Ada Lovelace worked with Charles Babbage" in picked.text
                and dialogue.pending_binding is None
                and picked.intent_hypothesis.matched_frame == "pronoun-binding-selection"
                and picked.intent_hypothesis.selected_value == "Charles Babbage",
                f"choosing by number did not run the chosen question: {picked.text!r}")
        require(not knowledge.facts(), "a binding choice promoted a fact")

        respond(dialogue, "Who designed the Analytical Engine?", research_index=index)
        respond(dialogue, "Who worked with him?", research_index=index)
        by_name = respond(dialogue, "Charles Babbage", research_index=index)
        require("Ada Lovelace worked with Charles Babbage" in by_name.text,
                f"choosing by name did not run the chosen question: {by_name.text!r}")

        # Receipts keep the choice open; any other turn discards it.
        respond(dialogue, "Who designed the Analytical Engine?", research_index=index)
        respond(dialogue, "Who worked with him?", research_index=index)
        for phrase in ("ok", "yes", "lol"):
            kept = respond(dialogue, phrase, research_index=index)
            require(kept.status == "ambiguous" and dialogue.pending_binding is not None
                    and "Please choose:" in kept.text,
                    f"{phrase!r} closed or ignored the open choice: {kept.text!r}")
        other = respond(dialogue, "banana", research_index=index)
        require(dialogue.pending_binding is None and "Please choose" not in other.text,
                "an unrelated turn did not discard the open choice")
        gone = respond(dialogue, "1", research_index=index)
        require("Ada Lovelace worked with" not in gone.text,
                f"a discarded choice was still answerable: {gone.text!r}")

        # An unresolved pronoun with no candidates is unchanged.
        fresh = respond(CRMSDialogue(knowledge), "Who worked with him?", research_index=index)
        require(fresh.text == "Please name the entity this pronoun refers to."
                and fresh.status == "unknown",
                f"a pronoun with no referent changed its reply: {fresh.text!r}")

        # Entity overview over accepted facts.
        facts = CRMSKnowledgeBase()
        for subject, relation, obj, source in FACTS:
            facts.add_fact(subject, relation, obj, source)
        overview = CRMSDialogue(facts)
        first = respond(overview, "What do you know about Charles Babbage?",
                        research_index=index)
        require(first.status == "elaborated"
                and first.text.startswith("What I have accepted about Charles Babbage:")
                and first.text.count("\n- ") == 5 and "[source: " in first.text
                and "1 more available" in first.text
                and "Ada Lovelace — wrote" not in first.text,
                f"overview was wrong: {first.text!r}")
        require(first.intent_hypothesis is not None
                and first.intent_hypothesis.matched_frame == "entity-overview",
                "overview did not expose its intent")
        rest = respond(overview, "Tell me more", research_index=index)
        require(rest.text.startswith("More about Charles Babbage:")
                and rest.text.count("\n- ") == 1 and "everything I have accepted" in rest.text,
                f"'tell me more' after an overview repeated or lost facts: {rest.text!r}")
        again = respond(overview, "What can you tell me about Charles Babbage", research_index=index)
        require(again.text.count("\n- ") == 5,
                f"asking again did not restart the overview: {again.text!r}")
        lovelace = respond(overview, "what do you know about Ada Lovelace?",
                           research_index=index)
        require("Ada Lovelace — wrote" in lovelace.text
                and "Charles Babbage — worked with → Ada Lovelace" in lovelace.text,
                f"overview missed a fact with the entity as object: {lovelace.text!r}")

        # Unknown entities and taught about-frames keep their existing handling.
        unknown = respond(CRMSDialogue(facts), "What do you know about Python?",
                          research_index=index)
        require(unknown.status != "elaborated" and "What I have accepted" not in unknown.text,
                f"overview invented a card for an unknown entity: {unknown.text!r}")
        sourced_only = respond(CRMSDialogue(knowledge), "What do you know about Grace Hopper?",
                               research_index=index)
        require(sourced_only.status != "elaborated",
                "overview presented quoted source names as accepted facts")

    print("an ambiguous pronoun offers a numbered choice that runs the chosen question: PASS")
    print("receipts keep the choice open; other turns discard it: PASS")
    print("'what do you know about X' lists cited accepted facts and 'tell me more' continues: PASS")
    print("unknown and source-only entities keep their existing handling: PASS")


if __name__ == "__main__":
    main()
