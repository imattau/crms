"""Offers answer to yes/no, corrections re-ask without a verdict, and natural verdicts reach /right and /wrong."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import natural_feedback_verdict, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def make_knowledge() -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    for obj, source in (("the Analytical Engine", "a.txt"),
                        ("the Difference Engine", "b.txt")):
        knowledge.add_fact("Charles Babbage", "designed", obj, source)
        knowledge.teach_question(
            f"Who designed {obj}?", relation="designed", answer_field="subject",
            bound_entity=obj, answer="Charles Babbage")
    return knowledge


def main() -> None:
    # Only an explicit verdict about "that" or "it" maps to the feedback commands.
    for phrase, expected in (("That's wrong.", "wrong"), ("that is incorrect", "wrong"),
                             ("it's not right", "wrong"), ("That's right", "right"),
                             ("that's correct!", "right"), ("It is true", "right")):
        require(natural_feedback_verdict(phrase) == expected,
                f"verdict {phrase!r} did not map to {expected}")
    for phrase in ("correct", "right", "wrong", "that's not what I asked",
                   "that's wrong because the date is off", "Who is right?", "ok"):
        require(natural_feedback_verdict(phrase) is None,
                f"{phrase!r} was taken for a verdict")

    knowledge = make_knowledge()

    # Correction: re-ask the previous question about the named entity, no verdict.
    dialogue = CRMSDialogue(knowledge)
    respond(dialogue, "Who designed the Analytical Engine?")
    corrected = respond(dialogue, "No, I meant the Difference Engine")
    require(corrected.status == "answered"
            and "Asking again as ‘Who designed the Difference Engine?’" in corrected.text
            and "Charles Babbage" in corrected.text,
            f"correction did not re-ask the previous question: {corrected.text!r}")
    require(corrected.intent_hypothesis.dialogue_act == "correction"
            and corrected.intent_hypothesis.task_intent == "correct-result"
            and corrected.intent_hypothesis.decision == "selected",
            "correction did not expose its intent")
    require(dialogue.last_question == "Who designed the Difference Engine?",
            f"correction did not become the live question: {dialogue.last_question}")
    unanchored = respond(CRMSDialogue(knowledge), "I meant the Difference Engine")
    require("Asking again" not in unanchored.text and unanchored.status != "answered",
            f"a correction with no previous question invented one: {unanchored.text!r}")
    unknown = respond(dialogue, "I meant Zanzibar")
    require("Asking again" not in unknown.text,
            f"a correction to an unknown entity claimed a re-ask: {unknown.text!r}")

    # Offers: a pending-claims greeting opens one; yes runs the action, no declines.
    index = CRMSResearchIndex()
    greeted = CRMSDialogue(knowledge)
    hello = respond(greeted, "Hello", research_index=index, pending_claims=2)
    require("2 claims awaiting review" in hello.text
            and "Use /pending-candidates to inspect them." in hello.text
            and "Say ‘yes’ to review them now." in hello.text
            and len(greeted.offers) == 1,
            f"greeting with pending claims opened no visible offer: {hello.text!r}")
    nothing_pending = CRMSDialogue(knowledge)
    respond(nothing_pending, "Hello", research_index=index)
    require(not nothing_pending.offers, "greeting offered a review with nothing pending")
    yes = respond(greeted, "yes please")
    require(yes.action == "/pending-candidates" and yes.status == "social"
            and yes.intent_hypothesis.dialogue_act == "accept-offer"
            and not greeted.offers,
            f"yes did not accept the offer: {yes}")
    again = respond(greeted, "yes")
    require(again.action is None and again.intent_hypothesis.dialogue_act == "uncertain",
            "a second yes re-ran a consumed offer")

    declined = CRMSDialogue(knowledge)
    respond(declined, "Hello", research_index=index, pending_claims=1)
    no = respond(declined, "nope")
    require(no.action is None and no.intent_hypothesis.dialogue_act == "decline-offer"
            and not declined.offers, f"no did not decline the offer: {no}")

    # An offer lasts one intervening turn and is gone after two.
    survives = CRMSDialogue(knowledge)
    respond(survives, "Hello", research_index=index, pending_claims=1)
    respond(survives, "lol")
    require(respond(survives, "yes").action == "/pending-candidates",
            "an offer expired after a single other turn")
    expired = CRMSDialogue(knowledge)
    respond(expired, "Hello", research_index=index, pending_claims=1)
    respond(expired, "lol")
    respond(expired, "lol")
    require(respond(expired, "yes").action is None and not expired.offers,
            "an offer outlived its two turns")

    # An open answer choice or pronoun binding keeps its own yes/no handling.
    choosing = CRMSKnowledgeBase()
    choosing.add_fact("Ada Lovelace", "designed", "the Analytical Engine", "a")
    choosing.add_fact("Ada Lovelace", "designed", "the Difference Engine", "b")
    for answer in ("the Analytical Engine", "the Difference Engine"):
        choosing.teach_question("What did Ada Lovelace design?", relation="designed",
                                answer_field="object", bound_entity="Ada Lovelace",
                                answer=answer)
    busy = CRMSDialogue(choosing)
    respond(busy, "What did Ada Lovelace design?")
    busy.offers.append({"kind": "review_pending", "action": "/pending-candidates",
                        "turns_left": 2})
    answer = respond(busy, "yes")
    require(answer.action is None and "does not identify" in answer.text
            and busy.pending_result is not None,
            f"a yes meant for an open choice ran an offer: {answer.text!r}")

    # Terminal: yes runs /pending-candidates; natural verdicts reach /right and /wrong.
    with tempfile.TemporaryDirectory(prefix="crms-offers-") as folder:
        root = Path(folder)
        source = root / "history.txt"
        source.write_text("Charles Babbage designed the Analytical Engine.",
                          encoding="utf-8")
        CRMSKnowledgeBase().save(root / "empty-knowledge.json")
        sourced = CRMSResearchIndex()
        sourced.add_file(str(source))
        sourced.save(root / "index.json")
        make_knowledge().save(root / "knowledge.json")
        CRMSResearchIndex().save(root / "empty-index.json")
        script = Path(__file__).resolve().parents[1] / "crms_chat.py"

        def run(knowledge_file: str, index_file: str, session: str, text: str) -> str:
            return subprocess.run(
                [sys.executable, str(script),
                 "--knowledge", str(root / knowledge_file),
                 "--index", str(root / index_file),
                 "--rules", str(root / f"{session}-rules.json"),
                 "--dialogue-state", str(root / f"{session}-dialogue.json"),
                 "--rule-session", str(root / f"{session}-rule-session.json"),
                 "--candidate-session", str(root / f"{session}-candidates.json"),
                 "--feedback-db", str(root / f"{session}-feedback.sqlite3")],
                input=text, text=True, capture_output=True, check=True,
                timeout=30).stdout

        offered = run("empty-knowledge.json", "index.json", "offer",
                      "Who designed the Analytical Engine?\nyes\nGoodbye\n")
        require("Say ‘yes’ to review them now." in offered
                and "Okay, here they are." in offered
                and "you> /pending-candidates" in offered
                and "Charles Babbage" in offered.split("you> /pending-candidates")[-1],
                f"terminal did not run the accepted offer: {offered}")

        right = run("knowledge.json", "empty-index.json", "right",
                    "Who designed the Analytical Engine?\nThat's right.\nGoodbye\n")
        require("I recorded your feedback against" in right
                and "I don't have a recent evidence-backed answer" not in right,
                f"'that's right' did not reach /right: {right}")
        wrong = run("knowledge.json", "empty-index.json", "wrong",
                    "Who designed the Analytical Engine?\nthat is wrong\n/feedback\nGoodbye\n")
        require("I recorded your feedback against" in wrong
                and "WRONG #1: Who designed the Analytical Engine?" in wrong,
                f"'that is wrong' did not reach /wrong: {wrong}")
        require("RIGHT #" in run("knowledge.json", "empty-index.json", "right2",
                                 "Who designed the Analytical Engine?\nThat's right.\n"
                                 "/feedback\nGoodbye\n"),
                "'that's right' was not recorded as a right verdict")
        none = run("knowledge.json", "empty-index.json", "none", "that's wrong\nGoodbye\n")
        require("I don't have a recent evidence-backed answer to attach this to." in none,
                f"a verdict with no answer was not explained: {none}")
        corrected = run("knowledge.json", "empty-index.json", "fix",
                        "Who designed the Analytical Engine?\nNo, I meant the Difference Engine\n"
                        "/feedback\nGoodbye\n")
        require("Asking again as ‘Who designed the Difference Engine?’" in corrected
                and "No answer feedback has been recorded." in corrected,
                f"a correction recorded a verdict or did not re-ask: {corrected}")

    print("explicit verdict phrases map to /right and /wrong, bare words do not: PASS")
    print("'no, I meant X' re-asks the previous question and records no verdict: PASS")
    print("an offer is visible, answerable by yes or no, and expires after two turns: PASS")
    print("an open choice keeps its own yes/no handling: PASS")
    print("terminal runs an accepted offer and routes natural verdicts: PASS")


if __name__ == "__main__":
    main()
