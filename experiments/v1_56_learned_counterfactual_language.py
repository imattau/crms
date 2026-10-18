"""Check learned language frames for source-level path counterfactuals.

Run from the project root with:
    python3 experiments/v1_56_learned_counterfactual_language.py
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


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Origin", "r1", "Middle", "archive-a")
    kb.add_fact("Origin", "r1", "Middle", "archive-b")
    kb.add_fact("Middle", "r2", "Target", "archive-c")
    q_a = ("Would Target still be reachable from Origin via r1 then r2 "
           "if archive-a were removed?")
    q_b = ("Would Target still be reachable from Origin via r1 then r2 "
           "if archive-b were removed?")
    q_c = ("Would Target still be reachable from Origin via r1 then r2 "
           "if archive-c were removed?")

    if kb.teach_counterfactual_source_question(
            q_a, start="Origin", target="Target", relations=["r1", "r2"],
            source="archive-a"):
        raise SystemExit("one source example should not license a variable frame")
    if not kb.teach_counterfactual_source_question(
            q_b, start="Origin", target="Target", relations=["r1", "r2"],
            source="archive-b"):
        raise SystemExit("two distinct source examples did not license the frame")

    retained = kb.ask_counterfactual_source_question(q_a)
    lost = kb.ask_counterfactual_source_question(q_c)
    if retained is None or retained.status != "supported":
        raise SystemExit(f"remaining source did not preserve support: {retained}")
    if lost is None or lost.status != "unsupported":
        raise SystemExit(f"held-out necessary source was not identified: {lost}")
    counterfactual_snapshot = []
    for fact in kb.facts():
        sources = tuple(source for source in fact.sources if source != "archive-a")
        if sources:
            counterfactual_snapshot.append(
                fact.__dict__ | {"sources": sources})
    for proof in retained.counterfactual.proofs or []:
        checked = verify_fact_path(
            proof, counterfactual_snapshot, start="Origin", relations=["r1", "r2"],
            answer="Target")
        if not checked.valid:
            raise SystemExit(f"learned counterfactual returned an invalid proof: {checked}")
    if kb.ask_counterfactual_source_question(
            "Could Target still be reachable from Origin via r1 then r2 "
            "if archive-c were removed?") is not None:
        raise SystemExit("unlearned question wording matched the frame")

    qualified = CRMSKnowledgeBase()
    context = {"period": "1840s"}
    qualified.add_fact("Origin", "r1", "Middle", "archive-a",
                       qualifiers=context)
    qualified.add_fact("Origin", "r1", "Middle", "archive-b",
                       qualifiers=context)
    qualified.add_fact("Middle", "r2", "Target", "archive-c",
                       qualifiers=context)
    qualified.add_fact("Origin", "r1", "Other", "archive-old-a",
                       qualifiers={"period": "1850s"})
    qualified.add_fact("Other", "r2", "Target", "archive-old-b",
                       qualifiers={"period": "1850s"})
    q_a_context = ("Would Target still be reachable from Origin via r1 then r2 "
                   "in period 1840s if archive-a were removed?")
    q_b_context = ("Would Target still be reachable from Origin via r1 then r2 "
                   "in period 1840s if archive-b were removed?")
    q_c_context = ("Would Target still be reachable from Origin via r1 then r2 "
                   "in period 1840s if archive-c were removed?")
    if qualified.teach_counterfactual_source_question(
            q_a_context, start="Origin", target="Target", relations=["r1", "r2"],
            source="archive-a", qualifiers=context):
        raise SystemExit("one contextual source example licensed too early")
    if not qualified.teach_counterfactual_source_question(
            q_b_context, start="Origin", target="Target", relations=["r1", "r2"],
            source="archive-b", qualifiers=context):
        raise SystemExit("contextual examples did not license the frame")
    context_result = qualified.ask_counterfactual_source_question(q_c_context)
    if context_result is None or context_result.status != "unsupported":
        raise SystemExit(f"learned qualifier did not constrain the path: {context_result}")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        state_path = temp / "dialogue.json"
        rules_path = temp / "rules.json"
        session_path = temp / "rule-session.json"
        qualified.save(knowledge_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        dialogue = CRMSDialogue(restored)
        dialogue_turn = dialogue.turn(q_c_context)
        if (dialogue_turn.status != "unsupported"
                or "no longer supported without source archive-c" not in dialogue_turn.text):
            raise SystemExit(f"dialogue did not answer learned frame: {dialogue_turn}")

        CRMSResearchIndex().save(index_path)
        train_commands = [
            f"/teach-counterfactual-source-question {q_a_context}|r1>r2|Origin|Target|archive-a|period=1840s",
            f"/teach-counterfactual-source-question {q_b_context}|r1>r2|Origin|Target|archive-b|period=1840s",
            "/quit",
        ]
        base_command = [
            sys.executable, str(PROJECT / "crms_chat.py"),
            "--knowledge", str(knowledge_path), "--index", str(index_path),
            "--dialogue-state", str(state_path), "--rules", str(rules_path),
            "--rule-session", str(session_path),
        ]
        trained = subprocess.run(
            base_command, input="\n".join(train_commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "Counterfactual source frame licensed." not in trained.stdout:
            raise SystemExit(f"CLI did not license the learned frame:\n{trained.stdout}")

        asked = subprocess.run(
            base_command, input=f"{q_c_context}\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20)
        if "no longer supported without source archive-c" not in asked.stdout:
            raise SystemExit(f"restarted CLI did not use the saved frame:\n{asked.stdout}")

    print("learned counterfactual language diagnostic: PASS")
    print("two-example licensing, qualifier binding, held-out source, wording gate, proof check, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
