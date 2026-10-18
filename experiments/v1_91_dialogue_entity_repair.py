"""Check explicit entity correction in grounded short-turn dialogue.

Run from the project root with:
    python3 experiments/v1_91_dialogue_entity_repair.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def build_knowledge() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    examples = (
        ("Ada", "designed", "Engine", "source:ada"),
        ("Grace", "designed", "Compiler", "source:grace"),
    )
    for example in examples:
        kb.add_fact(*example)
    for subject, relation, obj, _source in examples:
        kb.teach_question(f"Who designed the {obj}?", relation=relation,
                          answer_field="subject", bound_entity=obj,
                          answer=subject)
    return kb


def main() -> None:
    complementizer_question = (
        "Does the word count prove that CRMS knows as much as a large model?")
    complementizer_turn = CRMSDialogue(CRMSKnowledgeBase()).turn(
        complementizer_question)
    if ("Please name the entity this pronoun refers to" in complementizer_turn.text
            or complementizer_turn.resolved_question != complementizer_question):
        raise SystemExit(
            f"clausal 'that' was treated as a dialogue pronoun: "
            f"{complementizer_turn}")

    kb = build_knowledge()
    dialogue = CRMSDialogue(kb)
    first = dialogue.turn("Who designed the Engine?")
    if first.response is None or first.response.answer != "Ada":
        raise SystemExit(f"initial grounded question failed: {first}")

    corrected = dialogue.turn("Actually, I meant the Compiler.")
    if (corrected.status != "answered"
            or corrected.resolved_question != "Who designed the Compiler?"
            or corrected.response is None
            or corrected.response.answer != "Grace"):
        raise SystemExit(f"explicit entity repair failed: {corrected}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "dialogue.json"
        dialogue.save(str(path))
        restored = CRMSDialogue.load(kb, str(path))
        repaired_again = restored.turn("No, I meant the Engine.")
    if (repaired_again.status != "answered"
            or repaired_again.resolved_question != "Who designed the Engine?"
            or repaired_again.response is None
            or repaired_again.response.answer != "Ada"):
        raise SystemExit(f"persisted repair context failed: {repaired_again}")

    before = restored.last_question
    unsupported = restored.turn("I meant the Observatory.")
    if (unsupported.status != "unknown"
            or "already present" not in unsupported.text
            or restored.last_question != before):
        raise SystemExit("unsupported correction changed grounded dialogue state")

    ambiguous_kb = CRMSKnowledgeBase()
    for subject, obj in (("Ada", "Engine"), ("Grace", "Compiler"),
                         ("Grace", "Engine"), ("Ada", "Grace")):
        ambiguous_kb.add_fact(subject, "designed", obj,
                              f"source:{subject}:{obj}")
    for subject, obj in (("Ada", "Engine"), ("Grace", "Compiler")):
        ambiguous_kb.teach_polar_question(
            f"Did {subject} design the {obj}?", subject=subject,
            relation="designed", obj=obj, answer=True)
    ambiguous_dialogue = CRMSDialogue(ambiguous_kb)
    if ambiguous_dialogue.turn("Did Ada design the Engine?").status != "answered":
        raise SystemExit("grounded polar question did not answer")
    ambiguous_repair = ambiguous_dialogue.turn("I meant Grace.")
    if (ambiguous_repair.status != "unknown"
            or "multiple entities" not in ambiguous_repair.text):
        raise SystemExit("ambiguous entity correction guessed a role")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        dialogue_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        rule_session_path = root / "rule-session.json"
        cli_kb = build_knowledge()
        cli_kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(dialogue_path), "--rules", str(rules_path),
             "--rule-session", str(rule_session_path)],
            input=("Who designed the Engine?\n"
                   "Actually, I meant the Compiler.\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Ada designed Engine." not in process.stdout
                or "Grace designed Compiler." not in process.stdout):
            raise SystemExit(f"terminal dialogue correction failed:\n{process.stdout}")

    print("dialogue entity repair diagnostic: PASS")
    print("explicit correction, re-answering, persistence, unknown-entity abstention, ambiguous-role abstention, terminal routing: PASS")


if __name__ == "__main__":
    main()
