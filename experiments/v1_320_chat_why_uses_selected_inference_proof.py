"""Keep chat's why-followup attached to the latest inference proof."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-v1-320-") as folder:
        root = Path(folder)
        kb = CRMSKnowledgeBase()
        kb.add_fact("Ann", "parent", "Bob", "source:ann-bob")
        kb.add_fact("Bob", "parent", "Cara", "source:bob-cara")
        kb.add_inference_rule(
            "grandparent-rule", "parent", "parent", "grandparent")
        kb.save(root / "knowledge.json")

        index = CRMSResearchIndex()
        index.add_document(
            "unrelated-grandparent", "Family guide",
            "A grandparent is a parent of one of a person's parents."
            " This description does not establish anything about Ann, Bob, or Cara.",
            "family-guide.txt")
        index.save(root / "index.json")

        command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(root / "knowledge.json"),
            "--index", str(root / "index.json"),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rules", str(root / "rules.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
        ]
        run = subprocess.run(
            command,
            input=("What is a grandparent?\n"
                   "Is Ann a grandparent of Cara?\n"
                   "Why?\n/quit\n"),
            text=True, capture_output=True, cwd=root, timeout=30, check=False)
        output = run.stdout + run.stderr
        if run.returncode or "Traceback" in output:
            raise SystemExit(f"chat failed during proof explanation:\n{output}")
        if "Yes." not in output:
            raise SystemExit(f"natural-language inference did not answer:\n{output}")
        why_reply = output.rsplit("you> CRMS> Yes.", 1)[-1]
        if ("grandparent-rule" not in why_reply
                or "source:ann-bob" not in why_reply
                or "source:bob-cara" not in why_reply):
            raise SystemExit(
                "why-followup did not explain the selected proof:\n" + output)
        if "Family guide" in why_reply or "does not establish" in why_reply:
            raise SystemExit(
                "why-followup explained an unrelated retrieval sentence:\n" + output)
        print("PASS: chat explains the selected inference proof after retrieval")
        print("PASS: unrelated source evidence does not replace proof context")


if __name__ == "__main__":
    main()
