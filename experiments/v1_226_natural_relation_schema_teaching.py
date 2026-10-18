"""Check explicit relation-schema teaching through ordinary CRMS language."""
from __future__ import annotations

from dataclasses import asdict
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex
from crms_rule_proof import verify_inference_proof


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-natural-schema-") as tmp:
        root = Path(tmp)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        rules_path = root / "rules.json"
        kb = CRMSKnowledgeBase()
        kb.add_fact("A", "precedes", "B", "source:ab")
        kb.add_fact("B", "precedes", "C", "source:bc")
        kb.add_fact("Dee", "collaborates with", "Cal", "source:dc")
        kb.add_fact("Ann", "works for", "Acme", "source:ann-acme")
        kb.add_fact("Ann", "works for", "Beta", "source:ann-beta")
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)

        process = subprocess.run(
            [sys.executable, str(ROOT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(rules_path),
             "--rule-session", str(root / "rule-session.json")],
            input=('Teach CRMS that the relation "precedes" is transitive.\n'
                   'Please teach that the relation "collaborates with" is symmetric.\n'
                   'Teach CRMS that the relation "works for" is functional.\n'
                   '/quit\n'),
            text=True, capture_output=True, check=False, timeout=30)
        require(process.returncode == 0
                and "precedes is transitive" in process.stdout
                and "collaborates with is symmetric" in process.stdout
                and "works for is functional" in process.stdout,
                f"natural schema teaching failed in chat:\n{process.stdout}\n{process.stderr}")

        restored = CRMSKnowledgeBase.load(knowledge_path)
        transitive = restored.infer_relation("A", "precedes", "C")
        symmetric = restored.infer_relation(
            "Cal", "collaborates with", "Dee")
        functional = restored.infer_relation("Ann", "works for", "Acme")
        require(transitive.status == "answered" and transitive.proofs
                and "conversation:natural-language-relation-schema"
                in transitive.source_documents,
                f"natural transitive teaching was not persisted or applied: {transitive}")
        require(symmetric.status == "answered" and symmetric.proofs
                and "conversation:natural-language-relation-schema"
                in symmetric.source_documents,
                f"natural symmetric teaching was not persisted or applied: {symmetric}")
        require(functional.status == "ambiguous"
                and functional.reason_code == "integrity_conflict",
                f"natural functional teaching was not persisted or applied: {functional}")
        for result in (transitive, symmetric):
            for proof in result.proofs:
                check = verify_inference_proof(
                    proof, [asdict(fact) for fact in restored.facts()],
                    [asdict(rule) for rule in restored._inference_rules.values()],
                    expected_conclusion=result.conclusion)
                require(check.valid, f"natural-language schema proof failed verification: {check}")

    print("natural-language relation-schema teaching: PASS")
    print("transitivity, symmetry, functionality, persistence, provenance, and proof verification: PASS")


if __name__ == "__main__":
    main()
