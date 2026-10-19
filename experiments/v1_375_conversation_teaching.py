"""A plain statement is proposed, confirmed, stored as told by the user, and queryable."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import parse_statement, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    parsed = {
        "Ada Lovelace wrote the first published algorithm.":
            ("Ada Lovelace", "wrote", "the first published algorithm"),
        "Mary Shelley wrote Frankenstein.": ("Mary Shelley", "wrote", "Frankenstein"),
        "Ada Lovelace worked with Charles Babbage.":
            ("Ada Lovelace", "worked with", "Charles Babbage"),
        "Python was created by Guido van Rossum.":
            ("Python", "was created by", "Guido van Rossum"),
        "Grace Hopper worked at Harvard": ("Grace Hopper", "worked at", "Harvard"),
    }
    for sentence, expected in parsed.items():
        require(parse_statement(sentence) == expected,
                f"statement parsed wrongly: {sentence!r} -> {parse_statement(sentence)}")
    for sentence in ("Who created Python?", "Tell me about Ada Lovelace.",
                     "My name is Matt.", "Ada wrote it and Babbage built it.",
                     "Compose a short story about Marie Curie.", "2 + 3 * 4",
                     "Hello, Ada Lovelace wrote code.", "Ada Lovelace",
                     "Teach CRMS that Ada wrote code.", "what is the capital of France",
                     "/pending-candidates", "Please translate this sentence"):
        require(parse_statement(sentence) is None,
                f"a non-statement was parsed: {sentence!r}")

    knowledge = CRMSKnowledgeBase()
    dialogue = CRMSDialogue(knowledge)
    index = CRMSResearchIndex()

    # Proposal first: nothing is stored until the user confirms.
    proposal = respond(dialogue, "Ada Lovelace wrote the first published algorithm.",
                       research_index=index)
    require(proposal.status == "social" and not proposal.learned
            and "I understood: Ada Lovelace — wrote → the first published algorithm."
            in proposal.text and "Shall I remember" in proposal.text
            and not knowledge.facts() and len(dialogue.offers) == 1,
            f"statement was not held for confirmation: {proposal.text!r} {knowledge.facts()}")
    require(proposal.intent_hypothesis.dialogue_act == "inform"
            and proposal.intent_hypothesis.decision == "ambiguous"
            and "remember" in proposal.intent_hypothesis.alternatives,
            "statement proposal did not expose its alternatives")

    first = respond(dialogue, "yes", research_index=index)
    facts = knowledge.facts()
    require(first.status == "learned" and first.learned and len(facts) == 1
            and facts[0].sources[0].startswith("told by user#")
            and "[told by user]" in first.text
            and "I need one more example with different names" in first.text
            and f"/retract-fact POS|Ada Lovelace|wrote|the first published algorithm|"
                f"{facts[0].sources[0]}" in first.text,
            f"confirmed statement was not stored as told by the user: {first.text!r}")
    asked = respond(dialogue, "Who wrote the first published algorithm?",
                    research_index=index)
    require("Ada Lovelace" in asked.text and "told by user" in asked.text
            and asked.status != "unknown",
            f"a told-by-user fact was not queryable: {asked.text!r}")

    # A second example with different names licenses the wording; the question
    # still renders, and nothing is stored without another confirmation.
    respond(dialogue, "Grace Hopper wrote the first compiler.", research_index=index)
    require(len(knowledge.facts()) == 1, "a second statement was stored unconfirmed")
    second = respond(dialogue, "yes", research_index=index)
    require("I can now recognise sentences worded like that one." in second.text
            and len(knowledge.facts()) == 2, f"second example was not learned: {second.text!r}")
    again = respond(dialogue, "Who wrote the first compiler?", research_index=index)
    require("Grace Hopper" in again.text and again.status != "unknown",
            f"answer after a learned pattern failed to render: {again.text!r}")

    # Origins: everything told by the user shares one document-level source.
    origins = {source.split("#", 1)[0] for fact in knowledge.facts()
               for source in fact.sources}
    require(origins == {"told by user"},
            f"user statements counted as separate origins: {origins}")

    # Duplicates, declines and expiry store nothing.
    duplicate = respond(dialogue, "Ada Lovelace wrote the first published algorithm.",
                        research_index=index)
    require("I already have that" in duplicate.text and not dialogue.offers,
            f"a known statement was proposed again: {duplicate.text!r}")
    respond(dialogue, "Mary Shelley wrote Frankenstein.", research_index=index)
    declined = respond(dialogue, "no", research_index=index)
    require("won't remember" in declined.text and len(knowledge.facts()) == 2
            and declined.intent_hypothesis.dialogue_act == "decline-offer",
            f"a declined statement was stored: {declined.text!r}")
    respond(dialogue, "Mary Shelley wrote Frankenstein.", research_index=index)
    respond(dialogue, "lol")
    respond(dialogue, "lol")
    late = respond(dialogue, "yes")
    require(len(knowledge.facts()) == 2 and not late.learned,
            "an expired confirmation still stored the statement")

    # Anything that is not a plain statement keeps its existing route.
    for text in ("Who wrote Frankenstein?", "Tell me about Mary Shelley.",
                 "My name is Matt.", "What do you know about Ada Lovelace?"):
        other = respond(CRMSDialogue(knowledge), text, research_index=index)
        require(not other.learned and "I understood:" not in other.text,
                f"a non-statement was proposed for learning: {text!r}")

    # Terminal: confirm, persist across a restart, query, then forget.
    with tempfile.TemporaryDirectory(prefix="crms-teaching-") as folder:
        root = Path(folder)
        CRMSKnowledgeBase().save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "index.json")
        script = Path(__file__).resolve().parents[1] / "crms_chat.py"

        def run(text: str) -> str:
            return subprocess.run(
                [sys.executable, str(script),
                 "--knowledge", str(root / "knowledge.json"),
                 "--index", str(root / "index.json"),
                 "--rules", str(root / "rules.json"),
                 "--dialogue-state", str(root / "dialogue.json"),
                 "--rule-session", str(root / "rule-session.json"),
                 "--candidate-session", str(root / "candidates.json"),
                 "--feedback-db", str(root / "feedback.sqlite3")],
                input=text, text=True, capture_output=True, check=True,
                timeout=30).stdout

        taught = run("Ada Lovelace wrote the first published algorithm.\nyes\nGoodbye\n")
        require("Remembered: Ada Lovelace — wrote → the first published algorithm"
                in taught, f"terminal did not store the confirmed statement: {taught}")
        reloaded = CRMSKnowledgeBase.load(root / "knowledge.json")
        require(len(reloaded.facts()) == 1,
                "the learned fact was not saved to the knowledge file")
        asked = run("Who wrote the first published algorithm?\nGoodbye\n")
        require("Ada Lovelace" in asked and "told by user" in asked,
                f"a restarted session lost the told-by-user fact: {asked}")
        source = reloaded.facts()[0].sources[0]
        forgot = run("/retract-fact POS|Ada Lovelace|wrote|"
                     f"the first published algorithm|{source}\n"
                     "Who wrote the first published algorithm?\nGoodbye\n")
        require("Retracted the final source support; the fact is no longer stored."
                in forgot
                and "Ada Lovelace wrote" not in forgot.split("Retracted")[-1],
                f"the forget command did not remove the fact: {forgot}")
        require(not CRMSKnowledgeBase.load(root / "knowledge.json").facts(),
                "the retracted fact is still in the knowledge file")

    print("plain statements are parsed narrowly and everything else is left alone: PASS")
    print("a statement is held until confirmed, then stored as told by the user: PASS")
    print("told-by-user facts answer questions and share one source origin: PASS")
    print("a second example licenses the wording and still renders: PASS")
    print("duplicates, declines and expiry store nothing: PASS")
    print("the fact survives a restart and the printed forget command removes it: PASS")


if __name__ == "__main__":
    main()
