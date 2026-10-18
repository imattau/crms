"""Check natural-language teaching of fact-grounded contextual question frames."""
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
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        knowledge = CRMSKnowledgeBase()
        knowledge.add_fact("Ada", "managed", "Project Alpha", "source:alpha",
                           qualifiers={"year": "2020"})
        knowledge.add_fact("Bob", "managed", "Project Beta", "source:beta",
                           qualifiers={"year": "2024"})
        knowledge.add_fact("Mia", "managed", "Project Gamma", "source:gamma",
                           qualifiers={"year": "2025"})
        knowledge.add_fact("Nia", "managed", "Project Delta", "source:delta",
                           qualifiers={"year": "2026"})
        knowledge.save(knowledge_path)
        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
        ]
        invalid = (
            'Teach a question frame from examples: '
            '"Who managed Project Alpha in 2020?" => "Ada"; '
            '"Who managed Project Beta in 2020?" => "Bob".')
        valid = (
            'Teach a question frame from examples: '
            '"Who managed Project Alpha in 2020?" => "Ada"; '
            '"Who managed Project Beta in 2024?" => "Bob"; '
            '"Who managed Project Gamma in 2025?" => "Mia".')
        process = subprocess.run(
            command,
            input="\n".join((invalid, valid,
                              "Who managed Project Delta in 2026?",
                              "Who managed Project Gamma in 2025?",
                              "Who managed Project Gamma in 2024?",
                              "/quit")) + "\n",
            text=True, capture_output=True, check=True, timeout=20)
        output = process.stdout
        require("do not uniquely identify one shared fact-backed question pattern"
                in output,
                f"context-mismatched examples were not rejected:\n{output}")
        require("Question frame licensed from 3 qualified examples "
                "(relation: managed; answer: subject; qualifiers: year)." in output,
                f"aligned contextual examples did not license a question frame:\n{output}")
        require("Answer: Nia." in output and "Answer: Mia." in output,
                f"held-out entity and year did not resolve:\n{output}")
        require("The qualified question frame is learned, but no matching fact "
                "or rule proof is stored." in output,
                f"wrong contextual value did not abstain:\n{output}")

        resumed_command = command[:6] + [
            "--dialogue-state", str(root / "resumed.json")]
        resumed = subprocess.run(
            resumed_command,
            input="Who managed Project Gamma in 2025?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        require("Answer: Mia." in resumed,
                f"contextual question frame did not persist:\n{resumed}")

    print("conversational contextual question-learning diagnostic: PASS")
    print("evidence alignment, context mismatch abstention, held-out transfer, persistence: PASS")


if __name__ == "__main__":
    main()
