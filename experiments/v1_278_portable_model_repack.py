"""Check that learned state can be repacked into one portable model file."""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath
from crms_package import (
    inspect_model_database, install_model_database, model_database_research_stats,
    repack_model_database,
)
from crms_research import CRMSSQLiteResearchIndex
from crms_translation import CRMSTranslation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    source_model = PROJECT / "data" / "crms_project_model_academic_expanded.sqlite"
    require(source_model.is_file(), f"portable source model is missing: {source_model}")

    with tempfile.TemporaryDirectory(prefix="crms-model-repack-test-") as folder:
        root = Path(folder)
        input_model = root / "source.sqlite"
        shutil.copy2(source_model, input_model)
        memory_dir = root / "source.sqlite.memories"
        install_model_database(input_model, memory_dir)
        marker = hashlib.sha256(input_model.read_bytes()).hexdigest()
        (memory_dir / ".model.sha256").write_text(marker + "\n", encoding="ascii")

        index = CRMSSQLiteResearchIndex(memory_dir / "research.sqlite")
        index.add_document(
            "repack:probe", "Repack probe source", "The repack probe is a widget.",
            "https://example.test/repack-probe")
        hit = next(hit for hit in index.search("repack probe widget", limit=5)
                   if hit.document_id == "repack:probe")
        citation = index.citation(hit)
        index.close()

        knowledge = CRMSKnowledgeBase.load(memory_dir / "knowledge.json")
        knowledge.add_fact("repack probe", "is-a", "widget", citation)
        knowledge.save(memory_dir / "knowledge.json")

        math = CRMSMath()
        math.teach("What is 2 plus 3?", "5")
        math.teach("What is 4 plus 6?", "10")
        math.save(memory_dir / "math.json")

        translations = CRMSTranslation()
        translations.teach(
            "English", "French", "formal", "Hello, {name}.",
            "Bonjour, {name}.",
            [("Hello, Ada.", "Bonjour, Ada."),
             ("Hello, Malik.", "Bonjour, Malik.")])
        translations.save(memory_dir / "translations.json")

        output_model = root / "repacked.sqlite"
        repack = subprocess.run(
            [sys.executable, str(PROJECT / "crms_package.py"), "repack",
             str(input_model), "--memory-dir", str(memory_dir),
             "--output", str(output_model)],
            text=True, capture_output=True, check=True, timeout=90)
        require("Created repacked portable CRMS model database:" in repack.stdout,
                f"repack command did not report success: {repack.stdout}")
        memories = inspect_model_database(output_model)
        require({"knowledge", "rules", "math", "translations"} <= memories.keys(),
                f"repacked file omitted learned-memory types: {memories}")
        stats = model_database_research_stats(output_model)
        require(stats is not None and stats["documents"] == 2934,
                f"repack did not preserve and extend the source corpus: {stats}")
        readback = root / "readback"
        install_model_database(output_model, readback)
        require(CRMSKnowledgeBase.load(
                    readback / "knowledge.json").ask("What is the repack probe?").answer
                == "widget",
                "repacked fact memory did not retain the new reviewed fact")
        math_result = CRMSMath.load(readback / "math.json").ask(
            "What is 10 plus 11?")
        require(math_result is not None and str(math_result.value) == "21",
                "repacked math memory did not retain the held-out addition")
        translated = CRMSTranslation.load(readback / "translations.json").translate(
            "Translate from English to French in formal register: Hello, Rowan.")
        require(translated is not None and translated.output == "Bonjour, Rowan.",
                "repacked translation memory did not retain the held-out name")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(output_model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        run = subprocess.run(
            command,
            input=("What is the repack probe?\n"
                   "What is 10 plus 11?\n"
                   "Translate from English to French in formal register: Hello, Rowan.\n"
                   "/quit\n"),
            text=True, capture_output=True, check=True, timeout=90)
        require("Loaded portable learned model:" in run.stdout
                and "widget" in run.stdout
                and "21" in run.stdout
                and "Bonjour, Rowan." in run.stdout,
                f"chat could not use repacked fact, math, and translation state: {run.stdout}")

        try:
            repack_model_database(input_model, memory_dir, output_model)
        except FileExistsError:
            pass
        else:
            raise SystemExit("repack unexpectedly replaced an existing output model")
        try:
            repack_model_database(input_model, memory_dir, input_model)
        except ValueError as error:
            require("must differ" in str(error),
                    f"in-place repack failed for an unexpected reason: {error}")
        else:
            raise SystemExit("repack unexpectedly overwrote its input model")

    print("portable model repack diagnostic: PASS")


if __name__ == "__main__":
    main()
