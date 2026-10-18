"""Check multi-slot learned counterfactual frames across new path entities.

Run from the project root with:
    python3 experiments/v1_57_variable_endpoint_counterfactual_frames.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_dialogue import CRMSDialogue
from crms_knowledge import CRMSKnowledgeBase
from crms_proof import verify_fact_path
from crms_research import CRMSResearchIndex

PROJECT = Path(__file__).resolve().parents[1]


def question(target: str, start: str, source: str) -> str:
    return (f"Would {target} still be reachable from {start} via designed then uses "
            f"in 1840s if {source} were removed?")


def add_path(kb: CRMSKnowledgeBase, start: str, middle: str,
             target: str, first_source: str, second_source: str) -> None:
    context = {"period": "1840s"}
    kb.add_fact(start, "designed", middle, first_source, qualifiers=context)
    kb.add_fact(middle, "uses", target, second_source, qualifiers=context)


def generic_question(target: str, start: str, source: str) -> str:
    return f"Would {target} still be reachable from {start} if {source} were removed?"


def main() -> None:
    kb = CRMSKnowledgeBase()
    add_path(kb, "Ada Lovelace", "Engine", "Steam", "archive-a", "evidence-a")
    add_path(kb, "Grace Hopper", "Compiler", "Electricity", "archive-b", "evidence-b")
    add_path(kb, "Katherine Johnson", "Trajectory Table", "Solar",
             "archive-c", "evidence-c")
    context = {"period": "1840s"}
    first = question("Steam", "Ada Lovelace", "archive-a")
    second = question("Electricity", "Grace Hopper", "archive-b")
    held_out = question("Solar", "Katherine Johnson", "archive-c")

    if kb.teach_counterfactual_path_question(
            first, start="Ada Lovelace", target="Steam",
            relations=["designed", "uses"], source="archive-a",
            qualifiers=context):
        raise SystemExit("one example should not license the multi-slot frame")
    if not kb.teach_counterfactual_path_question(
            second, start="Grace Hopper", target="Electricity",
            relations=["designed", "uses"], source="archive-b",
            qualifiers=context):
        raise SystemExit("distinct start/target/source examples did not license frame")

    result = kb.ask_counterfactual_path_question(held_out)
    if result is None or result.status != "unsupported":
        raise SystemExit(f"held-out multi-slot binding failed: {result}")
    for proof in result.baseline.proofs or []:
        checked = verify_fact_path(
            proof, [fact.__dict__ for fact in kb.facts()],
            start="Katherine Johnson", relations=["designed", "uses"],
            answer="Solar", qualifiers=context)
        if not checked.valid:
            raise SystemExit(f"held-out baseline proof failed validation: {checked}")
    if kb.ask_counterfactual_path_question(
            "Could Solar still be reachable from Katherine Johnson via designed "
            "then uses in 1840s if archive-c were removed?") is not None:
        raise SystemExit("unlearned wording matched the multi-slot frame")

    ambiguous_kb = CRMSKnowledgeBase()
    for start, relation, target, source in (
            ("A1", "r1", "T1", "src-1"),
            ("A2", "r1", "T2", "src-2"),
            ("B1", "r2", "T3", "src-3"),
            ("B2", "r2", "T4", "src-4"),
            ("Shared", "r1", "End", "src-shared"),
            ("Shared", "r2", "End", "src-shared")):
        ambiguous_kb.add_fact(start, relation, target, source)
    for start, target, source in (("A1", "T1", "src-1"),
                                  ("A2", "T2", "src-2")):
        ambiguous_kb.teach_counterfactual_path_question(
            generic_question(target, start, source), start=start, target=target,
            relations=["r1"], source=source)
    for start, target, source in (("B1", "T3", "src-3"),
                                  ("B2", "T4", "src-4")):
        ambiguous_kb.teach_counterfactual_path_question(
            generic_question(target, start, source), start=start, target=target,
            relations=["r2"], source=source)
    ambiguous_result = ambiguous_kb.ask_counterfactual_path_question(
        generic_question("End", "Shared", "src-shared"))
    if ambiguous_result is None or ambiguous_result.status != "ambiguous_frame":
        raise SystemExit(f"overlapping learned frames did not abstain: {ambiguous_result}")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        rules_path = temp / "rules.json"
        session_path = temp / "rule-session.json"
        kb.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        dialogue_turn = CRMSDialogue(restored).turn(held_out)
        if (dialogue_turn.status != "unsupported"
                or "no longer supported without source archive-c" not in dialogue_turn.text):
            raise SystemExit(f"dialogue did not route multi-slot frame: {dialogue_turn}")

        CRMSResearchIndex().save(index_path)
        commands = [
            f"/teach-counterfactual-path-question {first}|designed>uses|Ada Lovelace|Steam|archive-a|period=1840s",
            f"/teach-counterfactual-path-question {second}|designed>uses|Grace Hopper|Electricity|archive-b|period=1840s",
            "/quit",
        ]
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        trained = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "Counterfactual path frame licensed." not in trained.stdout:
            raise SystemExit(f"CLI did not license multi-slot frame:\n{trained.stdout}")
        asked = subprocess.run(
            cli, input=f"{held_out}\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "no longer supported without source archive-c" not in asked.stdout:
            raise SystemExit(f"restarted CLI did not use multi-slot frame:\n{asked.stdout}")

    print("variable-endpoint counterfactual frame diagnostic: PASS")
    print("distinct-role licensing, endpoint/source transfer, qualifiers, proof validation, ambiguous-frame abstention, dialogue, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
