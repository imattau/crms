"""Seed conversation acts avoid retrieval and preserve content routing."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_conversation import classify_act, respond
from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


class NoRetrievalIndex:
    def document_count(self) -> int:
        return 4

    def search(self, *_args, **_kwargs):
        raise AssertionError("content-free act reached source retrieval")


class ContentDialogue:
    def __init__(self) -> None:
        self.knowledge = SimpleNamespace(_facts={})
        self.last_entity = None
        self.pending_result = None
        self.last_question = None
        self.last_selected_answer = None
        self.source_mentions: list = []
        self.last_intent_hypothesis = None
        self.last_answered = None
        self.pending_binding = None
        self.history: list = []
        self.calls_recorded: list = []
        self.calls: list[str] = []

    def record_turn(self, utterance, act, turn) -> None:
        self.calls_recorded.append((utterance, act))

    def elaborate(self):
        return None

    def turn(self, text: str, *, research_index=None):
        self.calls.append(text)
        return SimpleNamespace(status="answered", text="grounded answer")


def main() -> None:
    require(classify_act("hi there") == "greeting"
            and classify_act("Good morning") == "greeting"
            and classify_act("Tell me more") == "elaboration"
            and classify_act("Goodbye!") == "farewell"
            and classify_act("got it") == "acknowledgement"
            and classify_act("hmm") == "unclassified",
            "seed dialogue acts did not classify expected phrasings")

    dialogue = ContentDialogue()
    index = NoRetrievalIndex()
    greetings = respond(dialogue, "hi there", research_index=index,
                        pending_claims=2)
    require(greetings.status == "social"
            and "0 accepted facts" in greetings.text
            and "4 source documents" in greetings.text
            and "2 claims awaiting review" in greetings.text,
            f"greeting status was incomplete or fabricated: {greetings}")
    for phrase in ("Tell me more", "got it", "thanks", "hmm", "What can you do?"):
        handled = respond(dialogue, phrase, research_index=index)
        require(handled.status != "answered",
                f"content-free act was mistaken for an answer: {phrase}: {handled}")
    require(not dialogue.calls,
            f"content-free turns were delegated to dialogue/retrieval: {dialogue.calls}")

    answer = respond(dialogue, "Who created Python?", research_index=index)
    require(answer.status == "answered" and answer.text == "grounded answer"
            and dialogue.calls == ["Who created Python?"],
            "conversation dispatch changed an ordinary content answer")
    mixed = respond(dialogue, "Hello, Who created Python?",
                    research_index=index)
    require(mixed.status == "answered" and "grounded answer" in mixed.text
            and mixed.text.startswith("Hello.")
            and dialogue.calls[-1] == "Who created Python?",
            "mixed greeting/question did not preserve and answer the content turn")

    # The terminal chat uses the ordinary save/exit path for a farewell.
    with tempfile.TemporaryDirectory(prefix="crms-conversation-acts-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        CRMSKnowledgeBase().save(knowledge_path)
        corpus = CRMSResearchIndex()
        corpus.add_document(
            "bait", "Conversation bait", "Hi there. Tell me more. Goodbye.",
            "conversation.txt")
        corpus.save(index_path)
        script = Path(__file__).resolve().parents[1] / "crms_chat.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--knowledge", str(knowledge_path),
             "--index", str(index_path), "--rules", str(root / "rules.json"),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rule-session", str(root / "session.json")],
            input="hi there\nTell me more\nGoodbye\n",
            text=True, capture_output=True,
            check=True, timeout=20)
        require("CRMS state saved. Goodbye." in completed.stdout
                and (root / "dialogue.json").is_file()
                and "1 source document loaded" in completed.stdout
                and "Which entity or source" in completed.stdout
                and "[Source: Conversation bait" not in completed.stdout,
                f"acts caused junk retrieval or failed to exit: {completed.stdout}")

    print("greeting/status, farewell, acknowledgement, elaboration, help, unclassified: PASS")
    print("content-free turns bypass retrieval; content questions retain existing routing: PASS")
    print("farewell reuses the persistent save-and-exit path: PASS")


if __name__ == "__main__":
    main()
