"""Exercise a bounded creative revision turn in the terminal chat."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_story_revision
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(_natural_story_revision("Make it funnier") == "funny"
            and _natural_story_revision("Could you make the story more adventurous?")
            == "adventure"
            and _natural_story_revision("Change the tone to funny.") == "funny",
            "supported story tone revisions were not recognized")
    for text in (
            "Make the code funnier.",
            "Make it funnier and add a dragon.",
            "Who wrote the story?",
            "Make the story sadder."):
        require(_natural_story_revision(text) is None,
                f"unsupported or unrelated revision was accepted: {text!r}")

    with tempfile.TemporaryDirectory(prefix="crms-story-revision-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "computing", "Computing facts",
                "Guido van Rossum created Python.", "fixture://computing")
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
            "--feedback-db", str(root / "feedback.sqlite3"),
        ]
        result = subprocess.run(
            command,
            input=("Write a short story about Python.\n"
                   "Can you make it funnier?\n"
                   "Make it funnier.\n"
                   "Who created Python?\n"
                   "/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n"
                f"{result.stdout}")
        require(result.stdout.count(
                    "Fictional short story (invented details; no factual claims):")
                == 2
                and "Revised the story in a funny tone." in result.stdout
                and "Template: comic-council-v1." in result.stdout
                and "The latest story already uses the funny tone." in result.stdout,
                f"story revision or repeated-tone handling failed: {result.stdout}")
        require("Guido van Rossum created Python." in result.stdout,
                "story revision interfered with the factual answer route")

    print("session story revision, tone limits, and factual-route isolation: PASS")


if __name__ == "__main__":
    main()
