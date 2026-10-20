"""Recall the user's actual last question after dialogue resolution.

Run with: python3 experiments/v1_542_exact_question_recall.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-question-recall-",
                                     dir="/tmp") as folder:
        root = Path(folder)
        source = root / "tower.txt"
        source.write_text(
            "The Eiffel Tower is located in Paris. "
            "It was completed in 1889.\n", encoding="utf-8")
        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(root / f"{name}.json")))
        options.extend(("--index", str(root / "index.sqlite")))
        command = [sys.executable, str(PROJECT / "crms_chat.py"), *options]
        run = subprocess.run(
            command,
            input=(f"/source {source}\n"
                   "Where is the Eiffel Tower?\n"
                   "When was it completed?\n"
                   "What did I just ask?\n"
                   "/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=120,
            check=False)
        output = run.stdout + run.stderr
        require(run.returncode == 0 and "Traceback" not in output,
                f"fresh chat failed: {output}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in run.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == 3,
                f"expected three chat replies, got {replies!r}")
        require("1889" in replies[1],
                f"pronoun follow-up did not resolve before recall: {replies[1]!r}")
        require(replies[2] == "Your last question was: When was it completed?",
                "recall should preserve the user's actual wording, not the "
                f"resolved internal query: {replies[2]!r}")

    print("fresh chat resolves a pronoun follow-up and recalls exact user wording: PASS")


if __name__ == "__main__":
    main()
