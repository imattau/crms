"""Pending source candidates stay reviewable without hijacking other answers."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_chat(root: Path, index_path: Path, turns: tuple[str, ...],
             name: str) -> tuple[str, list[str]]:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(index_path), "--index-read-only",
        "--dialogue-state", str(root / f"{name}-dialogue.json"),
        "--candidate-session", str(root / "candidates.json"),
        "--rule-session", str(root / f"{name}-rules.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*turns, "/quit", "")), text=True,
        capture_output=True, cwd=root, check=False, timeout=45)
    require(result.returncode == 0 and "Traceback" not in
            result.stdout + result.stderr,
            f"chat failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    chunks = [part.strip() for part in result.stdout.split("you> ")[1:]]
    # The CLI prints its final input prompt before reading /quit as well.
    require(len(chunks) == len(turns) + 1,
            f"expected {len(turns) + 1} prompts, received {len(chunks)}:\n"
            f"{result.stdout}")
    return result.stdout, chunks[:-1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-pending-review-followup-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "seine", "Paris river source",
            "The Seine flows through Paris. The Seine is a river.",
            "https://example.test/seine")
        index.close()

        knowledge = CRMSKnowledgeBase()
        knowledge.add_fact("Alice", "likes", "tea", "accepted:tea")
        knowledge.teach_question(
            "Who likes tea?", relation="likes", answer_field="subject",
            bound_entity="tea", answer="Alice")
        knowledge.save(root / "knowledge.json")

        first_output, replies = run_chat(
            root, index_path,
            ("Which river flows through Paris?", "Who likes tea?",
             "/pending-candidates"), "first")
        require("Review candidate 1" in replies[0]
                and "Review candidate 2" in replies[0],
                f"setup did not create two review-only candidates: {replies[0]}")
        require("Alice likes tea." in replies[1]
                and "accepted:tea" in replies[1]
                and "Review candidate" not in replies[1]
                and "candidate(s) remain pending" not in replies[1]
                and "Say 'yes'" not in replies[1],
                f"pending candidates interrupted an unrelated direct answer: "
                f"{replies[1]}")
        require("The Seine" in replies[2]
                and "flows through" in replies[2]
                and "is-a" in replies[2],
                f"candidates disappeared from explicit review: {replies[2]}")

        _restarted_output, restarted = run_chat(
            root, index_path, ("/pending-candidates",), "restarted")
        require("Restored 2 pending cited fact candidate" in _restarted_output
                and "The Seine" in restarted[0]
                and "flows through" in restarted[0]
                and "is-a" in restarted[0],
                f"pending candidates did not survive restart: {restarted[0]}")

    print("review-only candidates do not interrupt an unrelated accepted answer: PASS")
    print("candidates remain available through explicit review: PASS")
    print("pending candidates survive restart with cited lineage: PASS")


if __name__ == "__main__":
    main()
