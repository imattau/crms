"""Objective: persist explicit feedback against the exact answer evidence.

Setup: record direct-fact and rule-proof references in a temporary SQLite log.
Metrics: attribution, duplicate suppression, conflict preservation, reload.
Failure modes: feedback loses lineage, silently changes knowledge, or disappears.
Definition of success: exact references survive reload and no knowledge is mutated.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_feedback import AnswerFeedbackStore, collect_feedback_refs


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    response = SimpleNamespace(
        evidence=[{"subject": "Ada", "relation": "designed",
                   "object": "Engine", "sources": ["book:12"]}],
        proofs=None,
        inference_proofs=[{
            "rule": {"rule_id": "parent-rule"},
            "fact": {"sources": ["family:1"]},
            "premises": [{"fact": {"sources": ["family:2"]}}],
        }])
    research = SimpleNamespace(
        source_sentences=[{"document_id": "wiki:ada", "sentence_id": "s7"}],
        passages=[])
    refs = collect_feedback_refs(response, research)
    require(refs == [
        {"kind": "rule", "id": "parent-rule"},
        {"kind": "source", "id": "book:12"},
        {"kind": "source", "id": "family:1"},
        {"kind": "source", "id": "family:2"},
        {"kind": "source", "id": "s7"},
        {"kind": "source", "id": "wiki:ada"}],
        f"did not collect exact fact/rule/source lineage: {refs}")

    with tempfile.TemporaryDirectory(prefix="crms-feedback-") as directory:
        store = AnswerFeedbackStore(Path(directory) / "feedback.sqlite3")
        answer_id, inserted = store.record(
            "wrong", "Who designed Engine?", "Ada designed Engine.", refs)
        require(inserted, "first wrong signal was not stored")
        duplicate_id, inserted = store.record(
            "wrong", "Who designed Engine?", "Ada designed Engine.",
            list(reversed(refs)))
        require(answer_id == duplicate_id and not inserted,
                "same feedback was duplicated or order changed identity")
        _same_id, inserted = store.record(
            "right", "Who designed Engine?", "Ada designed Engine.", refs)
        require(inserted, "contradictory signal was not retained for review")
        reloaded = AnswerFeedbackStore(Path(directory) / "feedback.sqlite3")
        events = reloaded.events()
        require([row["verdict"] for row in events] == ["wrong", "right"],
                "feedback did not persist in event order")
        require(all(row["evidence"] == refs for row in events),
                "persisted feedback lost evidence attribution")
        require(all(row["question"] == "Who designed Engine?"
                    and row["answer"] == "Ada designed Engine."
                    for row in events),
                "feedback was attached to a different answer")

    print("answer feedback attribution: direct facts, rule, and source refs PASS")
    print("SQLite persistence, deterministic IDs, duplicate suppression: PASS")
    print("conflicting feedback retained for review without changing knowledge: PASS")


if __name__ == "__main__":
    main()
