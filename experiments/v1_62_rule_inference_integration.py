"""Exercise explicit rule inference through CRMS storage and terminal chat."""

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
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "list-rules.json"
        session_path = root / "rule-session.json"

        kb = CRMSKnowledgeBase()
        kb.add_fact("Ada", "parent", "Bea", "source:one")
        kb.add_fact("Bea", "parent", "Cal", "source:two")
        kb.add_fact("Cal", "employed_by", "Acme", "source:three")
        kb.add_inference_rule("parent-transitivity", "parent", "parent", "ancestor")
        kb.add_inference_rule("ancestor-employer", "ancestor", "employed_by",
                              "ancestor_employed_by")
        kb.save(knowledge_path)
        loaded = CRMSKnowledgeBase.load(knowledge_path)
        result = loaded.infer_relation("Ada", "ancestor_employed_by", "Acme")
        if result.status != "answered" or not result.proofs:
            raise SystemExit(f"inference did not survive knowledge save/load: {result}")

        CRMSResearchIndex().save(index_path)
        commands = ["/infer-relation Ada|ancestor_employed_by|Acme", "/quit"]
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        process = subprocess.run(
            cli, input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("Derived: Ada — ancestor_employed_by → Acme." not in process.stdout
                or "parent-transitivity" not in process.stdout
                or "ancestor-employer" not in process.stdout
                or "source:one" not in process.stdout
                or "source:two" not in process.stdout
                or "source:three" not in process.stdout):
            raise SystemExit(f"CLI omitted conclusion or proof provenance:\n{process.stdout}")
    print("rule inference integration diagnostic: PASS")
    print("knowledge persistence, recursive CLI query, both rules and all premise sources: PASS")


if __name__ == "__main__":
    main()
