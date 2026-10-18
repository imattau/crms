"""Check category-language routes on the expanded portable corpus model."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    model = PROJECT / "data" / "crms_project_model_academic_expanded.sqlite"
    require(model.is_file(), f"expanded portable corpus model is missing: {model}")
    with sqlite3.connect(f"file:{model.resolve()}?mode=ro", uri=True) as db:
        count = db.execute("SELECT count(*) FROM research_documents").fetchone()[0]
    require(count == 2933, f"expanded model should contain 2,933 records; found {count}")

    with tempfile.TemporaryDirectory(prefix="crms-category-chat-") as folder:
        root = Path(folder)
        scratch_model = root / "model.sqlite"
        shutil.copy2(model, scratch_model)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(scratch_model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
        ]
        questions = [
            "Which papers discuss mathematical logic?",
            "Which papers discuss number theory?",
            "Which papers discuss programming languages?",
            "Which papers discuss formal languages?",
            "Which papers discuss computational complexity?",
            "What is the latest research in computational complexity?",
            "What is 2 + 3?",
        ]
        run = subprocess.run(
            command, input="\n".join(questions + ["/quit", ""]),
            text=True, capture_output=True, check=True, timeout=90)
        output = run.stdout
        expected = (
            "Papers in the arXiv Logic category (math.LO)",
            "The Characterization of Finite Elasticities",
            "Papers in the arXiv Number Theory category (math.NT)",
            "Papers in the arXiv Programming Languages category (cs.PL)",
            "Papers in the arXiv Formal Languages and Automata Theory category (cs.FL)",
            "Papers in the arXiv Computational Complexity category (cs.CC)",
            "2026-10-",
            "CRMS> 5 (exact arithmetic",
        )
        for phrase in expected:
            require(phrase in output,
                    f"expanded model chat omitted {phrase!r}: {output}")
        require("Loaded portable learned model:" in output
                and "Metadata license:" not in output,
                f"chat did not use the self-contained model cleanly: {output}")

    print("expanded arXiv category language diagnostic: PASS")


if __name__ == "__main__":
    main()
