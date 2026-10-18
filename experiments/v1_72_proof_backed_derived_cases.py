"""Check explicit practice and lineage-validated derived-case memory.

Run from the project root with:
    python3 experiments/v1_72_proof_backed_derived_cases.py
"""

from __future__ import annotations

import sys
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "designed", "Engine", "source:ada")
    kb.add_fact("Engine", "located in", "London", "source:engine")
    kb.add_inference_rule("design-location", "designed", "located in",
                          "designed in")
    original_facts = kb.facts()

    practiced = kb.practice_relation("Ada", "designed in", "London")
    if practiced.status != "answered":
        raise SystemExit("practice did not produce a verified inference")
    if kb.facts() != original_facts or len(kb.facts()) != 2:
        raise SystemExit("derived conclusion was promoted into source facts")
    if kb.practice_relation("Ada", "designed in", "London").status != "answered":
        raise SystemExit("repeat practice failed")
    cases = kb.derived_cases()
    if len(cases) != 1 or cases[0]["practice_count"] != 2:
        raise SystemExit("repeated derivations were not deduplicated")
    case = kb.retrieve_derived_case("Ada", "designed in", "London")
    if (case is None or case["status"] != "verified"
            or case["lineage"]["sources"] != ["source:ada", "source:engine"]
            or case["lineage"]["rule_ids"] != ["design-location"]):
        raise SystemExit("derived case lost proof lineage or failed retrieval")
    retrieval_count = kb._derived_cases[next(iter(kb._derived_cases))]["retrieval_count"]
    kb.derived_cases()
    if kb._derived_cases[next(iter(kb._derived_cases))]["retrieval_count"] != retrieval_count:
        raise SystemExit("listing cases incorrectly counted as artifact reuse")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "knowledge.json"
        kb.save(path)
        restored = CRMSKnowledgeBase.load(path)
        loaded = restored.retrieve_derived_case(
            "Ada", "designed in", "London")
        if loaded is None or loaded["status"] != "verified":
            raise SystemExit("derived case did not survive persistence")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "rules.json"
        session_path = root / "rule-session.json"
        cli_kb = CRMSKnowledgeBase()
        cli_kb.add_fact("Ada", "designed", "Engine", "source:ada")
        cli_kb.add_fact("Engine", "located in", "London", "source:engine")
        cli_kb.add_inference_rule("design-location", "designed", "located in",
                                  "designed in")
        cli_kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(state_path), "--rules", str(rules_path),
             "--rule-session", str(session_path)],
            input=("/practice-inference Ada|designed in|London\n"
                   "/derived-cases\n"
                   "/practice-inference Ada|designed|Engine\n/quit\n"),
            text=True, capture_output=True,
            check=True, timeout=20)
        if ("Verified derivation stored as a separate derived case." not in process.stdout
                or "Derived case [verified]: Ada — designed in → London" not in process.stdout
                or "No derived case stored: this result is directly taught." not in process.stdout):
            raise SystemExit(f"derived practice CLI flow failed:\n{process.stdout}")
        restored_cli = CRMSKnowledgeBase.load(knowledge_path)
        if (len(restored_cli.derived_cases()) != 1
                or len(restored_cli.facts()) != 2):
            raise SystemExit("CLI did not persist a separate derived case")

    kb.add_negative_fact("Ada", "designed in", "London", "source:counter")
    if kb.retrieve_derived_case("Ada", "designed in", "London") is not None:
        raise SystemExit("conflicted derived case was returned")
    if kb.derived_cases()[0]["status"] != "stale_or_conflicted":
        raise SystemExit("conflicted artifact was not marked unavailable")
    if kb.practice_relation("Ada", "unknown relation", "London").status != "unknown":
        raise SystemExit("unsupported conclusion was incorrectly practiced")

    print("proof-backed derived cases diagnostic: PASS")
    print("explicit practice, CLI, no fact promotion, lineage, dedupe, persistence, conflict abstention: PASS")


if __name__ == "__main__":
    main()
