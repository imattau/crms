"""Check read-only fact exclusion and path dependency reporting.

Run from the project root with:
    python3 experiments/v1_55_fact_path_counterfactual.py
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


def snapshot(kb: CRMSKnowledgeBase) -> tuple[object, ...]:
    return tuple(kb.facts()), tuple(kb.negative_facts())


def main() -> None:
    kb = CRMSKnowledgeBase()
    first = kb.add_fact("Origin", "r1", "Route A", "source:a1")
    kb.add_fact("Route A", "r2", "Target", "source:a2")
    kb.add_fact("Origin", "r1", "Route B", "source:b1")
    kb.add_fact("Route B", "r2", "Target", "source:b2")
    unrelated = kb.add_fact("Elsewhere", "r1", "Other", "source:other")

    before = snapshot(kb)
    alternative = kb.counterfactual_path_between(
        "Origin", "Target", (relation for relation in ["r1", "r2"]),
        excluded_fact=first)
    if (alternative.status != "supported" or alternative.supported is not True
            or alternative.baseline.status != "answered"
            or len(alternative.counterfactual.proofs or []) != 1):
        raise SystemExit(f"alternative path was not retained: {alternative}")
    if snapshot(kb) != before:
        raise SystemExit("counterfactual exclusion mutated the original fact store")
    again = kb.ask_path_between("Origin", "Target", ["r1", "r2"])
    if again.status != "answered" or len(again.proofs or []) != 2:
        raise SystemExit("original query changed after counterfactual evaluation")

    single = CRMSKnowledgeBase()
    single_first = single.add_fact("Origin", "r1", "Middle", "source:one")
    single.add_fact("Middle", "r2", "Target", "source:two")
    single_before = snapshot(single)
    removed_support = single.counterfactual_path_between(
        "Origin", "Target", ["r1", "r2"], excluded_fact=single_first)
    if (removed_support.status != "unsupported"
            or removed_support.supported is not False
            or removed_support.counterfactual.status != "unknown"):
        raise SystemExit(f"necessary fact did not remove support: {removed_support}")
    if snapshot(single) != single_before:
        raise SystemExit("necessary-fact counterfactual mutated original store")

    not_cited = kb.counterfactual_path_between(
        "Origin", "Target", ["r1", "r2"], excluded_fact=unrelated)
    if not_cited.status != "fact_not_in_proof" or not_cited.counterfactual is not None:
        raise SystemExit(f"uncited exclusion was not rejected: {not_cited}")

    unknown = kb.counterfactual_path_between(
        "Origin", "Missing", ["r1", "r2"], excluded_fact=first)
    if unknown.status != "baseline_not_proven" or unknown.counterfactual is not None:
        raise SystemExit(f"unproven baseline was treated as a counterfactual: {unknown}")

    conflicted = CRMSKnowledgeBase()
    conflict_fact = conflicted.add_fact("Origin", "r1", "Target", "source:positive")
    conflicted.add_negative_fact("Origin", "r1", "Target", "source:negative")
    conflict = conflicted.counterfactual_path_between(
        "Origin", "Target", ["r1"], excluded_fact=conflict_fact)
    if conflict.status != "baseline_not_proven" or conflict.baseline.status != "ambiguous":
        raise SystemExit(f"conflicted baseline was not kept distinct: {conflict}")

    corroborated = CRMSKnowledgeBase()
    corroborated.add_fact("Origin", "r1", "Target", "source:alpha")
    corroborated.add_fact("Origin", "r1", "Target", "source:beta")
    corroborated_before = snapshot(corroborated)
    source_survives = corroborated.counterfactual_path_without_source(
        "Origin", "Target", ["r1"], source="source:alpha")
    if (source_survives.status != "supported"
            or source_survives.counterfactual.proofs[0][0]["sources"]
            != ("source:beta",)):
        raise SystemExit(f"remaining citation did not preserve the fact: {source_survives}")
    if snapshot(corroborated) != corroborated_before:
        raise SystemExit("source-level counterfactual mutated the original store")

    source_dependent = CRMSKnowledgeBase()
    source_dependent.add_fact("Origin", "r1", "Middle", "source:shared")
    source_dependent.add_fact("Middle", "r2", "Target", "source:shared")
    source_before = snapshot(source_dependent)
    source_removed = source_dependent.counterfactual_path_without_source(
        "Origin", "Target", ["r1", "r2"], source="source:shared")
    if (source_removed.status != "unsupported"
            or source_removed.counterfactual.status != "unknown"):
        raise SystemExit(f"sole source removal retained support: {source_removed}")
    if snapshot(source_dependent) != source_before:
        raise SystemExit("global source exclusion mutated the original store")

    source_not_cited = source_dependent.counterfactual_path_without_source(
        "Origin", "Target", ["r1", "r2"], source="source:absent")
    if (source_not_cited.status != "source_not_in_proof"
            or source_not_cited.counterfactual is not None):
        raise SystemExit(f"uncited source exclusion was not rejected: {source_not_cited}")

    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        knowledge_path = temp / "knowledge.json"
        index_path = temp / "index.json"
        cli_kb = CRMSKnowledgeBase()
        cli_kb.add_fact("Origin", "r1", "Target", "source:alpha")
        cli_kb.add_fact("Origin", "r1", "Target", "source:beta")
        cli_kb.add_fact("Origin 2", "r1", "Middle 2", "source:needed")
        cli_kb.add_fact("Middle 2", "r2", "Target 2", "source:needed")
        cli_kb.save(knowledge_path)
        before_cli = snapshot(cli_kb)
        CRMSResearchIndex().save(index_path)
        commands = [
            "/counterfactual-path-without-source Origin|Target|r1|source:alpha",
            "/counterfactual-path-without-source Origin 2|Target 2|r1>r2|source:needed",
            "/counterfactual-path-without-source Origin|Target|r1|source:absent",
            "/quit",
        ]
        process = subprocess.run(
            [sys.executable, str(PROJECT / "crms_chat.py"),
             "--knowledge", str(knowledge_path), "--index", str(index_path),
             "--dialogue-state", str(temp / "dialogue.json"),
             "--rules", str(temp / "rules.json"),
             "--rule-session", str(temp / "rule-session.json")],
            input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=True, timeout=20)
        if ("remains supported without source source:alpha" not in process.stdout
                or "source:beta" not in process.stdout
                or "no longer supported without source source:needed" not in process.stdout
                or "does not support the baseline proof" not in process.stdout):
            raise SystemExit(f"source counterfactual CLI output was incomplete:\n{process.stdout}")
        if snapshot(CRMSKnowledgeBase.load(knowledge_path)) != before_cli:
            raise SystemExit("terminal counterfactual changed the persisted knowledge store")

    print("fact-path counterfactual diagnostic: PASS")
    print("fact/source exclusion, retained/lost support, invalid baselines, read-only API and CLI: PASS")


if __name__ == "__main__":
    main()
