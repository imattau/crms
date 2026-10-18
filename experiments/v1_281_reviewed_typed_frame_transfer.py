"""Prove reviewed typed-source examples license offline question transfer."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_model import CRMSModel
from crms_package import (
    export_model_database, inspect_model_database,
    model_database_research_stats,
)
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-reviewed-typed-frame-") as temp:
        root = Path(temp)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        for document_id, title, city, article in (
                ("seine", "Seine", "Paris", "The Seine"),
                ("thames", "Thames", "London", "The Thames"),
                ("nacre", "Nacre River", "Nacre City", "The Nacre River")):
            index.add_document(
                document_id, title,
                f"{article} flows through {city}. {article} is a river.",
                f"fixture://{document_id}")
        index.close()

        state = root / "state"
        state.mkdir()
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(state / "knowledge.json"),
            "--dialogue-state", str(state / "dialogue.json"),
            "--candidate-session", str(state / "candidates.json"),
            "--rule-session", str(state / "rules.json"),
            "--math", str(state / "math.json"),
            "--translations", str(state / "translations.json"),
        ]
        questions = "".join(
            f"Which river flows through {city}?\n"
            for city in ("Paris", "London", "Nacre City"))
        proposed = subprocess.run(
            command, input=questions + "/quit\n", text=True,
            capture_output=True, check=False, timeout=30)
        require(proposed.returncode == 0,
                f"source proposal chat failed: {proposed.stderr}\n{proposed.stdout}")
        require(proposed.stdout.count("Review candidate ") == 6,
                f"expected relation and class claims for all three sources: {proposed.stdout}")

        accepted = subprocess.run(
            command,
            input="accept candidate 1\n" * 6 + "/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(accepted.returncode == 0,
                f"source acceptance chat failed: {accepted.stderr}\n{accepted.stdout}")
        require(accepted.stdout.count("Accepted positive fact:") == 6,
                f"not all reviewed relation and class facts were stored: {accepted.stdout}")

        knowledge = CRMSKnowledgeBase.load(state / "knowledge.json")
        try:
            answer = knowledge.ask("What river flows through Nacre City?")
            require(answer.status == "answered"
                    and answer.answer == "The Nacre River",
                    "the reviewed frame did not transfer to an unseen entity "
                    f"without a research index: {answer}")
            relations = {item["relation"] for item in answer.evidence or []}
            require(relations == {"flows through", "is-a"},
                    f"offline answer lacks explicit relation and type proof: {relations}")
            frame_count = sum(
                len(examples) for (relation_repr, answer_field, _prefix, _suffix),
                examples in knowledge._question_examples.items()
                if relation_repr == '["flows", "through"]'
                and answer_field == "subject")
            require(frame_count >= 3,
                    f"accepted typed question examples were not retained: {frame_count}")
        finally:
            knowledge.close()

        empty_index_path = root / "empty-index.sqlite"
        CRMSSQLiteResearchIndex(empty_index_path).close()
        offline_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(state / "knowledge.json"),
            "--index", str(empty_index_path),
            "--dialogue-state", str(state / "offline-dialogue.json"),
            "--candidate-session", str(state / "offline-candidates.json"),
            "--rule-session", str(state / "offline-rules.json"),
            "--math", str(state / "offline-math.json"),
            "--translations", str(state / "offline-translations.json"),
        ]
        offline_chat = subprocess.run(
            offline_command, input="What river flows through Nacre City?\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(offline_chat.returncode == 0,
                f"offline chat failed: {offline_chat.stderr}\n{offline_chat.stdout}")
        require("The Nacre River flows through Nacre City." in offline_chat.stdout
                and "I couldn't find source sentences" not in offline_chat.stdout,
                f"question frame did not answer in terminal chat without corpus access: {offline_chat.stdout}")

        rules_path = state / "rules.json"
        CRMSModel(memory_path=rules_path).save()
        portable_model = root / "crms-reviewed-knowledge.sqlite"
        export_model_database(
            portable_model, knowledge=state / "knowledge.json",
            rules=rules_path, research_index=index_path)
        memory_manifest = inspect_model_database(portable_model)
        source_stats = model_database_research_stats(portable_model)
        require("knowledge" in memory_manifest and source_stats is not None
                and source_stats["documents"] == 3,
                "portable model did not contain learned facts and source text")
        portable_chat = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--model-db", str(portable_model),
             "--dialogue-state", str(state / "portable-dialogue.json"),
             "--candidate-session", str(state / "portable-candidates.json"),
             "--rule-session", str(state / "portable-rule-session.json"),
             "--math-session", str(state / "portable-math-session.json"),
             "--translation-session", str(state / "portable-translation-session.json")],
            input="What river flows through Nacre City?\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(portable_chat.returncode == 0
                and "The Nacre River flows through Nacre City."
                    in portable_chat.stdout,
                f"portable SQLite model did not preserve offline QA "
                f"(exit={portable_chat.returncode}): {portable_chat.stdout}\n"
                f"{portable_chat.stderr}")

    print("reviewed typed relation frame transfer without source index: PASS")


if __name__ == "__main__":
    main()
