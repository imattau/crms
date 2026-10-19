"""Check natural evidence follow-ups after quoted-source answers."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    sentence = "Guido van Rossum created Python."
    with tempfile.TemporaryDirectory(prefix="crms-quoted-followup-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document("python", "Python history", sentence,
                               "fixture://python-history")
        finally:
            index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command,
            input=("Who created Python?\nWhy?\n"
                   "Who created Python?\nHow do you know?\n"
                   "Who created Python?\nAre you sure?\n/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n"
                f"{result.stdout}")
        require("Guido van Rossum created Python." in result.stdout
                and "quoted evidence, not an accepted fact" in result.stdout,
                f"initial answer lost its source status: {result.stdout}")
        evidence_explanations = result.stdout.count(
            "I used this quoted source sentence as evidence")
        require(evidence_explanations == 3
                and "it has not been accepted as a fact" in result.stdout
                and result.stdout.count("Guido van Rossum created Python.") >= 6
                and result.stdout.count("Python history") >= 3,
                "natural evidence follow-ups did not explain the cited result "
                f"consistently ({evidence_explanations} explanations):\n"
                f"{result.stdout}")
        require("verified language rule to paraphrase" not in result.stdout,
                f"quoted evidence was mislabeled as a paraphrase failure: "
                f"{result.stdout}")

    print("Why/how-do-you-know/are-you-sure follow-ups preserve quoted source "
          "and review status: PASS")


if __name__ == "__main__":
    main()
