"""Check source-backed yes/no replies and open-world abstention in chat."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="crms-polar-source-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        index.add_document(
            "australia", "Capital of Australia",
            "Canberra is the capital of Australia, not Sydney.",
            "sources/australia.txt")
        index.add_document(
            "france", "Capital of France",
            "Paris is the capital of France.", "sources/france.txt")
        index.add_document(
            "sydney", "Sydney",
            "Sydney is the capital of New South Wales.", "sources/sydney.txt")
        index.add_document(
            "python", "Python history",
            "Guido van Rossum created Python.", "sources/python.txt")
        index.close()

        state = root / "state"
        state.mkdir()
        CRMSKnowledgeBase().save(state / "knowledge.json")
        command = [
            sys.executable, str(project / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(state / "knowledge.json"),
            "--rules", str(state / "rules.json"),
            "--math", str(state / "math.json"),
            "--translations", str(state / "translations.json"),
            "--dialogue-state", str(state / "dialogue.json"),
            "--rule-session", str(state / "rule-session.json"),
            "--candidate-session", str(state / "candidate-session.json"),
        ]
        run = subprocess.run(
            command,
            input=("Is Sydney the capital of Australia?\n"
                   "accept candidate 1\n"
                   "Is Sydney the capital of Australia?\n"
                   "Is Paris the capital of France?\n"
                   "accept candidate 1\n"
                   "Is Paris the capital of France?\n"
                   "Did Guido van Rossum create Linux?\n"
                   "Did Guido van Rossum create Python?\n/quit\n"),
            text=True, capture_output=True, timeout=60, check=False)
        require(run.returncode == 0,
                f"chat exited {run.returncode}: {run.stderr}")
        expected = (
            "The source states no: “Canberra is the capital of Australia, not Sydney.”",
            "Accepted negative fact: Sydney — capital of → Australia.",
            "CRMS> No.",
            "The source states yes: “Paris is the capital of France.”",
            "Accepted positive fact: Paris — capital of → France.",
            "CRMS> Yes.",
            "I don't have a direct source statement for this exact proposition",
            "The source states yes: “Guido van Rossum created Python.”",
        )
        missing = [fragment for fragment in expected if fragment not in run.stdout]
        require(not missing,
                f"polar evidence or abstention failed for {missing}: {run.stdout}")
        require("Sydney is the capital of New South Wales" not in run.stdout,
                "a lexical location decoy leaked into the polar answer")

    print("source-grounded polar chat diagnostic: PASS")
    print("explicit positive/negative source candidates, review-before-storage, learned Yes/No, unrelated-claim abstention, and decoy suppression: PASS")


if __name__ == "__main__":
    main()
