"""Check bounded reverse path search between grounded endpoints.

Run from the project root with:
    python3 experiments/v1_53_goal_directed_path_lookup.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_proof import verify_fact_path
from crms_research import CRMSResearchIndex


def main() -> None:
    kb = CRMSKnowledgeBase()
    context = {"period": "1840s"}
    kb.add_fact("Ada Lovelace", "designed", "Engine", "source:engine",
                qualifiers=context)
    kb.add_fact("Engine", "used", "Steam", "source:engine-steam",
                qualifiers=context)
    kb.add_fact("Ada Lovelace", "designed", "Boiler", "source:boiler",
                qualifiers=context)
    kb.add_fact("Boiler", "used", "Steam", "source:boiler-steam",
                qualifiers=context)
    kb.add_fact("Boiler", "used", "Electricity", "source:boiler-electric",
                qualifiers=context)

    facts = [fact.__dict__ for fact in kb.facts()]
    result = kb.ask_path_between(
        "Ada Lovelace", "Steam", ["designed", "used"], qualifiers=context)
    if (result.status != "answered" or result.answer != "yes"
            or result.truth is not True or len(result.proofs or []) != 2):
        raise SystemExit(f"reverse lookup missed supported endpoint paths: {result}")
    for proof in result.proofs or []:
        checked = verify_fact_path(
            proof, facts, start="Ada Lovelace",
            relations=["designed", "used"], answer="Steam", qualifiers=context)
        if not checked.valid:
            raise SystemExit(f"reverse search returned an invalid proof: {checked}")
    if {source for row in result.proofs for step in row
            for source in step["sources"]} != {
                "source:engine", "source:engine-steam",
                "source:boiler", "source:boiler-steam"}:
        raise SystemExit("reverse path proofs lost source provenance")

    missing = kb.ask_path_between(
        "Ada Lovelace", "Gas", ["designed", "used"], qualifiers=context)
    if missing.status != "unknown" or missing.proofs:
        raise SystemExit(f"unsupported target did not abstain: {missing}")
    wrong_start = kb.ask_path_between(
        "Grace Hopper", "Steam", ["designed", "used"], qualifiers=context)
    if wrong_start.status != "unknown" or wrong_start.proofs:
        raise SystemExit(f"unconnected start did not abstain: {wrong_start}")
    wrong_context = kb.ask_path_between(
        "Ada Lovelace", "Steam", ["designed", "used"],
        qualifiers={"period": "1850s"})
    if wrong_context.status != "unknown" or wrong_context.proofs:
        raise SystemExit(f"unsupported qualifier did not abstain: {wrong_context}")

    limited = kb.ask_path_between(
        "Ada Lovelace", "Steam", ["designed", "used"],
        qualifiers=context, max_expansions=1)
    if limited.status != "unknown" or limited.proofs or "limit" not in (limited.request or ""):
        raise SystemExit(f"expansion-limit exhaustion was not an abstention: {limited}")
    try:
        kb.ask_path_between("Ada Lovelace", "Steam", [], max_expansions=1)
    except ValueError:
        pass
    else:
        raise SystemExit("empty relation path should be rejected")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        commands = [
            "/ask-path-between Ada Lovelace|Steam|designed>used|period=1840s",
            "/ask-path-between Ada Lovelace|Gas|designed>used|period=1840s",
            "/quit",
        ]
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rules", str(temp / "rules.json"),
             "--rule-session", str(temp / "rule-session.json")],
            input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("Answer: yes." not in process.stdout
                or "Proof 1:" not in process.stdout
                or "don't have a grounded answer" not in process.stdout):
            raise SystemExit(f"CLI path query output was incomplete:\n{process.stdout}")

    conflicted = CRMSKnowledgeBase()
    conflicted.add_fact("Ada Lovelace", "designed", "Engine", "source:design",
                        qualifiers=context)
    conflicted.add_fact("Engine", "used", "Steam", "source:positive",
                        qualifiers=context)
    conflicted.add_negative_fact("Engine", "used", "Steam", "source:negative",
                                 qualifiers=context)
    conflict_result = conflicted.ask_path_between(
        "Ada Lovelace", "Steam", ["designed", "used"], qualifiers=context)
    if (conflict_result.status != "ambiguous" or conflict_result.truth is not None
            or "source:negative" not in str(conflict_result.evidence)):
        raise SystemExit(f"contradictory path evidence was treated as true: {conflict_result}")
    conflict_text = conflicted.render(conflict_result)
    if "source:negative" not in conflict_text or "evidence conflicts" not in conflict_text:
        raise SystemExit(f"path contradiction was not rendered with its source: {conflict_text}")
    print("goal-directed path lookup diagnostic: PASS")
    print("reverse traversal, multi-proof endpoints, proof checks, provenance, qualifiers, contradiction, abstention, limits, CLI: PASS")


if __name__ == "__main__":
    main()
