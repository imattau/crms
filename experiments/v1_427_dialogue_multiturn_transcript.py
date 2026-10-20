"""Replay a longer topic-switch transcript and separate safety from coverage."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


CORPUS = (
    "The Eiffel Tower is a landmark in Paris. "
    "It was completed in 1889 and stands 330 metres tall. "
    "The tower was designed and built by Gustave Eiffel. "
    "The Seine flows through Paris, the capital of France.\n\n"
    "The Colosseum is an amphitheatre in Rome. "
    "It was completed in 80 CE and could hold 50,000 spectators. "
    "Rome is the capital of Italy. The Tiber flows through Rome."
)

TRANSCRIPT = (
    "Hello",
    "What can you do?",
    "Where is the Eiffel Tower?",
    "When was it completed?",
    "How tall is it?",
    "Who built it?",
    "Which river flows through Paris?",
    "What about the Colosseum?",
    "Where is it?",
    "When was it completed?",
    "How many people could it hold?",
    "Why?",
    "What did I just ask?",
    "And Italy?",
    "What did I just ask?",
    "The first one",
    "Who designed the Analytical Engine?",
    "When was it completed?",
    "What about the Eiffel Tower?",
    "When was it completed?",
    "What is the capital of France?",
    "And Italy?",
    "What is its capital?",
    "Which river flows through Rome?",
    "Where does the Tiber flow?",
    "Who built the Eiffel Tower?",
    "Who designed it?",
    "What source supports that?",
    "Tell me a joke",
    "Why?",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-dialogue-transcript-") as folder:
        Path(folder, "travel.txt").write_text(CORPUS, encoding="utf-8")
        index = CRMSResearchIndex()
        index.add_directory(folder)
        dialogue = CRMSDialogue(CRMSKnowledgeBase())
        dialogue_path = Path(folder, "dialogue.json")
        turns = []
        for number, text in enumerate(TRANSCRIPT, 1):
            turns.append(respond(dialogue, text, research_index=index))
            if number == 18:
                # The entity clarification is a bounded discourse state and
                # must survive a normal restart before the user's response.
                dialogue.save(str(dialogue_path))
                dialogue = CRMSDialogue.load(
                    CRMSKnowledgeBase(), str(dialogue_path),
                    research_index=index)

    require(len(turns) == 30, f"transcript stopped early: {len(turns)} turns")
    require(all(turn.status for turn in turns), "a transcript turn has no status")

    # Safety: the named Colosseum switch and its elliptical follow-ups must
    # stay in its paragraph; the explanation must target the latest answer.
    for number, expected in ((8, "Colosseum"), (9, "Rome"), (10, "80 CE"),
                             (11, "50,000 spectators"),
                             (12, "50,000 spectators")):
        text = turns[number - 1].text
        require(expected.casefold() in text.casefold(),
                f"turn {number} lost its expected evidence {expected!r}: {text}")
        require("1889" not in text,
                f"turn {number} leaked Eiffel Tower evidence: {text}")
    require("How many people could Colosseum hold?" in turns[12].text,
            f"history recall did not report the preceding question: {turns[12]!r}")
    require("And Italy?" in turns[14].text,
            f"history recall was not updated after an unanswered turn: {turns[14]!r}")
    unbound_ordinal = turns[15]
    require(unbound_ordinal.status == "clarify"
            and "numbered source list" in unbound_ordinal.text.casefold()
            and "Which result or entity" in unbound_ordinal.text,
            "an ordinal with no open list should ask what the user means, "
            f"not fall through to a generic unknown answer: {unbound_ordinal!r}")
    clarification = turns[17]
    require(clarification.status == "unknown"
            and "Please name the entity" in clarification.text,
            f"unresolved pronoun did not request its missing entity: {clarification!r}")
    recovered = turns[18]
    require(recovered.status == "sources_found"
            and recovered.resolved_question
                == "When was the Eiffel Tower completed?"
            and "1889" in recovered.text
            and "Gustave Eiffel" not in recovered.text
            and recovered.research is not None
            and recovered.research.source_sentences,
            f"named entity did not fill the open pronoun clarification: {recovered!r}")
    recovered_citation = recovered.research.source_sentences[0]
    require(index.resolve_citation(recovered_citation["citation"])
            == recovered_citation["text"],
            "clarification recovery returned an inexact evidence citation")
    completed = turns[19]
    require(completed.status == "sources_found"
            and completed.resolved_question == "When was Eiffel Tower completed?"
            and "1889" in completed.text,
            f"the recovered entity did not remain available for the next turn: {completed!r}")

    # The pending entity slot is a one-step clarification, not a sticky mode.
    interrupted = CRMSDialogue(CRMSKnowledgeBase())
    respond(interrupted, "When was it completed?", research_index=index)
    respond(interrupted, "Tell me a joke", research_index=index)
    after_interruption = respond(
        interrupted, "What about the Eiffel Tower?", research_index=index)
    require(after_interruption.status == "unknown"
            and after_interruption.resolved_question
                != "When was the Eiffel Tower completed?",
            f"an unrelated turn left a stale entity clarification open: {after_interruption!r}")
    lowercase_reply = CRMSDialogue(CRMSKnowledgeBase())
    respond(lowercase_reply, "When was it completed?", research_index=index)
    lowercase_recovered = respond(
        lowercase_reply, "what about the eiffel tower?", research_index=index)
    require(lowercase_recovered.resolved_question
                == "When was the Eiffel Tower completed?"
            and lowercase_recovered.status == "sources_found",
            f"lowercase entity reply did not resolve against the index: {lowercase_recovered!r}")
    bare_confirmation = CRMSDialogue(CRMSKnowledgeBase())
    respond(bare_confirmation, "When was it completed?", research_index=index)
    confirmation_reply = respond(
        bare_confirmation, "and yes", research_index=index)
    require(confirmation_reply.resolved_question
                != "When was yes completed?",
            f"a bare confirmation was inserted as an entity name: {confirmation_reply!r}")
    built = turns[25]
    require(built.status == "sources_found"
            and "designed and built by Gustave Eiffel" in built.text
            and "1889" not in built.text,
            f"named Eiffel Tower did not bind its paragraph-local 'the tower' evidence: {built!r}")
    designed = turns[26]
    require(designed.status == "sources_found"
            and designed.resolved_question == "Who designed Eiffel Tower?"
            and "designed and built by Gustave Eiffel" in designed.text,
            f"follow-up pronoun drifted from the explicitly named tower: {designed!r}")
    possessive = turns[22]
    require(possessive.status == "needs_review"
            and possessive.resolved_question == "What is the capital of Italy?"
            and "Rome is the capital of Italy" in possessive.text
            and "Paris" not in possessive.text
            and possessive.research is not None
            and possessive.research.source_sentences,
            f"source-only possessive follow-up lost or misbound Italy: {possessive!r}")
    cited = possessive.research.source_sentences[0]
    require(index.resolve_citation(cited["citation"]) == cited["text"],
            "source-only possessive answer has an inexact citation")
    require("80 CE" not in turns[29].text and "1889" not in turns[29].text,
            "final why? reused stale evidence after an out-of-scope turn")

    # Coverage is deliberately reported separately: the experiment must not
    # turn honest abstentions into apparent passes.
    weak_coverage = [number for number in (18,)
                     if turns[number - 1].status in {"unknown", "clarify"}]
    print("multi-turn transcript: 30 turns, no crash")
    print("topic switch and Colosseum follow-ups: grounded, no cross-topic leak")
    print("history, stale-explanation, and clarification save/reload: PASS")
    print("unresolved pronoun turns:", ", ".join(
        f"{n}:{turns[n - 1].status}" for n in weak_coverage) or "none")
    print("entity clarification resumes the held question; completion follow-up: PASS")
    print("unrelated turn expires the entity clarification: PASS")
    print("built date remains unstated; related source wording is shown without converting")
    print("the completion date into a construction date")


if __name__ == "__main__":
    main()
