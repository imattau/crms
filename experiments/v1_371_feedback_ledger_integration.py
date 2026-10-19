"""Connect explicit answer feedback to a cautious, per-user review ledger."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_feedback import AnswerFeedbackStore


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-feedback-ledger-") as folder:
        path = Path(folder) / "feedback.sqlite3"
        store = AnswerFeedbackStore(path)
        refs = [
            {"kind": "fact", "id": "fact-1", "subject": "Ada",
             "relation": "designed", "object": "Engine"},
            {"kind": "rule", "id": "learned-rule"},
            {"kind": "rule", "id": "teacher-rule"},
        ]

        _answer_id, inserted = store.record(
            "right", "Who designed the Engine?", "Ada",
            refs, auto_learned_rule_ids={"learned-rule"})
        require(inserted, "first feedback event was not recorded")
        require(abs(store.ledger_weight("fact", "fact-1") - 1.0) < 1e-12,
                "direct fact feedback altered a protected fact weight")
        require(abs(store.ledger_weight("rule", "learned-rule") - 0.32) < 1e-12,
                "validated learned rule did not receive the feedback update")
        require(store.ledger_item("rule", "teacher-rule")["protected"],
                "teacher-supplied rule was not protected")

        _duplicate_id, duplicate = store.record(
            "right", "Who designed the Engine?", "Ada",
            refs, auto_learned_rule_ids={"learned-rule"})
        require(not duplicate
                and store.ledger_item("rule", "learned-rule")["hits"] == 1,
                "duplicate feedback changed the ledger twice")

        _wrong_id, inserted = store.record(
            "wrong", "Who designed the Engine?", "Ada", refs,
            auto_learned_rule_ids={"learned-rule"})
        require(inserted and store.ledger_item(
            "rule", "learned-rule")["misses"] == 1,
            "opposite feedback was not retained as a separate review signal")
        require(store.ledger_item("rule", "learned-rule")["weight"] < 0.32,
                "negative feedback did not lower the review weight")
        require(store.ledger_item("rule", "teacher-rule")["weight"] == 1.0,
                "negative feedback altered a protected teacher rule")

        # Simulate a v2 database upgrade while retaining its event history and
        # pending context; the v3 constructor must add only the ledger tables.
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TABLE ledger_event")
            connection.execute("DROP TABLE item_ledger")
            connection.execute("PRAGMA user_version=2")
        upgraded = AnswerFeedbackStore(path)
        require(len(upgraded.events()) == 2,
                "schema migration lost answer feedback history")
        require(upgraded.ledger_item("rule", "learned-rule") is None,
                "schema migration unexpectedly invented prior ledger evidence")

    print("facts and teacher rules remain protected: PASS")
    print("validated learned rules receive deterministic review updates: PASS")
    print("duplicate feedback is inert; opposite feedback is retained: PASS")
    print("v2 migration preserves event history without inventing ledger state: PASS")


if __name__ == "__main__":
    main()
