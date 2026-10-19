"""Round-trip versioned contextual dialogue frames in portable model SQLite."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue_intent import (empty_dialogue_intent_memory,
                                  validate_dialogue_intent_memory)
from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import (export_model_database, inspect_model_database,
                          install_model_database,
                          model_database_dialogue_intent_memory,
                          repack_model_database)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def sample_memory() -> dict:
    payload = empty_dialogue_intent_memory()
    payload["builtin_policy"].append({
        "policy_id": "greeting-seed-v1",
        "dialogue_act": "greeting",
        "task_intent": "social-contact",
        "surface_patterns": ["hello", "hi there"],
        "context_predicates": ["conversation_opening"],
        "predecessor_act": None,
        "runtime_route": "greeting",
    })
    payload["learned_frames"].append({
        "frame_id": "clarification-choice-v1",
        "dialogue_act": "answer-clarification",
        "task_intent": "resolve-ambiguity",
        "surface_patterns": ["the second option"],
        "context_predicates": ["pending_candidate_choice"],
        "predecessor_act": "clarification-request",
        "runtime_route": None,
        "source_citations": ["taskmaster:dialogue-a#turn=4",
                             "taskmaster:dialogue-b#turn=8"],
        "status": "heldout-validated",
        "validation": {
            "status": "heldout-validated",
            "train_conversation_ids": ["dialogue-a", "dialogue-c"],
            "holdout_conversation_ids": ["dialogue-b"],
            "reviewer_count": 2,
            "metrics": {"intent_accuracy": 0.9, "abstention_rate": 0.1},
        },
    })
    return payload


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-dialogue-memory-") as temp:
        root = Path(temp)
        knowledge_path, rules_path = root / "knowledge.json", root / "rules.json"
        CRMSKnowledgeBase().save(knowledge_path)
        CRMSModel().save(rules_path)
        memory_path = root / "dialogue.json"
        memory = sample_memory()
        memory_path.write_text(json.dumps(memory, ensure_ascii=False),
                               encoding="utf-8")

        database = export_model_database(
            root / "model.sqlite", knowledge=knowledge_path, rules=rules_path,
            dialogue=memory_path)
        inspected = inspect_model_database(database)
        require(set(inspected) == {"knowledge", "rules", "dialogue"},
                f"dialogue memory missing from portable model: {inspected}")
        embedded = model_database_dialogue_intent_memory(database)
        require(embedded == validate_dialogue_intent_memory(memory)
                and embedded["learned_frames"][0]["status"]
                == "heldout-validated"
                and embedded["learned_frames"][0]["validation"]
                ["train_conversation_ids"] == ["dialogue-a", "dialogue-c"],
                "portable model changed contextual frame or validation metadata")

        installed = install_model_database(database, root / "installed")
        require("dialogue" in installed
                and json.loads(installed["dialogue"].read_text(encoding="utf-8"))
                == embedded,
                "model installation did not restore the dialogue memory")

        runtime = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1]
                                 / "crms_chat.py"),
             "--model-db", str(database),
             "--dialogue-state", str(root / "dialogue-state.json")],
            input="/quit\n", text=True, capture_output=True,
            cwd=root, timeout=30)
        sidecar_dialogue = Path(str(database) + ".memories") / "dialogue.json"
        require(runtime.returncode == 0 and sidecar_dialogue.is_file()
                and "Loaded portable learned model:" in runtime.stdout,
                "chat startup did not install the packaged dialogue memory: "
                f"{runtime.stdout}\n{runtime.stderr}")

        repacked = repack_model_database(
            database, root / "installed", root / "repacked.sqlite")
        require(model_database_dialogue_intent_memory(repacked) == embedded,
                "model repacking lost the dialogue memory")

        invalid = sample_memory()
        invalid["learned_frames"][0]["validation"][
            "holdout_conversation_ids"] = ["dialogue-a"]
        try:
            validate_dialogue_intent_memory(invalid)
        except ValueError as error:
            require("split leakage" in str(error),
                    f"unexpected leakage validation error: {error}")
        else:
            raise SystemExit("dialogue memory accepted overlapping train/holdout IDs")

        invalid = sample_memory()
        invalid["learned_frames"][0]["context_predicates"] = ["free_form_guess"]
        try:
            validate_dialogue_intent_memory(invalid)
        except ValueError as error:
            require("unknown context predicate" in str(error),
                    f"unexpected context validation error: {error}")
        else:
            raise SystemExit("dialogue memory accepted an unknown context predicate")

        invalid = sample_memory()
        invalid["builtin_policy"][0]["runtime_route"] = "farewell"
        try:
            validate_dialogue_intent_memory(invalid)
        except ValueError as error:
            require("conflicts with its runtime route" in str(error),
                    f"unexpected route validation error: {error}")
        else:
            raise SystemExit("dialogue memory accepted an inconsistent route")

        legacy = export_model_database(
            root / "without-dialogue.sqlite", knowledge=knowledge_path,
            rules=rules_path)
        require(model_database_dialogue_intent_memory(legacy) is None,
                "dialogue memory must remain optional for existing model workflows")

        # Simulate the immediately previous model container, which has the
        # normalized knowledge tables but no dialogue memory kind.
        v4 = root / "model-v4.sqlite"
        shutil.copyfile(legacy, v4)
        with sqlite3.connect(v4) as db:
            db.execute("UPDATE model_metadata SET value='4' WHERE key='version'")
            db.execute("PRAGMA user_version=4")
        require(set(inspect_model_database(v4)) == {"knowledge", "rules"},
                "version-4 portable model compatibility regressed")
        invalid_v4 = root / "invalid-v4-dialogue.sqlite"
        shutil.copyfile(v4, invalid_v4)
        serialized = json.dumps(memory, ensure_ascii=False, separators=(",", ":"))
        with sqlite3.connect(invalid_v4) as db:
            db.execute("INSERT INTO learned_memories VALUES (?,?,?,?)", (
                "dialogue", serialized,
                hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                len(serialized.encode("utf-8"))))
        try:
            inspect_model_database(invalid_v4)
        except ValueError as error:
            require("unknown memory type" in str(error),
                    f"unexpected legacy memory error: {error}")
        else:
            raise SystemExit("version-4 model accepted the version-5 dialogue memory")

    print("versioned dialogue intent memory exports and validates in SQLite: PASS")
    print("held-out metadata survives install, chat startup, and repack: PASS")
    print("train/holdout leakage and unknown context predicates are rejected: PASS")
    print("legacy models without dialogue memory remain supported: PASS")


if __name__ == "__main__":
    main()
