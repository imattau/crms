"""Check conversational acquisition of proof-backed relation-path questions."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase

PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        knowledge = CRMSKnowledgeBase()
        for subject, middle, answer, label in (
                ("Ada", "Bea", "Cal", "ada"),
                ("Mia", "Nia", "Ora", "mia"),
                ("Kai", "Lee", "Uma", "kai"),
                ("Tia", "Vik", "Wen", "tia")):
            knowledge.add_fact(subject, "parent", middle, f"source:{label}:1")
            knowledge.add_fact(middle, "parent", answer, f"source:{label}:2")
        for subject, middle, relation, label in (
                ("Rae", "Sam", "parent", "rae-parent"),
                ("Rae", "Tay", "mentor", "rae-mentor")):
            knowledge.add_fact(subject, relation, middle, f"source:{label}:1")
            knowledge.add_fact(middle, relation, "Zen", f"source:{label}:2")
        knowledge.save(knowledge_path)
        command = [sys.executable, str(PROJECT / "crms_chat.py"),
                   "--knowledge", str(knowledge_path),
                   "--index", str(root / "index.json"),
                   "--dialogue-state", str(root / "dialogue.json")]
        teach = (
            'Teach a path-question frame from examples: '
            '"Who is the ancestor of Ada?" => "Cal"; '
            '"Who is the ancestor of Mia?" => "Ora"; '
            '"Who is the ancestor of Kai?" => "Uma".')
        ambiguous = (
            'Teach a path-question frame from examples: '
            '"Who is the ancestor of Rae?" => "Zen"; '
            '"Who is the ancestor of Mia?" => "Ora".')
        output = subprocess.run(
            command,
            input="\n".join((ambiguous, teach, "Who is the ancestor of Tia?",
                              "Who is the ancestor of Zed?", "/quit")) + "\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("do not each resolve to one shared fact-backed path" not in output
                or "Path-question frame licensed from 3 fact-backed examples "
                "(path: parent -> parent)." not in output
                or "Answer: Wen." not in output
                or "The question frame is grounded, but no matching fact path is stored."
                not in output):
            raise SystemExit(f"conversational path-question learning failed:\n{output}")

        resumed_command = command[:6] + [
            "--dialogue-state", str(root / "resumed.json")]
        resumed = subprocess.run(
            resumed_command, input="Who is the ancestor of Tia?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        if "Answer: Wen." not in resumed:
            raise SystemExit(f"path-question frame did not persist:\n{resumed}")

    print("conversational path-question learning diagnostic: PASS")
    print("unique path resolution, ambiguous-path abstention, held-out transfer, "
          "unknown-path abstention, persistence: PASS")


if __name__ == "__main__":
    main()
