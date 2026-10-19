"""Ensure answer feedback can target its evidence after a chat restart.

Objective: persist only the current answer target, separately from the event log.
Setup: temporary SQLite feedback stores and fresh CLI processes.
Metrics: target fidelity, restart recovery, explicit conflict retention, migration.
Failure modes: stale answer attribution, lost evidence, knowledge mutation, or lost events.
Definition of success: feedback after restart attaches to the exact prior answer and leaves
knowledge unchanged; a new user turn clears the prior target.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_feedback import AnswerFeedbackStore
from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def chat_args(root: Path, knowledge: Path) -> list[str]:
    return [
        sys.executable, str(ROOT / "crms_chat.py"),
        "--knowledge", str(knowledge),
        "--feedback-db", str(root / "feedback.sqlite3"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rules", str(root / "rules.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--math", str(root / "math.json"),
        "--math-session", str(root / "math-session.json"),
        "--translations", str(root / "translations.json"),
        "--translation-session", str(root / "translation-session.json"),
        "--index", str(root / "index.sqlite3"),
    ]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-feedback-context-migration-") as folder:
        path = Path(folder) / "feedback.sqlite3"
        store = AnswerFeedbackStore(path)
        refs = [{"kind": "fact", "id": "f1", "subject": "Ada",
                 "relation": "designed", "object": "Engine",
                 "sources": ["book:12"]}]
        store.set_pending("Who designed Engine?", "Ada designed Engine.", refs)
        expected = store.pending()
        require(expected is not None and expected["evidence"] == refs,
                "pending feedback target did not round-trip")
        store.record("wrong", expected["question"], expected["answer"], refs)
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE feedback_context")
            connection.execute("DROP TABLE ledger_event")
            connection.execute("DROP TABLE item_ledger")
            connection.execute("PRAGMA user_version=1")
        migrated = AnswerFeedbackStore(path)
        require(migrated.pending() is None
                and len(migrated.events()) == 1,
                "v1 feedback migration discarded events or invented context")
        with sqlite3.connect(path) as connection:
            require(connection.execute("PRAGMA user_version").fetchone()[0] == 3,
                    "feedback database schema version was not upgraded")

    with tempfile.TemporaryDirectory(prefix="crms-feedback-context-restart-") as folder:
        root = Path(folder)
        knowledge = CRMSKnowledgeBase()
        knowledge.add_fact("Ada Lovelace", "designed", "Engine", "book:12")
        knowledge.teach_question(
            "Who designed Engine?", relation="designed", answer_field="subject",
            bound_entity="Engine", answer="Ada Lovelace")
        knowledge_path = root / "knowledge.json"
        knowledge.save(knowledge_path)
        args = chat_args(root, knowledge_path)

        first = subprocess.run(
            args, input="Who designed Engine?\n/quit\n", text=True,
            capture_output=True, check=True, timeout=30)
        require("Ada Lovelace designed Engine." in first.stdout,
                f"first session did not answer the test question: {first.stdout}")
        store = AnswerFeedbackStore(root / "feedback.sqlite3")
        saved = store.pending()
        require(saved is not None
                and saved["question"] == "Who designed Engine?"
                and "Ada Lovelace" in saved["answer"]
                and any(item.get("sources") == ["book:12"]
                        for item in saved["evidence"]),
                f"answer context was not saved with its source: {saved}")

        second = subprocess.run(
            args, input="/wrong\n/feedback\n/quit\n", text=True,
            capture_output=True, check=True, timeout=30)
        require("Restored the last evidence-backed answer" in second.stdout
                and "I recorded your feedback against" in second.stdout
                and "Ada Lovelace — designed → Engine" in second.stdout,
                f"feedback after restart lost its answer attribution: {second.stdout}")
        require(len(store.events()) == 1
                and store.events()[0]["verdict"] == "wrong",
                "wrong feedback event was not retained")
        unchanged = CRMSKnowledgeBase.load(knowledge_path)
        require(len(unchanged.facts()) == 1 and not unchanged.negative_facts(),
                "persisted wrong feedback changed knowledge automatically")

        third = subprocess.run(
            args, input="/right\n/feedback\n/quit\n", text=True,
            capture_output=True, check=True, timeout=30)
        require("conflicting feedback for review" in third.stdout
                and [event["verdict"] for event in store.events()]
                    == ["wrong", "right"],
                "opposite feedback after restart was not preserved as a conflict")

        fourth = subprocess.run(
            args, input="Who invented an unsupported object?\n/wrong\n/quit\n",
            text=True, capture_output=True, check=True, timeout=30)
        require("I don't have a recent evidence-backed answer" in fourth.stdout,
                "a new unsupported turn left the previous feedback target active")
        require(store.pending() is None,
                "new user turn did not clear the previous feedback target")

    print("feedback context survives restart with exact evidence attribution: PASS")
    print("feedback schema v1 migrates without losing its event history: PASS")
    print("opposite post-restart feedback remains a reviewable conflict: PASS")
    print("new unsupported turn clears stale answer feedback context: PASS")
    print("feedback alone does not mutate accepted facts: PASS")


if __name__ == "__main__":
    main()
