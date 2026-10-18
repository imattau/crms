"""Check one-example wording transfer from a licensed canonical relation.

Run from the project root with:
    python3 experiments/v1_58_grounded_question_paraphrase_transfer.py
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
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "designed", "Engine", "source:ada")
    kb.add_fact("Grace Hopper", "designed", "Compiler", "source:grace")
    kb.add_fact("Katherine Johnson", "designed", "Trajectory Table", "source:katherine")
    kb.add_fact("Eve Example", "piloted", "Test Craft", "source:eve")

    if kb.teach_question(
            "Who designed the Engine?", relation="designed",
            answer_field="subject", bound_entity="Engine",
            answer="Ada Lovelace"):
        raise SystemExit("first canonical frame example licensed too early")
    if not kb.teach_question(
            "Who designed the Compiler?", relation="designed",
            answer_field="subject", bound_entity="Compiler",
            answer="Grace Hopper"):
        raise SystemExit("two canonical question examples did not license")

    if not kb.teach_question(
            "Who built the Trajectory Table?", relation="designed",
            answer_field="subject", bound_entity="Trajectory Table",
            answer="Katherine Johnson"):
        raise SystemExit("known relation did not transfer to one grounded wording example")
    transferred = kb.ask("Who built the Engine?")
    if transferred.status != "answered" or transferred.answer != "Ada Lovelace":
        raise SystemExit(f"new exact wording did not transfer to a stored fact: {transferred}")
    unseen = kb.ask("Who engineered the Engine?")
    if unseen.status != "unknown":
        raise SystemExit(f"unseen wording was inferred without a teaching example: {unseen}")
    unknown_entity = kb.ask("Who built the Unknown Device?")
    if unknown_entity.status != "unknown" or not unknown_entity.matched_templates:
        raise SystemExit(f"learned wording did not abstain for missing facts: {unknown_entity}")

    if kb.teach_question(
            "Who operated the Test Craft?", relation="piloted",
            answer_field="subject", bound_entity="Test Craft",
            answer="Eve Example"):
        raise SystemExit("a new canonical relation borrowed unrelated relation evidence")
    unrelated = kb.ask("Who operated the Unknown Craft?")
    if unrelated.status != "unknown":
        raise SystemExit(f"unlicensed relation wording generalized: {unrelated}")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        rules_path = temp / "rules.json"
        session_path = temp / "rule-session.json"
        kb.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        loaded = restored.ask("Who built the Engine?")
        if loaded.status != "answered" or loaded.answer != "Ada Lovelace":
            raise SystemExit(f"transferred wording did not persist: {loaded}")

        seed = CRMSKnowledgeBase()
        for fact in (("Ada Lovelace", "designed", "Engine", "source:ada"),
                     ("Grace Hopper", "designed", "Compiler", "source:grace"),
                     ("Katherine Johnson", "designed", "Trajectory Table", "source:katherine")):
            seed.add_fact(*fact)
        seed.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        commands = [
            "/teach-question Who designed the Engine?|designed|subject|Engine|Ada Lovelace",
            "/teach-question Who designed the Compiler?|designed|subject|Compiler|Grace Hopper",
            "/teach-question Who built the Trajectory Table?|designed|subject|Trajectory Table|Katherine Johnson",
            "Who built the Engine?",
            "/quit",
        ]
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("Question frame licensed." not in process.stdout
                or "Answer: Ada Lovelace." not in process.stdout):
            raise SystemExit(f"CLI did not perform grounded wording transfer:\n{process.stdout}")

    print("grounded question paraphrase transfer: PASS")
    print("licensed relation reuse, one-example new frame, fact-backed transfer, unseen wording/unknown abstention, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
