"""Check canonical SQLite knowledge storage and chat use.

Run from the project root with:
    python3 experiments/v1_302_sqlite_knowledge_memory.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase, SQLiteFactMap
from crms_model import CRMSModel
from crms_package import export_model_database, inspect_model_database, install_model_database


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-knowledge-sqlite-") as folder:
        root = Path(folder)
        database = root / "knowledge.sqlite"
        kb = CRMSKnowledgeBase()
        kb.add_fact("Ada", "designed", "Engine", "paper:ada")
        kb.add_fact("Ada", "designed", "Engine", "archive:engine")
        kb.add_fact("Grace", "designed", "Compiler", "paper:grace")
        kb.teach_question("Who designed Engine?", relation="designed",
                          answer_field="subject", bound_entity="Engine",
                          answer="Ada")
        kb.teach_question("Who designed Compiler?", relation="designed",
                          answer_field="subject", bound_entity="Compiler",
                          answer="Grace")
        kb.add_fact("Ann", "parent", "Bob", "family:ann-bob")
        kb.add_fact("Bob", "parent", "Cara", "family:bob-cara")
        kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
        practiced = kb.practice_relation("Ann", "ancestor", "Cara")
        require(practiced.status == "answered" and kb.derived_cases(),
                "proof-backed derived case was not prepared")
        kb.add_negative_fact("Bob", "parent", "Dan", "family:negative")
        kb.save(database)
        kb.close()

        with sqlite3.connect(database) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            fact_count = db.execute("SELECT count(*) FROM positive_facts").fetchone()[0]
            source_row = db.execute(
                "SELECT payload_json FROM positive_facts "
                "WHERE subject_key='[\"ada\"]' "
                "AND relation_key='[\"designed\"]' "
                "AND object_key='[\"engine\"]'").fetchone()
        require({"knowledge_metadata", "knowledge_payload", "inference_rules",
                 "derived_cases", "positive_facts", "negative_facts"} <= tables,
                f"knowledge database lacks typed SQL tables: {tables}")
        require(fact_count == 4 and source_row is not None
                and {"paper:ada", "archive:engine"}
                <= set(json.loads(source_row[0])["sources"]),
                "fact values or evidence provenance were lost from SQL rows")

        restored = CRMSKnowledgeBase.load(database)
        require(isinstance(restored._facts, SQLiteFactMap)
                and restored.ask("Who designed Engine?").answer == "Ada"
                and restored.infer_relation(
                    "Ann", "ancestor", "Cara").status == "answered"
                and restored.retrieve_derived_case(
                    "Ann", "ancestor", "Cara") is not None
                and any(fact.object == "Dan"
                        for fact in restored.negative_facts()),
                "SQLite reload lost language frames, proof reasoning, or polarity")
        restored.add_fact("Iris", "designed", "Rotor", "paper:iris")
        restored.save(database)
        restored.close()

        reloaded = CRMSKnowledgeBase.load(database)
        require(reloaded.ask("Who designed Rotor?").answer == "Iris"
                and any(fact.subject == "Iris" for fact in reloaded.facts())
                and reloaded.ask("Who designed Engine?").answer == "Ada",
                "same-file SQL save did not persist facts and preserve learned frames")
        json_export = root / "knowledge.json"
        reloaded.save(json_export)
        reloaded.close()
        json_roundtrip = CRMSKnowledgeBase.load(json_export)
        require(json_roundtrip.ask("Who designed Engine?").answer == "Ada"
                and json_roundtrip.infer_relation(
                    "Ann", "ancestor", "Cara").status == "answered",
                "SQLite-to-JSON export changed question or proof behavior")
        json_roundtrip.close()

        rules_path = root / "rules.json"
        CRMSModel().save(rules_path)
        portable_model = export_model_database(
            root / "portable.sqlite", knowledge=database, rules=rules_path)
        require(set(inspect_model_database(portable_model)) == {"knowledge", "rules"},
                "portable model rejected a canonical SQLite knowledge source")
        installed = install_model_database(portable_model, root / "installed")
        installed_kb = CRMSKnowledgeBase.load(installed["knowledge"])
        require(installed["knowledge"].suffix == ".sqlite"
                and installed_kb.ask("Who designed Engine?").answer == "Ada",
                "portable model lost SQLite-backed knowledge during installation")
        installed_kb.close()
        portable_chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(portable_model),
             "--dialogue-state", str(root / "portable-dialogue.json")],
            input="Who designed Engine?\n/quit\n", text=True,
            capture_output=True, cwd=root, timeout=30)
        require(portable_chat.returncode == 0 and "Ada" in portable_chat.stdout,
                f"portable model chat lost SQLite knowledge:\n"
                f"{portable_chat.stdout}\n{portable_chat.stderr}")

        chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(database),
             "--dialogue-state", str(root / "dialogue.json")],
            input="Who designed Engine?\n/quit\n", text=True,
            capture_output=True, cwd=root, timeout=30)
        require(chat.returncode == 0 and "Ada" in chat.stdout,
                f"chat could not answer from SQLite knowledge:\n"
                f"{chat.stdout}\n{chat.stderr}")

    print("SQLite canonical knowledge-memory diagnostic: PASS")
    print("indexed facts, multi-source provenance, language frames, negatives, "
          "derived proofs, update/reload, JSON export, and chat use: PASS")


if __name__ == "__main__":
    main()
