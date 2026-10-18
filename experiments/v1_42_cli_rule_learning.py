"""Check the terminal chat can teach and apply learned list procedures.

Run from the project root with:
    python3 experiments/v1_42_cli_rule_learning.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        rules = temp / "rules.json"
        inputs = [
            "/teach-rule reverse the list|1,2,3|3,2,1",
            "/teach-rule reverse the list|5,0,-2|-2,0,5",
            "/teach-rule reverse the list|0,1,2,3|3,2,1,0",
            "/explain-rule reverse the list|7,1,-4",
            "/apply-rule reverse the list|7,1,-4",
            "Reverse the list [7,1,-4]",
            "Apply reverse the list to [8,0,-3]",
            "/rules",
            "/quit",
        ]
        result = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--rules", str(rules),
             "--knowledge", str(temp / "knowledge.json"),
             "--index", str(temp / "index.json"),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rule-depth", "1"],
            input="\n".join(inputs) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        output = result.stdout
        required = ("Rule learning status: learned.", "CRMS> [-4, 1, 7]",
                    "CRMS> [-3, 0, 8]",
                    "reverse the list: reverse",
                    "Rule explanation status: ok.",
                    "Grounding phrases: reverse the list",
                    "examples: [1, 2, 3] -> [3, 2, 1]")
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"rule-learning chat omitted {missing}:\n{output}")
        if not rules.exists():
            raise SystemExit("transformation rules were not persisted")

    print("CLI rule learning diagnostic: PASS")
    print("example teaching, held-out application, rule inspection and persistence: PASS")


if __name__ == "__main__":
    main()
