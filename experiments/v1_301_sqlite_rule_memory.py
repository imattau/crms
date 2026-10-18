"""Exercise normalized SQLite persistence for learned transformation rules.

Run from the project root with:
    python3 experiments/v1_301_sqlite_rule_memory.py
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_model import CRMSModel
from crms_knowledge import CRMSKnowledgeBase
from crms_package import export_model_database, inspect_model_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-rule-sqlite-") as folder:
        root = Path(folder)
        sqlite_path = root / "rules.sqlite"
        json_path = root / "rules.json"
        instruction = "increase each value by 2 before reversing it"
        examples = [
            ([1, 4, -2], [0, 6, 3]),
            ([5, -3, 8], [10, -1, 7]),
            ([0, 6, -7], [-5, 8, 2]),
            ([9, 2, 1], [3, 4, 11]),
        ]
        trained = CRMSModel(max_search_expansions=20_000, max_workers=1)
        taught = trained.teach(instruction, examples)
        require(taught.status == "learned",
                f"grounded rule failed to learn: {taught}")
        trained.save(sqlite_path)

        with sqlite3.connect(sqlite_path) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("rule_examples", "rule_procedures", "rule_artifacts")
            }
        require(tables == {"rule_store_settings", "rule_examples",
                           "rule_procedures", "rule_artifacts"},
                f"rule memory was not stored in the normalized schema: {tables}")
        require(counts["rule_examples"] == len(examples)
                and counts["rule_procedures"] == 1,
                f"rule training evidence was not persisted row-by-row: {counts}")

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        portable_model = export_model_database(
            root / "model.sqlite", knowledge=knowledge_path, rules=sqlite_path)
        require(set(inspect_model_database(portable_model)) == {"knowledge", "rules"},
                "portable model rejected SQLite-backed rule memory")
        with sqlite3.connect(portable_model) as db:
            packaged = db.execute(
                "SELECT payload_json FROM learned_memories WHERE kind='rules'"
            ).fetchone()[0]
        require(instruction in packaged and '"reverse"' in packaged,
                "portable model dropped the learned rule or its procedure")

        restored = CRMSModel(
            sqlite_path, max_search_expansions=20_000, max_workers=1)
        before = trained.predict(instruction, [4, 1, -3])
        after = restored.predict(instruction, [4, 1, -3])
        require(after.status == before.status == "ok"
                and after.output == before.output == [-1, 3, 6],
                f"SQLite reload changed learned rule behavior: {before} / {after}")
        restored.save(json_path)
        json_restored = CRMSModel(
            json_path, max_search_expansions=20_000, max_workers=1)
        round_trip = json_restored.predict(instruction, [4, 1, -3])
        require(round_trip.status == "ok" and round_trip.output == after.output,
                f"SQLite to JSON export changed learned rule behavior: {round_trip}")

        chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--rules", str(sqlite_path),
             "--dialogue-state", str(root / "dialogue.json")],
            input=f"/apply-rule {instruction}|4,1,-3\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        require(chat.returncode == 0 and "CRMS> [-1, 3, 6]" in chat.stdout,
                f"chat did not use SQLite-backed learned rules:\n"
                f"{chat.stdout}\n{chat.stderr}")

    print("SQLite learned-rule memory diagnostic: PASS")
    print("examples and accepted procedure use separate indexed rows; "
          "SQLite and JSON reloads preserve prediction behavior")


if __name__ == "__main__":
    main()
