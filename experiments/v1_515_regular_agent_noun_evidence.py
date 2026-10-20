"""Resolve a regular agent-noun question only from direct source evidence."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def ask(root: Path, knowledge_path: Path, index_path: Path,
        question: str, label: str) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(knowledge_path), "--index", str(index_path),
        "--feedback-db", str(root / f"{label}-feedback.sqlite3"),
        "--dialogue-state", str(root / f"{label}-dialogue.json"),
        "--rules", str(root / f"{label}-rules.json"),
        "--rule-session", str(root / f"{label}-rule-session.json"),
        "--math", str(root / f"{label}-math.json"),
        "--translations", str(root / f"{label}-translations.json"),
    ]
    result = subprocess.run(
        command, input=question + "\n/quit\n", text=True,
        capture_output=True, cwd=root, timeout=60, check=False)
    require(result.returncode == 0,
            f"{label} chat failed: {result.stderr}\n{result.stdout}")
    return result.stdout


def main() -> None:
    knowledge = CRMSKnowledgeBase()
    index = CRMSResearchIndex()
    sources = (
        ("design", "Design record",
         "Researcher 0000 designed the Vela instrument 0000."),
        ("build", "Construction record",
         "Researcher Luma built the Tern device."),
    )
    for document_id, title, sentence in sources:
        index.add_document(document_id, title, sentence,
                           f"{document_id}.txt")

    with tempfile.TemporaryDirectory(prefix="crms-v1-515-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        knowledge.save(knowledge_path)
        index.save(index_path)

        positive = ask(
            root, knowledge_path, index_path,
            "Who was the designer of the Vela instrument 0000?", "positive")
        require("Researcher 0000 designed the Vela instrument 0000." in positive,
                f"regular nominal form missed directly supporting evidence: {positive}")
        require("quoted evidence, not an accepted fact" in positive,
                f"source evidence was promoted to accepted knowledge: {positive}")

        negative = ask(
            root, knowledge_path, index_path,
            "Who was the builder of the Tern device?", "irregular")
        require("Researcher Luma" not in negative,
                f"irregular builder/built morphology produced a false answer: {negative}")
        require("couldn't find" in negative.casefold()
                or "don't know" in negative.casefold()
                or "won't guess" in negative.casefold(),
                f"unsupported irregular nominal should abstain: {negative}")

    print("PASS: regular designer → designed retrieves the exact cited sentence")
    print("PASS: the source remains quoted evidence, not an accepted fact")
    print("PASS: irregular builder → built does not fabricate a relation")
    print("LIMIT: morphology is retrieval-only; broader agent-noun coverage remains unmeasured")


if __name__ == "__main__":
    main()
