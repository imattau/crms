"""Check grounded conversational extension of a qualified question frame."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


PROJECT = Path(__file__).resolve().parents[1]


def seed(root: Path) -> None:
    knowledge = CRMSKnowledgeBase()
    for subject, relation, obj, year, source in (
            ("Ada Lovelace", "designed", "the Analytical Engine", "1843", "ada"),
            ("Grace Hopper", "designed", "the Compiler", "1952", "grace"),
            ("Katherine Johnson", "designed", "the trajectory table", "1969", "katherine")):
        knowledge.add_fact(subject, relation, obj, source, qualifiers={"year": year})
    knowledge.save(root / "knowledge.json")


def run_chat(root: Path, turns: tuple[str, ...]) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--index", str(root / "index.json"),
        "--dialogue-state", str(root / "dialogue.json"),
    ]
    return subprocess.run(
        command, input="\n".join((*turns, "/quit")) + "\n",
        text=True, capture_output=True, check=True, timeout=30).stdout


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        seed(root)
        output = run_chat(root, (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine in 1843?" => "Ada Lovelace"; '
            '"Who designed the Compiler in 1952?" => "Grace Hopper"',
            'Teach an additional contextual question example: '
            '"Who designed the trajectory table in 1969?" => "Katherine Johnson"',
            "Who designed the trajectory table in 1969?",
        ))
        if ("Question frame licensed from 2 qualified examples" not in output
                or "Additional qualified question example added" not in output
                or "Answer: Katherine Johnson" not in output):
            raise SystemExit(f"incremental qualified example did not transfer: {output}")
        restored = CRMSKnowledgeBase.load(root / "knowledge.json")
        answer = restored.ask("Who designed the trajectory table in 1969?")
        if answer.status != "answered" or answer.answer != "Katherine Johnson":
            raise SystemExit(f"qualified example did not persist: {answer}")

        unlicensed_root = Path(folder) / "unlicensed"
        unlicensed_root.mkdir()
        seed(unlicensed_root)
        rejected = run_chat(unlicensed_root, (
            'Teach an additional qualified question example: '
            '"Who designed the trajectory table in 1969?" => "Katherine Johnson"',
        ))
        if "No already licensed exact qualified question frame" not in rejected:
            raise SystemExit(f"one example licensed a qualified frame: {rejected}")
        unmodified = CRMSKnowledgeBase.load(unlicensed_root / "knowledge.json")
        if unmodified._qualified_question_examples:
            raise SystemExit("unlicensed qualified frame changed memory")

        invalid_root = Path(folder) / "invalid"
        invalid_root.mkdir()
        seed(invalid_root)
        invalid = run_chat(invalid_root, (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine in 1843?" => "Ada Lovelace"; '
            '"Who designed the Compiler in 1952?" => "Grace Hopper"',
            'Teach an additional contextual question example: '
            '"Who designed an imaginary device in 1969?" => "Katherine Johnson"',
        ))
        if "does not identify one directly supported qualified fact" not in invalid:
            raise SystemExit(f"unsupported qualified example was accepted: {invalid}")
        preserved = CRMSKnowledgeBase.load(invalid_root / "knowledge.json")
        if preserved.ask("Who designed the Compiler in 1952?").answer != "Grace Hopper":
            raise SystemExit("rejected example damaged the licensed qualified frame")

    print("incremental qualified question-frame learning diagnostic: PASS")
    print("one-qualifier exact-frame check, direct evidence, transfer, abstention, "
          "transactional rejection, and persistence: PASS")


if __name__ == "__main__":
    main()
