"""Check that history recall preserves a visible source choice in chat."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-517-") as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        CRMSKnowledgeBase().save(knowledge_path)
        sources = root / "sources"
        sources.mkdir()
        (sources / "bistro.txt").write_text(
            "Bistro Alder is an Italian restaurant that serves handmade pasta "
            "and has outdoor seating near the river.", encoding="utf-8")
        (sources / "cafe.txt").write_text(
            "Cafe Birch is a French restaurant that serves pastries and has "
            "indoor seating near the river.", encoding="utf-8")

        turns = (
            f"/source-dir {sources}",
            "List restaurants near the river.",
            "What did I just ask?",
            "What about the first one?",
            "why?",
        )
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "index.sqlite"),
            "--feedback-db", str(root / "feedback.sqlite3"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
        ]
        run = subprocess.run(
            command, input="\n".join((*turns, "/quit")) + "\n",
            text=True, capture_output=True, cwd=root, timeout=60, check=False)
        require(run.returncode == 0,
                f"fresh chat failed: {run.stderr}\n{run.stdout}")
        chunks = run.stdout.split("you> ")
        require(len(chunks) == len(turns) + 2,
                f"expected one response per turn plus /quit, got {len(chunks) - 2}: {run.stdout}")
        listing, recall, selected, explanation = (
            chunk.strip() for chunk in chunks[2:6])

        require("1. Cafe Birch" in listing and "2. Bistro Alder" in listing,
                f"the source list was not displayed in a selectable order: {listing}")
        require("Your last question was: List restaurants near the river." in recall,
                f"history recall did not identify the preceding question: {recall}")
        require("Cafe Birch is a French restaurant" in selected
                and "Source: cafe.txt" in selected
                and "Bistro Alder" not in selected,
                f"ordinal selection did not preserve the displayed first source: {selected}")
        require("cafe.txt" in explanation.casefold()
                and "Bistro Alder" not in explanation,
                f"why? lost the selected source context: {explanation}")

        restored = CRMSKnowledgeBase.load(knowledge_path)
        require(not restored.facts(),
                "selecting a cited source should not create accepted facts")

    print("PASS: the chat recalls the actual previous question")
    print("PASS: history recall preserves the visible source-list context")
    print("PASS: 'the first one' selects the exact cited first source")
    print("PASS: why? stays anchored to that selected source")
    print("PASS: selection remains quoted evidence and does not teach a fact")
    print("LIMIT: one controlled conversation; broader dialogue transfer remains open")


if __name__ == "__main__":
    main()
