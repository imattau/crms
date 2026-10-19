"""Check concise scope handling for explicit original-writing requests."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_creative_request
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    positive = {
        "Write a short story about Python.": "story",
        "Compose a poem about Ada Lovelace.": "poem",
        "Tell me a joke.": "joke",
        "Make me a song about Linux": "song",
        "Write a haiku": "haiku",
        "Write lyrics about computing": "lyrics",
    }
    for prompt, expected in positive.items():
        require(_natural_creative_request(prompt) == expected,
                f"creative request was not recognized: {prompt!r}")

    negative = (
        "Who created Python?",
        "What is the capital of France?",
        "Who wrote the poem that inspired Python?",
        "Write Python code to reverse a list.",
        "What is a short story?",
        "Can you explain Python?",
    )
    for prompt in negative:
        require(_natural_creative_request(prompt) is None,
                f"in-scope or non-imperative input was misrouted: {prompt!r}")

    with tempfile.TemporaryDirectory(prefix="crms-creative-scope-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "computing", "Computing facts",
                "Guido van Rossum created Python. Paris is the capital of France.",
                "fixture://computing")
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
            input=("Write a short story about Python.\n"
                   "Compose a poem about Ada Lovelace.\n"
                   "Tell me a joke.\n"
                   "Who created Python?\n"
                   "What is the capital of France?\n"
                   "/quit\n"),
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed ({result.returncode}): {result.stderr}\n"
                f"{result.stdout}")
        scope_reply = "I can't generate original creative writing from a prompt yet."
        require(result.stdout.count(scope_reply) == 3,
                f"creative requests did not receive the scope reply: {result.stdout}")
        require("Guido van Rossum created Python." in result.stdout
                and "Paris is the capital of France." in result.stdout,
                f"factual requests did not retain their normal routes: "
                f"{result.stdout}")

    print("creative-request scope routing and factual controls: PASS")


if __name__ == "__main__":
    main()
