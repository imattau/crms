"""Check multi-hop question learning through the terminal chat interface.

Run from the project root with:
    python3 experiments/v1_41_cli_path_learning.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        kb = CRMSKnowledgeBase()
        for fact in (
                ("Ada Lovelace", "designed", "the Analytical Engine", "a1"),
                ("the Analytical Engine", "uses", "steam", "a2"),
                ("Grace Hopper", "designed", "the Compiler", "b1"),
                ("the Compiler", "uses", "electricity", "b2"),
                ("Katherine Johnson", "designed", "the trajectory table", "c1"),
                ("the trajectory table", "uses", "solar power", "c2")):
            kb.add_fact(*fact)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        q1 = "Which power source is used by the thing designed by Ada Lovelace?"
        q2 = "Which power source is used by the thing designed by Grace Hopper?"
        turns = [
            f"/teach-path-question {q1}|designed>uses|Ada Lovelace|steam",
            f"/teach-path-question {q2}|designed>uses|Grace Hopper|electricity",
            "/facts",
            "/sources",
            "Which power source is used by the thing designed by Katherine Johnson?",
            "/quit",
        ]
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path)],
            input="\n".join(turns) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        output = result.stdout
        required = ("Path question frame licensed.", "FACT: Ada Lovelace",
                    "No sources are indexed yet.", "Answer: solar power.",
                    "Proof 1:")
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"path learning CLI omitted {missing}:\n{output}")

    print("CLI path learning diagnostic: PASS")
    print("multi-hop frame teaching, fact/source inspection, held-out composition and proof: PASS")


if __name__ == "__main__":
    main()
