"""Drive pronoun follow-ups through the full chat on the SimpleWiki corpus."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = PROJECT / "data" / "crms_simplewiki_research.sqlite"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, turns: list[str], label: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / f"{label}-knowledge.json"),
        "--rules", str(root / f"{label}-rules.json"),
        "--index", str(SOURCE_DB), "--index-read-only",
        "--feedback-db", str(root / f"{label}-feedback.sqlite3"),
        "--dialogue-state", str(root / f"{label}-dialogue.json"),
        "--rule-session", str(root / f"{label}-rule-session.json"),
        "--math", str(root / f"{label}-math.json"),
        "--translations", str(root / f"{label}-translations.json"),
    ]
    result = subprocess.run(
        command, input="\n".join([*turns, "/quit"]) + "\n",
        text=True, capture_output=True, cwd=root, timeout=90, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"{label} fresh CLI failed: {output[-2500:]}")
    return output


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing full read-only corpus: {SOURCE_DB}")
    with tempfile.TemporaryDirectory(prefix="crms-v1-525-") as temp:
        root = Path(temp)
        conversation = run_chat(root, [
            "Where was Marie Curie born?",
            "And Albert Einstein?",
            "Where was he born?",
            "why?",
        ], "topic-switch")
        require("Marie Curie's birthplace as Warsaw" in conversation,
                "opening Marie Curie answer was not grounded")
        require("Albert Einstein's birthplace as Ulm" in conversation,
                "explicit Einstein topic switch did not use the exact-title field")
        require("Luke Baldwin" not in conversation,
                "pronoun follow-up leaked an unrelated birthplace")
        require("April 1955 — ) was" not in conversation,
                "an unrelated review proposal interrupted the direct answer")
        require("birth_place = Ulm" in conversation,
                "why? did not explain the latest Einstein evidence")

        no_antecedent = run_chat(root, ["Where was he born?"], "no-context")
        require("Luke Baldwin" not in no_antecedent,
                "a pronoun with no antecedent bound to an arbitrary source")
        require("birthplace as Ulm" not in no_antecedent,
                "a pronoun with no antecedent produced a confident answer")

    print("topic-switch follow-up resolves Einstein and cites Ulm: PASS")
    print("unrelated review proposal does not interrupt the answer: PASS")
    print("why? remains anchored to the latest source evidence: PASS")
    print("pronoun without an antecedent does not bind corpus-wide: PASS")


if __name__ == "__main__":
    main()
