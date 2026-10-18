"""Check evidence-backed candidate inference-rule discovery and review flow."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_inference import discover_rule_candidates
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def seed_kb(*, include_counterexample: bool = True) -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    for start, middle, end in (("Ada", "Bea", "Cal"),
                               ("Dee", "Eli", "Fay")):
        kb.add_fact(start, "parent", middle, f"{start}:parent-1")
        kb.add_fact(middle, "parent", end, f"{middle}:parent-2")
        kb.add_fact(start, "ancestor", end, f"{start}:ancestor")
    if include_counterexample:
        kb.add_fact("Gus", "parent", "Hal", "Gus:parent-1")
        kb.add_fact("Hal", "parent", "Ivy", "Hal:parent-2")
        kb.add_negative_fact("Gus", "ancestor", "Ivy", "Gus:not-ancestor")
    return kb


def main() -> None:
    kb = seed_kb()
    discovery = kb.discover_inference_rules(min_support=2)
    candidate = next((item for item in discovery.candidates
                      if (item.first_relation, item.second_relation,
                          item.conclusion_relation) == ("parent", "parent", "ancestor")), None)
    if candidate is None or candidate.status != "contradicted":
        raise SystemExit(f"supported-but-falsified chain was not surfaced: {discovery}")
    if len(candidate.positive_examples) != 2 or len(candidate.negative_examples) != 1:
        raise SystemExit(f"candidate evidence counts are wrong: {candidate}")
    if kb._inference_rules:
        raise SystemExit("candidate discovery silently installed a rule")

    same_document = CRMSKnowledgeBase()
    for start, middle, end in (("Ada", "Bea", "Cal"),
                               ("Dee", "Eli", "Fay")):
        same_document.add_fact(start, "parent", middle,
                               f"source:parents#section-{start}")
        same_document.add_fact(middle, "parent", end,
                               f"source:parents#section-{middle}")
        same_document.add_fact(start, "ancestor", end,
                               f"source:parents#label-{start}")
    same_document_candidate = next(
        (item for item in same_document.discover_inference_rules().candidates
         if (item.first_relation, item.second_relation,
             item.conclusion_relation) == ("parent", "parent", "ancestor")), None)
    if (same_document_candidate is None
            or same_document_candidate.status
            != "insufficient-independent-sources"
            or same_document_candidate.independent_sources != ("source:parents",)):
        raise SystemExit("same-document examples were treated as independent rule support")

    one_example = CRMSKnowledgeBase()
    one_example.add_fact("Ada", "parent", "Bea", "s1")
    one_example.add_fact("Bea", "parent", "Cal", "s2")
    one_example.add_fact("Ada", "ancestor", "Cal", "s3")
    if one_example.discover_inference_rules(min_support=2).candidates:
        raise SystemExit("one observed endpoint pair passed the support threshold")
    incomplete = kb.discover_inference_rules(min_support=2, max_expansions=1)
    if incomplete.complete:
        raise SystemExit("limited rule discovery was reported complete")
    if any(item.status != "incomplete" for item in incomplete.candidates):
        raise SystemExit("partial search candidate was presented as fully evaluated")

    # Sparse joins should scale with matching edges, not all fact pairs.
    sparse_facts = []
    for number in range(12_000):
        sparse_facts.append({"subject": f"left-{number}", "relation": "edge-a",
                             "object": f"middle-{number}", "sources": [f"left:{number}"]})
        sparse_facts.append({"subject": f"other-{number}", "relation": "edge-b",
                             "object": f"end-{number}", "sources": [f"right:{number}"]})
    for start, middle, end, source in (
            ("Ada", "Bea", "Cal", "paper:one"),
            ("Dee", "Eli", "Fay", "paper:two")):
        sparse_facts.extend((
            {"subject": start, "relation": "parent", "object": middle,
             "sources": [source]},
            {"subject": middle, "relation": "parent", "object": end,
             "sources": [source]},
            {"subject": start, "relation": "ancestor", "object": end,
             "sources": [source]},
        ))
    for number in range(12_000):
        sparse_facts.append({
            "subject": "Ada", "relation": "ancestor", "object": "Cal",
            "qualifiers": {"year": str(1900 + number)},
            "sources": [f"dated-label:{number}"],
        })
    sparse = discover_rule_candidates(sparse_facts, min_support=2,
                                      max_expansions=10)
    sparse_rule = next((item for item in sparse.candidates
                        if (item.first_relation, item.second_relation,
                            item.conclusion_relation)
                        == ("parent", "parent", "ancestor")), None)
    if (not sparse.complete or sparse.expansions != 2 or sparse_rule is None
            or len(sparse_rule.positive_examples) != 2):
        raise SystemExit(f"sparse indexed discovery failed: {sparse}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        knowledge_path = root / "knowledge.json"
        index_path = root / "index.json"
        state_path = root / "dialogue.json"
        rules_path = root / "list-rules.json"
        session_path = root / "rule-session.json"
        kb.save(knowledge_path)
        CRMSResearchIndex().save(index_path)
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(knowledge_path), "--index", str(index_path),
               "--dialogue-state", str(state_path), "--rules", str(rules_path),
               "--rule-session", str(session_path)]
        output = subprocess.run(
            cli, input="/suggest-inference-rules\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("Candidate [contradicted]: parent then parent entails ancestor" not in output
                or "Gus:not-ancestor" not in output):
            raise SystemExit(f"CLI did not render candidate evidence:\n{output}")
        saved = json.loads(knowledge_path.read_text(encoding="utf-8"))
        if saved.get("inference_rules"):
            raise SystemExit("suggestion command persisted an unreviewed rule")
    print("rule candidate discovery diagnostic: PASS")
    print("support threshold, explicit counterexample, sparse 36k-fact exact-scope join, bounded-search label, non-installation, CLI review: PASS")


if __name__ == "__main__":
    main()
