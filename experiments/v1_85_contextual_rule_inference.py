"""Check exact-context inference over qualified facts and CLI access."""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_rule_proof import verify_inference_proof
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "parent", "Bea", "family:24-a",
                qualifiers={"year": "2024"})
    kb.add_fact("Bea", "parent", "Cal", "family:24-b",
                qualifiers={"year": "2024"})
    kb.add_fact("Ada", "parent", "Dee", "family:20-a",
                qualifiers={"year": "2020"})
    kb.add_fact("Dee", "parent", "Cal", "family:20-b",
                qualifiers={"year": "2020"})
    kb.add_fact("Eve", "parent", "Fox", "mixed:24",
                qualifiers={"year": "2024"})
    kb.add_fact("Fox", "parent", "Gia", "mixed:20",
                qualifiers={"year": "2020"})
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")

    in_2024 = kb.infer_relation(
        "Ada", "ancestor", "Cal", qualifiers={"year": "2024"})
    in_2020 = kb.infer_relation(
        "Ada", "ancestor", "Cal", qualifiers={"year": "2020"})
    if in_2024.status != "answered" or in_2020.status != "answered":
        raise SystemExit("same-scope qualified premises did not infer")
    if kb.infer_relation("Ada", "ancestor", "Cal").status != "unknown":
        raise SystemExit("qualified premises leaked into an unqualified query")
    if kb.infer_relation("Eve", "ancestor", "Gia",
                         qualifiers={"year": "2024"}).status != "unknown":
        raise SystemExit("rule inference combined facts from different years")
    if kb.infer_relation("Ada", "ancestor", "Cal",
                         qualifiers={"year": "2028"}).status != "unknown":
        raise SystemExit("missing contextual evidence was not left unknown")

    kb.add_negative_fact("Ada", "ancestor", "Cal", "counter:20",
                         qualifiers={"year": "2020"})
    if kb.infer_relation("Ada", "ancestor", "Cal",
                         qualifiers={"year": "2024"}).status != "answered":
        raise SystemExit("negative evidence leaked across qualifier scopes")
    if kb.infer_relation("Ada", "ancestor", "Cal",
                         qualifiers={"year": "2020"}).status != "ambiguous":
        raise SystemExit("same-scope negative evidence did not create conflict")

    tampered = copy.deepcopy(in_2024.proofs[0])

    def alter_leaf(node: dict) -> bool:
        if node.get("kind") == "fact":
            node["fact"]["qualifiers"] = [("year", "2020")]
            return True
        return any(alter_leaf(premise) for premise in node.get("premises", []))

    alter_leaf(tampered)
    if verify_inference_proof(
            tampered, [fact.__dict__ for fact in kb.facts()],
            [rule.__dict__ for rule in kb._inference_rules.values()],
            expected_conclusion=in_2024.conclusion,
            expected_qualifiers={"year": "2024"}).valid:
        raise SystemExit("proof checker accepted a premise from another scope")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input=("/infer-relation Ada|ancestor|Cal|year=2024\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if ("Derived: Ada — ancestor → Cal." not in process.stdout
                or "[context: year=2024]" not in process.stdout):
            raise SystemExit(f"contextual inference CLI failed:\n{process.stdout}")

    print("contextual rule inference diagnostic: PASS")
    print("exact-scope joins, no cross-context leakage, scoped conflict, proof verification, CLI: PASS")


if __name__ == "__main__":
    main()
