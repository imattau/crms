"""Conversation memory survives refusals, 'tell me more' shows cited facts, and state persists."""

from __future__ import annotations

import json
import subprocess
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


FACTS = (
    ("Charles Babbage", "designed", "the Analytical Engine", "a.txt"),
    ("Charles Babbage", "worked with", "Ada Lovelace", "b.txt"),
    ("Charles Babbage", "born in", "London", "c.txt"),
    ("Charles Babbage", "studied at", "Cambridge", "d.txt"),
    ("Ada Lovelace", "wrote", "the first published algorithm", "e.txt"),
)


def make_knowledge() -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    for subject, relation, obj, source in FACTS:
        knowledge.add_fact(subject, relation, obj, source)
    knowledge.teach_question(
        "Who designed the Analytical Engine?", relation="designed",
        answer_field="subject", bound_entity="the Analytical Engine",
        answer="Charles Babbage")
    return knowledge


class NoRetrievalIndex:
    def document_count(self) -> int:
        return 0

    def search(self, *_args, **_kwargs):
        raise AssertionError("elaboration reached source retrieval")


def main() -> None:
    knowledge = make_knowledge()
    index = NoRetrievalIndex()

    # A grounded answer is remembered separately from the live referents.
    dialogue = CRMSDialogue(knowledge)
    answer = respond(dialogue, "Who designed the Analytical Engine?")
    require(answer.status == "answered"
            and dialogue.last_answered is not None
            and dialogue.last_answered["question"]
            == "Who designed the Analytical Engine?"
            and dialogue.last_answered["answer"] == "Charles Babbage",
            f"answered turn was not remembered: {dialogue.last_answered}")

    # 'Tell me more' pages through accepted facts, citing sources, without retrieval.
    first = respond(dialogue, "Tell me more", research_index=index)
    require(first.status == "elaborated" and first.text.startswith("About Charles Babbage:")
            and first.text.count("\n- ") == 3 and "[source: " in first.text
            and "1 more available" in first.text,
            f"first elaboration was wrong: {first.text!r}")
    second = respond(dialogue, "go on", research_index=index)
    require(second.status == "elaborated" and second.text.startswith("More about Charles Babbage:")
            and second.text.count("\n- ") == 1
            and "everything I have accepted" in second.text,
            f"second elaboration was wrong: {second.text!r}")
    shown_lines = {line for line in (first.text + "\n" + second.text).splitlines()
                   if line.startswith("- ")}
    require(len(shown_lines) == 4, f"a fact was repeated or lost: {shown_lines}")
    require("Ada Lovelace — wrote" not in first.text + second.text,
            "elaboration included a fact about an unrelated entity")
    third = respond(dialogue, "anything else?", research_index=index)
    require("everything I have accepted" in third.text and "\n- " not in third.text,
            f"exhausted elaboration repeated facts: {third.text!r}")

    # A refused turn clears the live referents but not the conversation memory.
    refused = respond(dialogue, "What is the airspeed of a swallow?")
    require(refused.status == "unknown" and dialogue.last_question is None
            and dialogue.last_entity is None,
            "refusal no longer cleared the live referents")
    require(dialogue.last_answered is not None and len(dialogue.shown) == 4
            and dialogue.history[-1]["status"] == "unknown",
            "refusal erased the conversation memory")
    nothing = respond(dialogue, "Tell me more", research_index=index)
    require(nothing.status == "clarify"
            and "Which entity with accepted facts" in nothing.text,
            f"elaboration invented a topic after a refusal: {nothing.text!r}")

    # 'Why?' after the refusal explains the earlier answer and says which one.
    explained = respond(dialogue, "Why?")
    require(explained.text.startswith(
                "Explaining my earlier answer to ‘Who designed the Analytical Engine?’")
            and "Charles Babbage" in explained.text and "Sources: a.txt" in explained.text,
            f"'why' after a refusal did not explain the earlier answer: {explained.text!r}")
    require(explained.intent_hypothesis is not None
            and "earlier_grounded_answer" in explained.intent_hypothesis.context_predicates,
            "'why' after a refusal did not expose its context")
    require(respond(CRMSDialogue(knowledge), "Why?").intent_hypothesis.dialogue_act
            == "uncertain", "an unanchored 'why' gained a context it does not have")

    # Memory is bounded, and only an explicit reset wipes it.
    for _ in range(20):
        respond(dialogue, "lol")
    require(len(dialogue.history) == 12, f"history was not bounded: {len(dialogue.history)}")
    dialogue.clear()
    require(dialogue.last_answered is not None and dialogue.shown,
            "clear() wiped conversation memory that only /reset should wipe")
    dialogue.reset_history()
    require(not dialogue.history and dialogue.last_answered is None and not dialogue.shown,
            "reset_history left memory behind")

    # Persistence: round trip, legacy files, tampering.
    with tempfile.TemporaryDirectory(prefix="crms-history-") as folder:
        root = Path(folder)
        live = CRMSDialogue(knowledge)
        respond(live, "Who designed the Analytical Engine?")
        respond(live, "Tell me more", research_index=index)
        state = root / "dialogue.json"
        live.save(str(state))
        payload = json.loads(state.read_text(encoding="utf-8"))
        require(payload["format_version"] == 12 and payload["shown"]
                and payload["last_answered"]["answer"] == "Charles Babbage"
                and payload["history"][-1]["act"] == "elaboration",
                f"saved state lacked the conversation memory: {payload}")
        restored = CRMSDialogue.load(knowledge, str(state))
        require(restored.shown == live.shown and restored.history == live.history
                and restored.last_answered == live.last_answered,
                "conversation memory did not survive a round trip")
        more = respond(restored, "Tell me more", research_index=index)
        require(more.text.startswith("More about Charles Babbage:")
                and "worked with" in more.text and "born in" not in more.text,
                f"restored dialogue repeated or lost shown facts: {more.text!r}")

        legacy = {key: value for key, value in payload.items()
                  if key not in {"history", "last_answered", "shown",
                                 "pending_dialogue_slot"}}
        legacy["format_version"] = 11
        legacy_intent = legacy.get("last_intent_hypothesis")
        if isinstance(legacy_intent, dict):
            legacy_intent.pop("evidence_refs", None)
            legacy_intent.pop("runtime_route", None)
        state.write_text(json.dumps(legacy), encoding="utf-8")
        old_v11 = CRMSDialogue.load(knowledge, str(state))
        require(old_v11.last_intent_hypothesis is not None
                and old_v11.last_intent_hypothesis.evidence_refs == ()
                and old_v11.last_intent_hypothesis.runtime_route is None,
                "version 11 intent state did not load with legacy defaults")

        legacy["format_version"] = 9
        state.write_text(json.dumps(legacy), encoding="utf-8")
        old = CRMSDialogue.load(knowledge, str(state))
        require(old.history == [] and old.last_answered is None and old.shown == [],
                "a version 9 state did not load with empty conversation memory")

        for field, value in (("history", [{"act": 1, "utterance": "x", "status": "y"}]),
                             ("history", [{"act": "a"}]),
                             ("history", [{"act": "a", "utterance": "x", "status": "y"}] * 13),
                             ("last_answered", {"question": "", "answer": "x"}),
                             ("last_answered", {"question": "q"}),
                             ("shown", "not a list"),
                             ("shown", [1])):
            bad = dict(payload)
            bad[field] = value
            state.write_text(json.dumps(bad), encoding="utf-8")
            try:
                CRMSDialogue.load(knowledge, str(state))
            except ValueError:
                continue
            raise SystemExit(f"tampered {field} was trusted: {value!r}")

        # Terminal: memory persists, and /reset wipes it.
        knowledge_path = root / "knowledge.json"
        knowledge.save(knowledge_path)
        CRMSResearchIndex().save(root / "index.json")
        command = [
            sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(root / "index.json"),
            "--rules", str(root / "rules.json"),
            "--dialogue-state", str(root / "chat-dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        completed = subprocess.run(
            command,
            input=("Who designed the Analytical Engine?\nTell me more\n"
                   "What is the airspeed of a swallow?\nWhy?\n"
                   "/reset\nWhy?\nGoodbye\n"),
            text=True, capture_output=True, check=True, timeout=30)
        out = completed.stdout
        require("About Charles Babbage:" in out
                and "Explaining my earlier answer to ‘Who designed the Analytical Engine?’" in out,
                f"terminal session lost its conversation memory: {out}")
        require(out.count("Explaining my earlier answer") == 1
                and "There is no previous grounded answer to explain yet." in out,
                f"/reset did not wipe the earlier answer: {out}")
        saved = json.loads((root / "chat-dialogue.json").read_text(encoding="utf-8"))
        require(saved["last_answered"] is None and saved["shown"] == [],
                f"/reset state was saved with old memory: {saved}")

    print("grounded answers are remembered apart from live referents: PASS")
    print("'tell me more' pages through cited accepted facts without retrieval: PASS")
    print("a refusal clears referents but not conversation memory: PASS")
    print("'why?' after a refusal explains the earlier answer and names it: PASS")
    print("history is bounded; clear() keeps it and /reset wipes it: PASS")
    print("state version 12 round-trips; versions 11 and 9 load; tampering is rejected: PASS")


if __name__ == "__main__":
    main()
