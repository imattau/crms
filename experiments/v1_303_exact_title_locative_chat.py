"""Check where-question retrieval inside an exact-title article."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-title-locative-") as folder:
        root = Path(folder)
        index_path = root / "research.sqlite"
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            index.add_document(
                "alan-turing", "Alan Turing",
                "DEFAULTSORT:Turing, Alan\n"
                "During World War II, Turing worked at Bletchley Park.\n"
                "He later lived in Manchester.",
                "fixture://alan-turing")
        finally:
            index.close()

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--index", str(index_path),
            "--knowledge", str(root / "knowledge.json"),
            "--rules", str(root / "rules.json"),
            "--math", str(root / "math.json"),
            "--translations", str(root / "translations.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--candidate-session", str(root / "candidates.json"),
        ]
        result = subprocess.run(
            command,
            input="Where did Alan Turing work?\n/quit\n",
            text=True, capture_output=True, check=False, timeout=30)
        require(result.returncode == 0,
                f"chat failed: {result.stderr}\n{result.stdout}")
        require("During World War II, Turing worked at Bletchley Park."
                in result.stdout
                and "[Source: Alan Turing; quoted evidence, not an accepted fact]"
                in result.stdout,
                f"exact-title locative evidence was missed or misattributed: "
                f"{result.stdout}")
        require("University of Manchester" not in result.stdout,
                f"chat combined multiple workplace statements: {result.stdout}")

    print("exact-title locative source retrieval: PASS")
    print("metadata snippets, fronted time adjuncts, and article-local surname "
          "references preserve the cited sentence")


if __name__ == "__main__":
    main()
