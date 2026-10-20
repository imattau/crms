"""End-to-end chat checks for reported source-question failures.

The scratch corpus tests retrieval, supported voice realization, and the
current abstention boundary for an unlicensed semantic paraphrase. Run with: python3
experiments/v1_418_reported_chat_language_regressions.py
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="crms-reported-language-chat-",
                                    dir="/tmp"))
    try:
        docs = scratch / "docs"
        docs.mkdir()
        (docs / "everest.txt").write_text(
            "Mount Everest is located in the Himalayas.\n", encoding="utf-8")
        (docs / "turing.txt").write_text(
            "Alan Turing worked at Bletchley Park.\n", encoding="utf-8")
        (docs / "eiffel.txt").write_text(
            "Gustave Eiffel designed and built the Eiffel Tower.\n",
            encoding="utf-8")
        (docs / "rivers.txt").write_text(
            "Nacre City 0133 is crossed by Serein River 0133.\n",
            encoding="utf-8")

        options: list[str] = []
        for name in ("knowledge", "math", "rules", "dialogue-state",
                     "rule-session", "candidate-session", "math-session",
                     "translations", "translation-session"):
            options.extend(("--" + name, str(scratch / f"{name}.json")))
        command = [sys.executable, str(PROJECT / "crms_chat.py"), *options,
                   "--index", str(scratch / "research.sqlite")]
        questions = (
            "Where is Mount Everest located?",
            "Where does Alan Turing work?",
            "Who built the Eiffel Tower?",
            "What body of water crosses Nacre City 0133?",
            "Did Alan Turing work at Bletchley Park?",
            "Who made the Eiffel Tower?",
            "Where does the Serein River 0133 run?",
            "What body of water crosses Nacre City 0134?",
        )
        result = subprocess.run(
            command,
            input=f"/source-dir {docs}\n" + "\n".join(questions)
            + "\n/quit\n",
            text=True, capture_output=True, timeout=120,
            env=os.environ.copy(), check=False)
        require(result.returncode == 0,
                f"chat exited {result.returncode}: {result.stderr}\n{result.stdout}")
        replies = [line.split("CRMS>", 1)[1].strip()
                   for line in result.stdout.splitlines() if "CRMS>" in line]
        require(len(replies) == len(questions),
                f"expected {len(questions)} chat replies, got {len(replies)}:\n"
                + result.stdout)

        expected_sentences = (
            "Mount Everest is located in the Himalayas.",
            "Alan Turing worked at Bletchley Park.",
            "Gustave Eiffel designed and built the Eiffel Tower.",
        )
        for reply, sentence in zip(replies[:3], expected_sentences[:3]):
            require(sentence in reply,
                    f"chat failed to return the expected cited sentence {sentence!r}: "
                    f"{reply!r}")
        require("Serein River 0133 crosses Nacre City 0133." in replies[3]
                and "[Source: rivers.txt; quoted evidence, not an accepted fact]"
                in replies[3],
                "chat failed to realize and cite the source-backed answer to the "
                f"passive crossing sentence: {replies[3]!r}")
        require("source states yes" in replies[4].casefold(),
                f"supported polar question did not return yes: {replies[4]!r}")
        require("can't answer with 'made' yet" in replies[5].casefold()
                and "confirm that the wording and roles match" in replies[5],
                f"unlicensed synonym was presented as a direct answer: {replies[5]!r}")
        for index in (6, 7):
            require("i won't guess" in replies[index].casefold()
                    or "does not support a grounded answer" in replies[index].casefold(),
                    f"unlicensed or wrong-entity query did not abstain: {replies[index]!r}")
        require("0133" not in replies[7],
                f"wrong numbered entity leaked as an answer: {replies[7]!r}")

        print("reported Everest, Turing, Eiffel, and crossing questions: PASS")
        print("source-backed yes/no, unlicensed-synonym review, and run/wrong-ID abstentions: PASS")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
