"""Practice, persist, and reuse derived proofs in exact qualifier scopes."""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def add_context(kb: CRMSKnowledgeBase, year: str) -> None:
    scope = {"year": year}
    kb.add_fact("Ada", "parent", "Bea", f"family:{year}#p1",
                qualifiers=scope)
    kb.add_fact("Bea", "parent", "Cal", f"family:{year}#p2",
                qualifiers=scope)


def main() -> None:
    kb = CRMSKnowledgeBase()
    add_context(kb, "2024")
    add_context(kb, "2025")
    kb.add_fact("Cal", "located in", "Rome", "location:2024",
                qualifiers={"year": "2024"})
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    kb.add_inference_rule("ancestor-city", "ancestor", "located in",
                          "family located in")

    for year in ("2024", "2025"):
        practiced = kb.practice_relation(
            "Ada", "ancestor", "Cal", qualifiers={"year": year})
        if practiced.status != "answered":
            raise SystemExit(f"contextual practice failed for {year}: {practiced}")
    cases = kb.derived_cases()
    if (len(cases) != 2
            or {tuple(tuple(pair) for pair in case["qualifiers"])
                for case in cases} != {(('year', '2024'),), (('year', '2025'),)}):
        raise SystemExit("derived cases collapsed distinct qualifier scopes")

    reused = kb.infer_relation(
        "Ada", "family located in", "Rome", qualifiers={"year": "2024"})
    baseline = copy.deepcopy(kb)
    baseline._derived_cases.clear()
    recomputed = baseline.infer_relation(
        "Ada", "family located in", "Rome", qualifiers={"year": "2024"})
    if (reused.status != "answered" or recomputed.status != "answered"
            or reused.expansions >= recomputed.expansions):
        raise SystemExit("contextual derived proof was not reused as an intermediate")
    if kb.infer_relation("Ada", "family located in", "Rome",
                         qualifiers={"year": "2025"}).status != "unknown":
        raise SystemExit("derived subgoal crossed into a different context")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        restored = CRMSKnowledgeBase.load(knowledge_path)
        loaded = restored.retrieve_derived_case(
            "Ada", "ancestor", "Cal", qualifiers={"year": "2024"})
        wrong_scope = restored.retrieve_derived_case(
            "Ada", "ancestor", "Cal", qualifiers={"year": "2026"})
        if loaded is None or loaded["status"] != "verified" or wrong_scope is not None:
            raise SystemExit("contextual derived-case persistence/retrieval failed")
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(root / "dialogue.json"),
             "--rules", str(root / "rules.json")],
            input=("/practice-inference Ada|ancestor|Cal|year=2024\n"
                   "/derived-cases\n/quit\n"),
            text=True, capture_output=True, check=True, timeout=20)
        if "context: year=2024" not in process.stdout:
            raise SystemExit(f"CLI omitted contextual derived-case scope:\n{process.stdout}")

    kb.add_negative_fact("Ada", "ancestor", "Cal", "counter:2025",
                         qualifiers={"year": "2025"})
    if kb.retrieve_derived_case(
            "Ada", "ancestor", "Cal", qualifiers={"year": "2025"}) is not None:
        raise SystemExit("conflicted contextual artifact remained available")
    valid_2024 = kb.retrieve_derived_case(
        "Ada", "ancestor", "Cal", qualifiers={"year": "2024"})
    if valid_2024 is None or valid_2024["status"] != "verified":
        raise SystemExit("conflict in one scope invalidated a different scope")

    print("contextual derived practice diagnostic: PASS")
    print("scope-specific storage, persistence, query/subgoal reuse, CLI, isolated conflict invalidation: PASS")


if __name__ == "__main__":
    main()
