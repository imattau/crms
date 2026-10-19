"""Check explicit middle-kind indexing and independently verified guards."""

from __future__ import annotations

from dataclasses import asdict
import copy
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


PROJECT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Origin", "r1", "Zulu Relay", "r1:valid")
    kb.add_fact("Zulu Relay", "r2", "Target", "r2:valid")
    kb.add_fact("Zulu Relay", "is-a", "relay", "kind:relay")
    for index in range(12):
        middle = f"Middle {index:02d}"
        kb.add_fact("Origin", "r1", middle, f"r1:{index}")
        kb.add_fact(middle, "r2", "Target", f"r2:{index}")
        kb.add_fact(middle, "is-a", "unrelated", f"kind:{index}")
    rule = kb.add_inference_rule(
        "relay-rule", "r1", "r2", "reaches", middle_kind="relay")

    bounded = kb.infer_relation("Origin", "reaches", "Target", max_expansions=2)
    require(bounded.status == "answered" and bounded.complete
            and bounded.expansions == 2,
            f"kind index did not prune irrelevant middle entities: {bounded}")
    require(len(bounded.proofs) == 1
            and bounded.proofs[0].get("middle_kind_fact", {}).get("object") == "relay",
            "typed proof omitted its explicit kind evidence")
    require(bounded.source_documents == ("kind:relay", "r1:valid", "r2:valid"),
            "support lineage omitted the kind evidence source")
    checked = verify_inference_proof(
        bounded.proofs[0], [asdict(fact) for fact in kb.facts()],
        [asdict(rule)], expected_conclusion=bounded.conclusion)
    require(checked.valid, f"independent checker rejected typed proof: {checked}")

    forged = copy.deepcopy(bounded.proofs[0])
    forged["middle_kind_fact"]["object"] = "unrelated"
    rejected = verify_inference_proof(
        forged, [asdict(fact) for fact in kb.facts()], [asdict(rule)])
    require(not rejected.valid, "independent checker accepted a false middle-kind guard")
    missing = copy.deepcopy(bounded.proofs[0])
    del missing["middle_kind_fact"]
    rejected = verify_inference_proof(
        missing, [asdict(fact) for fact in kb.facts()], [asdict(rule)])
    require(not rejected.valid, "independent checker accepted a typed proof without kind evidence")
    untyped = CRMSKnowledgeBase()
    untyped.add_fact("Origin", "r1", "Zulu Relay", "r1:valid")
    untyped.add_fact("Zulu Relay", "r2", "Target", "r2:valid")
    for index in range(12):
        middle = f"Middle {index:02d}"
        untyped.add_fact("Origin", "r1", middle, f"r1:{index}")
        untyped.add_fact(middle, "r2", "Target", f"r2:{index}")
    untyped.add_inference_rule("plain-rule", "r1", "r2", "reaches")
    limited_baseline = untyped.infer_relation(
        "Origin", "reaches", "Target", max_expansions=2)
    require(limited_baseline.status == "answered"
            and not limited_baseline.complete
            and limited_baseline.reason_code == "search_limit"
            and limited_baseline.limit_kind == "expansion_limit"
            and limited_baseline.proofs,
            "untyped control should retain its proof and report incomplete support search")
    baseline = untyped.infer_relation("Origin", "reaches", "Target")
    require(baseline.status == "answered" and baseline.expansions > bounded.expansions,
            f"kind index did not reduce bounded search work: {baseline.expansions} vs "
            f"{bounded.expansions}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "typed.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        restored_result = restored.infer_relation(
            "Origin", "reaches", "Target", max_expansions=2)
        require(restored_result.status == "answered"
                and restored_result.proofs[0]["rule"].get("middle_kind") == "relay",
                "typed rule or its result did not survive save/load")

    kb.add_negative_fact("Zulu Relay", "is-a", "relay", "kind:counter")
    kind_conflict = kb.infer_relation("Origin", "reaches", "Target")
    require(kind_conflict.status == "ambiguous"
            and kind_conflict.support_class == "contested",
            "contradicted kind evidence was silently accepted")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        cli_state = root / "dialogue.json"
        cli_rules = root / "rules.json"
        cli_session = root / "rule-session.json"
        cli_kb = CRMSKnowledgeBase()
        cli_kb.add_fact("Origin", "r1", "Zulu Relay", "r1:valid")
        cli_kb.add_fact("Zulu Relay", "r2", "Target", "r2:valid")
        cli_kb.add_fact("Zulu Relay", "is-a", "relay", "kind:relay")
        cli_kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(cli_state), "--rules", str(cli_rules),
             "--rule-session", str(cli_session)],
            input=("/teach-inference-rule cli-relay|r1|r2|reaches|middle_kind=relay\n"
                   "/infer-relation Origin|reaches|Target\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        require("with middle kind relay." in process.stdout
                and "CRMS> Derived:" in process.stdout
                and "middle kind: Zulu Relay is-a relay [sources: kind:relay]"
                in process.stdout,
                f"typed rule CLI teaching/query failed:\n{process.stdout}")

    print("middle-kind index diagnostic: PASS")
    print(f"typed search: {bounded.expansions} expansions; untyped: {baseline.expansions}")
    print("explicit type pruning, proof guard verification, tamper rejection, bound exhaustion, persistence, CLI: PASS")


if __name__ == "__main__":
    main()
