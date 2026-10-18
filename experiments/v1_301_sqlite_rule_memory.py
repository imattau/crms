"""Exercise normalized SQLite persistence for learned transformation rules.

Run from the project root with:
    python3 experiments/v1_301_sqlite_rule_memory.py
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sqlite3
import sys
import tempfile
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_model import CRMSModel
from crms_knowledge import CRMSKnowledgeBase
from crms_package import (export_model_database, inspect_model_database,
                          install_model_database)


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
        corrupted = root / "corrupted-rules.sqlite"
        shutil.copy2(sqlite_path, corrupted)
        with sqlite3.connect(corrupted) as db:
            db.execute("UPDATE rule_examples SET output_json='[999]' "
                       "WHERE ordinal=0")
        try:
            CRMSModel(corrupted, max_search_expansions=20_000, max_workers=1)
        except ValueError as error:
            require("integrity" in str(error),
                    f"corrupt rule memory failed for an unrelated reason: {error}")
        else:
            raise SystemExit("tampered SQLite rule evidence was accepted")

        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        portable_model = export_model_database(
            root / "model.sqlite", knowledge=knowledge_path, rules=sqlite_path)
        require(set(inspect_model_database(portable_model)) == {"knowledge", "rules"},
                "portable model rejected SQLite-backed rule memory")
        with sqlite3.connect(portable_model) as db:
            packaged_tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            packaged = db.execute(
                "SELECT payload_json FROM learned_memories WHERE kind='rules'"
            ).fetchone()[0]
        require({"model_rule_settings", "model_rule_examples",
                 "model_rule_procedures", "model_rule_artifacts",
                 "knowledge_metadata", "knowledge_payload", "inference_rules",
                 "derived_cases", "positive_facts", "negative_facts"}
                <= packaged_tables,
                "portable model omitted normalized knowledge or rule tables")
        legacy_v2 = root / "legacy-v2.sqlite"
        shutil.copy2(portable_model, legacy_v2)
        with sqlite3.connect(legacy_v2) as db:
            for table in ("knowledge_metadata", "knowledge_payload",
                          "inference_rules", "derived_cases",
                          "positive_facts", "negative_facts",
                          "knowledge_records"):
                db.execute(f"DROP TABLE {table}")
            db.execute("UPDATE model_metadata SET value='2' WHERE key='version'")
            db.execute("PRAGMA user_version=2")
        legacy_memories = inspect_model_database(legacy_v2)
        legacy_installed = install_model_database(
            legacy_v2, root / "legacy-v2-installed")
        require("storage" not in legacy_memories["knowledge"]
                and legacy_memories["rules"].get("storage") == "sqlite"
                and legacy_installed["knowledge"].suffix == ".json"
                and legacy_installed["rules"].suffix == ".sqlite",
                "portable model v2 compatibility path regressed")
        require(instruction in packaged and '"reverse"' in packaged,
                "portable model dropped the learned rule or its procedure")
        corrupted_model = root / "corrupted-model.sqlite"
        shutil.copy2(portable_model, corrupted_model)
        with sqlite3.connect(corrupted_model) as db:
            db.execute("UPDATE model_rule_examples SET output_json='[999]' "
                       "WHERE ordinal=0")
        try:
            inspect_model_database(corrupted_model)
        except ValueError as error:
            require("disagree" in str(error),
                    f"normalized rule corruption failed for an unrelated reason: {error}")
        else:
            raise SystemExit("portable model accepted inconsistent normalized rules")
        installed = install_model_database(portable_model, root / "installed")
        require(installed["rules"].suffix == ".sqlite"
                and installed["knowledge"].suffix == ".sqlite",
                "portable model did not restore knowledge and rules as SQLite memories")
        packaged_restored = CRMSModel(
            installed["rules"], max_search_expansions=20_000, max_workers=1)
        packaged_prediction = packaged_restored.predict(instruction, [4, 1, -3])
        require(packaged_prediction.status == "ok"
                and packaged_prediction.output == [-1, 3, 6],
                "installed portable SQL model lost its learned rule")
        model_chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(portable_model),
             "--dialogue-state", str(root / "model-dialogue.json")],
            input=f"/apply-rule {instruction}|4,1,-3\n/quit\n",
            text=True, capture_output=True, cwd=root, timeout=30)
        model_sidecar = Path(str(portable_model) + ".memories")
        require(model_chat.returncode == 0
                and "CRMS> [-1, 3, 6]" in model_chat.stdout
                and (model_sidecar / "rules.sqlite").is_file()
                and (model_sidecar / "knowledge.sqlite").is_file(),
                f"portable-model chat did not use normalized rules:\n"
                f"{model_chat.stdout}\n{model_chat.stderr}")

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
