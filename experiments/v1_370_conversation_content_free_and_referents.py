"""Reactions stay out of retrieval, greetings read correctly, and quoted answers keep referents."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_act, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


SOURCE_TEXT = (
    "Ada Lovelace wrote the first published algorithm. "
    "Ada Lovelace worked with Charles Babbage. "
    "Charles Babbage designed the Analytical Engine. "
    "The Analytical Engine was built in London. "
    "Grace Hopper created the first compiler. "
    "Grace Hopper worked at Harvard. "
    "Players of the game call it LoL and share jokes about it.")


class CountingIndex:
    """Wraps a real index and records every retrieval call."""

    def __init__(self, index: CRMSResearchIndex) -> None:
        self.index = index
        self.searches = 0

    def __getattr__(self, name):
        attribute = getattr(self.index, name)
        if name.startswith("search") and callable(attribute):
            def counted(*args, **kwargs):
                self.searches += 1
                return attribute(*args, **kwargs)
            return counted
        return attribute


def make_index(folder: Path) -> CountingIndex:
    path = folder / "history.txt"
    path.write_text(SOURCE_TEXT, encoding="utf-8")
    index = CRMSResearchIndex()
    index.add_file(str(path))
    return CountingIndex(index)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-conversation-") as folder:
        index = make_index(Path(folder))
        knowledge = CRMSKnowledgeBase()

        # Greeting counts use correct plurals and a single clause for pending claims.
        one = respond(CRMSDialogue(knowledge), "Hello", research_index=index,
                      pending_claims=1)
        require("0 accepted facts and 1 source document loaded" in one.text
                and ", with 1 claim awaiting review." in one.text,
                f"greeting grammar was wrong for singular counts: {one.text!r}")
        many = respond(CRMSDialogue(knowledge), "Hello", research_index=index,
                       pending_claims=2)
        require("2 claims awaiting review" in many.text
                and "loaded, with 2 claims" in many.text,
                f"greeting grammar was wrong for plural counts: {many.text!r}")
        none = respond(CRMSDialogue(knowledge), "Hello", research_index=index)
        require("awaiting review" not in none.text and "loaded." in none.text,
                f"greeting mentioned review with nothing pending: {none.text!r}")

        # Reactions and non-lexical turns never reach retrieval, even though the
        # corpus contains the word "LoL".
        for phrase in ("lol", "LOL!", "haha", "hahaha", "wow", "cool", "nice.",
                       "🙂", "!!!", "…"):
            before = index.searches
            turn = respond(CRMSDialogue(knowledge), phrase, research_index=index)
            require(index.searches == before and turn.status in {"social", "unclassified"}
                    and "Source" not in turn.text,
                    f"content-free turn reached retrieval: {phrase!r}: {turn}")
        reaction = respond(CRMSDialogue(knowledge), "lol", research_index=index)
        require(reaction.intent_hypothesis is not None
                and reaction.intent_hypothesis.dialogue_act == "reaction"
                and reaction.intent_hypothesis.task_intent == "social-contact",
                "reaction did not expose its intent hypothesis")

        # Content turns are never swallowed.
        for phrase in ("2 + 3 * 4", "2+3", "great wall of china location",
                       "nice try python", "Who created Python?", "Python"):
            require(classify_act(phrase) is None,
                    f"content turn was classified as an act: {phrase!r}")

        # A reaction does not consume or close an open answer choice.
        ambiguous = CRMSKnowledgeBase()
        ambiguous.add_fact("Ada Lovelace", "designed", "the Analytical Engine", "a")
        ambiguous.add_fact("Ada Lovelace", "designed", "the Difference Engine", "b")
        for answer in ("the Analytical Engine", "the Difference Engine"):
            ambiguous.teach_question(
                "What did Ada Lovelace design?", relation="designed",
                answer_field="object", bound_entity="Ada Lovelace", answer=answer)
        choosing = CRMSDialogue(ambiguous)
        choosing.turn("What did Ada Lovelace design?")
        require(choosing.pending_result is not None, "test setup lost its open choice")
        respond(choosing, "lol", research_index=index)
        require(choosing.pending_result is not None,
                "a reaction closed an open answer choice")

        # A quoted answer that awaits review keeps its names as candidate referents.
        dialogue = CRMSDialogue(knowledge)
        first = respond(dialogue, "Who designed the Analytical Engine?",
                        research_index=index)
        require("Charles Babbage designed the Analytical Engine" in first.text,
                f"setup answer changed: {first.text!r}")
        mentioned = {item["entity"] for item in dialogue.source_mentions}
        require({"Charles Babbage", "Analytical Engine"} <= mentioned,
                f"quoted answer left no candidate referents: {mentioned}")
        follow_up = respond(dialogue, "Who worked with him?", research_index=index)
        require("Charles Babbage" in follow_up.text
                and "Which entity do you mean?" in follow_up.text,
                f"pronoun after a quoted answer gave no named choice: {follow_up.text!r}")

        # Referents are not carried across an unrelated refusal.
        stale = CRMSDialogue(knowledge)
        respond(stale, "Who designed the Analytical Engine?", research_index=index)
        respond(stale, "What is the airspeed of a swallow?", research_index=index)
        gone = respond(stale, "Who worked with him?", research_index=index)
        require("Charles Babbage" not in gone.text,
                f"a stale referent survived an unrelated turn: {gone.text!r}")

    print("greeting counts and the review clause read correctly: PASS")
    print("reactions and non-lexical turns never reach retrieval: PASS")
    print("calculations and real questions are not classified as acts: PASS")
    print("a reaction leaves an open answer choice intact: PASS")
    print("a quoted answer under review keeps candidate referents: PASS")
    print("an unrelated refusal still clears stale referents: PASS")


if __name__ == "__main__":
    main()
