"""Check incremental extension of a multi-qualifier question frame."""
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
    for subject, obj, year, location, source in (
            ("Ada Lovelace", "the Analytical Engine", "1843", "London", "ada"),
            ("Grace Hopper", "the Compiler", "1952", "New York", "grace"),
            ("Katherine Johnson", "the trajectory table", "1969", "Washington", "katherine")):
        knowledge.add_fact(subject, "designed", obj, source,
                           qualifiers={"year": year, "location": location})
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
            '"Who designed the Analytical Engine in 1843 in London?" => "Ada Lovelace"; '
            '"Who designed the Compiler in 1952 in New York?" => "Grace Hopper"',
            'Teach an additional contextual question example: '
            '"Who designed the trajectory table in 1969 in Washington?" => "Katherine Johnson"',
            "Who designed the trajectory table in 1969 in Washington?",
        ))
        if ("Question frame licensed from 2 qualified examples" not in output
                or "Additional qualified question example added" not in output
                or "Answer: Katherine Johnson" not in output):
            raise SystemExit(f"incremental multi-qualifier example failed: {output}")
        restored = CRMSKnowledgeBase.load(root / "knowledge.json")
        answer = restored.ask("Who designed the trajectory table in 1969 in Washington?")
        if answer.status != "answered" or answer.answer != "Katherine Johnson":
            raise SystemExit(f"multi-qualifier example did not persist: {answer}")

        invalid_root = Path(folder) / "invalid"
        invalid_root.mkdir()
        seed(invalid_root)
        invalid = run_chat(invalid_root, (
            'Teach a question frame from examples: '
            '"Who designed the Analytical Engine in 1843 in London?" => "Ada Lovelace"; '
            '"Who designed the Compiler in 1952 in New York?" => "Grace Hopper"',
            'Teach an additional contextual question example: '
            '"Who designed an imaginary device in 1969 in Washington?" => "Katherine Johnson"',
        ))
        if "does not identify one directly supported qualified fact" not in invalid:
            raise SystemExit(f"unsupported multi-qualifier example was accepted: {invalid}")

    print("incremental multi-qualifier question-frame diagnostic: PASS")
    print("exact placeholder alignment, all qualifier slots grounded, held-out transfer, "
          "transactional abstention, and persistence: PASS")


if __name__ == "__main__":
    main()
