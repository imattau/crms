"""Check learning facts and question frames from the terminal chat interface.

Run from the project root with:
    python3 experiments/v1_40_cli_language_learning.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT))
from crms_knowledge import CRMSKnowledgeBase


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)

        def cli_command(knowledge_path: Path, index_path: Path,
                        dialogue_path: Path, name: str) -> list[str]:
            return [
                sys.executable, str(PROJECT / "crms_chat.py"),
                "--knowledge", str(knowledge_path), "--index", str(index_path),
                "--dialogue-state", str(dialogue_path),
                "--rules", str(temp / f"{name}-rules.json"),
                "--rule-session", str(temp / f"{name}-rule-session.json"),
                "--math", str(temp / f"{name}-math.json"),
                "--translations", str(temp / f"{name}-translations.json"),
            ]

        ada = temp / "ada.txt"
        grace = temp / "grace.txt"
        katherine = temp / "katherine.txt"
        ada.write_text("Ada Lovelace designed the Analytical Engine.", encoding="utf-8")
        grace.write_text("Grace Hopper designed the Compiler.", encoding="utf-8")
        katherine.write_text(
            "Katherine Johnson designed the trajectory table.", encoding="utf-8")
        knowledge = temp / "knowledge.json"
        index = temp / "index.json"
        dialogue = temp / "state.json"

        turns = [
            f"/source {ada}",
            "/teach-fact Ada Lovelace|designed|the Analytical Engine|Ada Lovelace designed Analytical Engine|designed|positive",
            f"/source {grace}",
            "/teach-fact Grace Hopper|designed|the Compiler|Grace Hopper designed Compiler|designed|positive",
            "/teach-question Who designed the Analytical Engine?|designed|subject|the Analytical Engine|Ada Lovelace",
            "/teach-question Who designed the Compiler?|designed|subject|the Compiler|Grace Hopper",
            f"/source {katherine}",
            "Who designed the trajectory table?",
            "/accept 1",
            "Who designed it?",
            "/quit",
        ]
        result = subprocess.run(
            cli_command(knowledge, index, dialogue, "initial"),
            input="\n".join(turns) + "\n", text=True, capture_output=True,
            check=True, timeout=20)
        output = result.stdout
        required = (
            "Sentence pattern licensed.",
            "Frame support: 2 distinct pair(s), 2 subject(s), 2 object(s), 2 source document(s).",
            "Frame licensing: needs at least 2 distinct subject/object pairs",
            "Question frame licensed.",
            "Unverified source candidate (supports): Katherine Johnson — designed → the trajectory table.",
            "Accepted positive fact: Katherine Johnson — designed → the trajectory table.",
            "Katherine Johnson designed the trajectory table.",
        )
        missing = [phrase for phrase in required if phrase not in output]
        if missing:
            raise SystemExit(f"interactive teaching missed {missing}:\n{output}")
        if not knowledge.exists() or not index.exists() or not dialogue.exists():
            raise SystemExit("interactive learning did not persist all stores")

        natural_knowledge_path = temp / "natural-knowledge.json"
        natural_knowledge = CRMSKnowledgeBase.load(knowledge)
        natural_knowledge._question_examples.clear()
        natural_knowledge.save(natural_knowledge_path)
        natural_output = subprocess.run(
            cli_command(natural_knowledge_path, index,
                        temp / "natural-state.json", "natural"),
            input=('Teach a question frame from examples: '
                   '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
                   '"Who designed the Compiler?" => "Grace Hopper".\n'
                   'Who designed the trajectory table?\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("Question frame licensed from 2 fact-backed examples "
                "(relation: designed; answer: subject)." not in natural_output
                or "Katherine Johnson designed the trajectory table." not in natural_output):
            raise SystemExit(f"conversational question-frame learning failed: {natural_output}")
        natural_resumed = subprocess.run(
            cli_command(natural_knowledge_path, index,
                        temp / "natural-resumed-state.json", "natural-resumed"),
            input="Who designed the trajectory table?\n/quit\n",
            text=True, capture_output=True, check=True, timeout=20).stdout
        if "Katherine Johnson designed the trajectory table." not in natural_resumed:
            raise SystemExit(f"conversationally taught question frame did not persist: {natural_resumed}")

        bidirectional_knowledge_path = temp / "bidirectional-knowledge.json"
        bidirectional_knowledge = CRMSKnowledgeBase.load(knowledge)
        bidirectional_knowledge._question_examples.clear()
        bidirectional_knowledge.save(bidirectional_knowledge_path)
        rejected_batch_output = subprocess.run(
            cli_command(bidirectional_knowledge_path, index,
                        temp / "rejected-batch-state.json", "rejected-batch"),
            input=(
                'Teach paired question frames from examples: '
                '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
                '"Who designed the Compiler?" => "Grace Hopper"; '
                '"What did Ada Lovelace design?" => "the Compiler"; '
                '"What did Grace Hopper design?" => "the Compiler".\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("Each paired question example must match one unique stored fact" not in
                rejected_batch_output
                or CRMSKnowledgeBase.load(
                    bidirectional_knowledge_path)._question_examples):
            raise SystemExit(
                "invalid paired training batch changed question memory:\n"
                f"{rejected_batch_output}")
        bidirectional_output = subprocess.run(
            cli_command(bidirectional_knowledge_path, index,
                        temp / "bidirectional-state.json", "bidirectional"),
            input=(
                'Teach paired question frames from examples: '
                '"Who designed the Analytical Engine?" => "Ada Lovelace"; '
                '"Who designed the Compiler?" => "Grace Hopper"; '
                '"What did Ada Lovelace design?" => "the Analytical Engine"; '
                '"What did Grace Hopper design?" => "the Compiler".\n'
                'Who designed the Analytical Engine?\n'
                'What did she design?\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("Paired question frames licensed from 4 fact-backed examples "
                "(2 wording patterns; relation: designed; answers: subject and object)."
                not in bidirectional_output
                or bidirectional_output.count(
                    "Ada Lovelace designed the Analytical Engine.") != 2
                or bidirectional_output.count("Source: ada.txt") != 2
                or "ada.txt#sha256=" in bidirectional_output):
            raise SystemExit(
                "conversationally learned answer directions did not compose "
                f"with grounded pronoun follow-up:\n{bidirectional_output}")

        polar_knowledge_path = temp / "polar-knowledge.json"
        polar_knowledge = CRMSKnowledgeBase.load(knowledge)
        polar_knowledge._question_examples.clear()
        polar_knowledge.add_fact(
            "Mary Jackson", "designed", "the flight equations",
            "teacher:explicit-positive-example")
        polar_knowledge.add_negative_fact(
            "Grace Hopper", "designed", "the trajectory table",
            "teacher:explicit-negative-example")
        polar_knowledge.add_negative_fact(
            "Katherine Johnson", "designed", "the Compiler",
            "teacher:held-out-negative-example")
        polar_knowledge.save(polar_knowledge_path)
        polar_output = subprocess.run(
            cli_command(polar_knowledge_path, index,
                        temp / "polar-state.json", "polar"),
            input=('Teach a yes/no frame from examples: '
                   '"Is it true that Ada Lovelace designed the Analytical Engine?" => yes; '
                   '"Is it true that Grace Hopper designed the trajectory table?" => no; '
                   '"Is it true that Mary Jackson designed the flight equations?" => yes.\n'
                   'Is it true that Katherine Johnson designed the Compiler?\n/quit\n'),
            text=True, capture_output=True, check=True, timeout=20).stdout
        if ("Yes/no frame licensed from 3 explicit fact examples "
                "(relation: designed)." not in polar_output
                or "No" not in polar_output):
            raise SystemExit(f"conversational polar learning failed: {polar_output}")

    print("CLI language learning diagnostic: PASS")
    print("cited pattern teaching, conversational question and truth-frame learning, "
          "held-out answers, review, dialogue, persistence: PASS")


if __name__ == "__main__":
    main()
