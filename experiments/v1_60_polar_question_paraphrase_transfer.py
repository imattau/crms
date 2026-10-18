"""Check wording transfer for grounded yes/no relation questions.

Run from the project root with:
    python3 experiments/v1_60_polar_question_paraphrase_transfer.py
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
    kb.add_negative_fact("Grace Hopper", "designed", "Compiler", "source:grace-negative")
    kb.add_fact("Katherine Johnson", "designed", "Trajectory Table", "source:katherine")
    kb.add_fact("Eve Example", "operated", "Test Craft", "source:eve")

    if kb.teach_polar_question(
            "Did Ada Lovelace design the Engine?", subject="Ada Lovelace",
            relation="designed", obj="Engine", answer=True):
        raise SystemExit("one canonical polar example licensed too early")
    if not kb.teach_polar_question(
            "Did Grace Hopper design the Compiler?", subject="Grace Hopper",
            relation="designed", obj="Compiler", answer=False):
        raise SystemExit("two grounded polar examples did not license relation")

    if not kb.teach_polar_question(
            "Was the Compiler designed by Grace Hopper?", subject="Grace Hopper",
            relation="designed", obj="Compiler", answer=False):
        raise SystemExit("licensed relation did not transfer to passive wording")
    passive_yes = kb.ask("Was the Engine designed by Ada Lovelace?")
    passive_no = kb.ask("Was the Compiler designed by Grace Hopper?")
    if passive_yes.status != "answered" or passive_yes.truth is not True:
        raise SystemExit(f"passive wording failed to retrieve positive fact: {passive_yes}")
    if passive_no.status != "answered" or passive_no.truth is not False:
        raise SystemExit(f"passive wording failed to retrieve negative fact: {passive_no}")
    missing = kb.ask("Was the Engine designed by Grace Hopper?")
    if missing.status != "unknown":
        raise SystemExit(f"missing proposition was treated as false: {missing}")
    unseen = kb.ask("Could Ada Lovelace have designed the Engine?")
    if unseen.status != "unknown":
        raise SystemExit(f"unseen wording generalized without teaching: {unseen}")

    if kb.teach_polar_question(
            "Was the Test Craft operated by Eve Example?", subject="Eve Example",
            relation="operated", obj="Test Craft", answer=True):
        raise SystemExit("new relation borrowed unrelated yes/no frame evidence")
    if kb.ask("Was the Test Craft operated by Eve Example?").status != "unknown":
        raise SystemExit("unlicensed yes/no relation frame generalized")

    ambiguous_kb = CRMSKnowledgeBase()
    ambiguous_kb.add_fact("Alice", "designed", "Engine", "source:design-alice")
    ambiguous_kb.add_fact("Bob", "designed", "Device", "source:design-bob")
    ambiguous_kb.add_fact("Carol", "owned", "Engine", "source:own-carol")
    ambiguous_kb.add_fact("Dave", "owned", "Device", "source:own-dave")
    for question, subject, relation, obj in (
            ("Did Alice design Engine?", "Alice", "designed", "Engine"),
            ("Did Bob design Device?", "Bob", "designed", "Device"),
            ("Did Carol own Engine?", "Carol", "owned", "Engine"),
            ("Did Dave own Device?", "Dave", "owned", "Device")):
        ambiguous_kb.teach_polar_question(
            question, subject=subject, relation=relation, obj=obj, answer=True)
    ambiguous_kb.teach_polar_question(
        "Was the Engine handled by Alice?", subject="Alice",
        relation="designed", obj="Engine", answer=True)
    ambiguous_kb.teach_polar_question(
        "Was the Engine handled by Carol?", subject="Carol",
        relation="owned", obj="Engine", answer=True)
    semantic_ambiguity = ambiguous_kb.ask("Was the Engine handled by Alice?")
    if (semantic_ambiguity.status != "ambiguous"
            or "multiple relations" not in (semantic_ambiguity.request or "")):
        raise SystemExit(f"overlapping relation wordings were not surfaced: {semantic_ambiguity}")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        rules_path = temp / "rules.json"
        session_path = temp / "rule-session.json"
        kb.save(knowledge_path)
        loaded = CRMSKnowledgeBase.load(knowledge_path).ask(
            "Was the Engine designed by Ada Lovelace?")
        if loaded.status != "answered" or loaded.truth is not True:
            raise SystemExit(f"polar wording transfer did not persist: {loaded}")

        seed = CRMSKnowledgeBase()
        seed.add_fact("Ada Lovelace", "designed", "Engine", "source:ada")
        seed.add_negative_fact("Grace Hopper", "designed", "Compiler", "source:grace-negative")
        seed.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        commands = [
            "/teach-polar Did Ada Lovelace design Engine?|Ada Lovelace|designed|Engine|yes",
            "/teach-polar Did Grace Hopper design Compiler?|Grace Hopper|designed|Compiler|no",
            "/teach-polar Was the Compiler designed by Grace Hopper?|Grace Hopper|designed|Compiler|no",
            "Was the Engine designed by Ada Lovelace?",
            "/quit",
        ]
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        process = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "CRMS> Yes." not in process.stdout:
            raise SystemExit(f"CLI did not answer transferred polar wording:\n{process.stdout}")

    print("polar question paraphrase transfer: PASS")
    print("relation license, passive syntax, positive/negative evidence, open-world unknown, wording gate, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
