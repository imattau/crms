"""Verify failed knowledge imports preserve the prior SQLite fact snapshot.

Run from the project root with:
    python3 experiments/v1_300_sqlite_load_rollback.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-sqlite-rollback-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        fact_db = root / "facts.sqlite"

        baseline = CRMSKnowledgeBase()
        baseline.add_fact("Ada", "designed", "Engine", "source:baseline")
        baseline.save(knowledge_path)
        loaded = CRMSKnowledgeBase.load(knowledge_path, fact_db=fact_db)
        loaded.close()

        invalid_payload = {
            "format_version": CRMSKnowledgeBase.FORMAT_VERSION,
            "facts": [{"subject": "Grace", "relation": "built",
                       "object": "Compiler", "sources": ["source:replacement"],
                       "qualifiers": []}],
            "negative_facts": [],
            "derived_cases": [{"conclusion": {"subject": "X",
                                                  "relation": "r",
                                                  "object": "Y"},
                               "proofs": [], "lineage": {},
                               "practice_count": 1, "retrieval_count": 0}],
        }
        knowledge_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
        try:
            CRMSKnowledgeBase.load(knowledge_path, fact_db=fact_db)
        except ValueError:
            pass
        else:
            raise SystemExit("malformed derived-case payload unexpectedly loaded")

        with sqlite3.connect(fact_db) as db:
            rows = [json.loads(row[0]) for row in db.execute(
                "SELECT payload_json FROM positive_facts")]
        require(rows == [{"subject": "Ada", "relation": "designed",
                          "object": "Engine", "sources": ["source:baseline"],
                          "qualifiers": []}],
                f"failed semantic import replaced the baseline facts: {rows}")

        knowledge_path.write_text("{ invalid json", encoding="utf-8")
        try:
            CRMSKnowledgeBase.load(knowledge_path, fact_db=fact_db)
        except (ValueError, json.JSONDecodeError):
            pass
        else:
            raise SystemExit("invalid JSON unexpectedly loaded")
        require(fact_db.is_file(), "failed parse deleted the existing fact database")
        with sqlite3.connect(fact_db) as db:
            rows_after_parse_error = [json.loads(row[0]) for row in db.execute(
                "SELECT payload_json FROM positive_facts")]
        require(rows_after_parse_error == rows,
                "failed parse changed the baseline fact snapshot")

    print("SQLite knowledge-load rollback diagnostic: PASS")
    print("failed semantic import did not replace the prior fact snapshot")


if __name__ == "__main__":
    main()
