"""Keep unsupported mathematical proof requests out of lexical paper retrieval."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _unsupported_mathematical_proof_request


def main() -> None:
    positives = (
        "How do I prove that sqrt(2) is irrational?",
        "Show that 17 is prime.",
        "Can you derive why this equation has no integer solution?",
    )
    negatives = (
        "How do I prove my software has no bugs?",
        "What is the latest theorem in graph theory?",
        "What is 2 + 3?",
    )
    for question in positives:
        if not _unsupported_mathematical_proof_request(question):
            raise SystemExit(f"mathematical proof request was not routed: {question}")
    for question in negatives:
        if _unsupported_mathematical_proof_request(question):
            raise SystemExit(f"non-proof request was caught by the guard: {question}")

    source_model = PROJECT / "data" / "crms_project_model_academic.sqlite"
    source_sidecar = source_model.with_name(source_model.name + ".memories")
    if not source_model.is_file() or not source_sidecar.is_dir():
        raise SystemExit("portable academic model or memory sidecar is missing")
    with tempfile.TemporaryDirectory(prefix="crms-math-proof-routing-") as folder:
        root = Path(folder)
        model = root / source_model.name
        shutil.copy2(source_model, model)
        shutil.copytree(source_sidecar, model.with_name(model.name + ".memories"))
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--model-db", str(model),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
            "--rule-session", str(root / "rules.json"),
            "--math-session", str(root / "math.json"),
            "--translation-session", str(root / "translations.json"),
        ]
        result = subprocess.run(
            command,
            input="How do I prove that sqrt(2) is irrational?\nWhat is 2 + 3?\n/quit\n",
            text=True, capture_output=True, check=False, timeout=45)
        if result.returncode:
            raise SystemExit(f"chat failed: {result.stderr}\n{result.stdout}")
        if ("I don't have a verified proof rule" not in result.stdout
                or "Improved Regret for Zeroth-Order" in result.stdout
                or "CRMS> 5 (exact arithmetic" not in result.stdout):
            raise SystemExit(
                "proof routing either leaked unrelated research or disrupted "
                f"exact arithmetic:\n{result.stdout}")

    print("mathematical proof intent routing: PASS")
    print("unsupported proof abstains without lexical research; exact arithmetic remains available")


if __name__ == "__main__":
    main()
