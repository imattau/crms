"""Write a grounded digest containing a verified inferred relation."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


PROJECT = Path(__file__).resolve().parents[1]


def seed() -> CRMSKnowledgeBase:
    kb = CRMSKnowledgeBase()
    examples = (("Ada", "Bea", "Cal", "one"),
                ("Dee", "Eli", "Fay", "two"))
    for subject, middle, target, name in examples:
        kb.add_fact(subject, "parent", middle, f"{name}:parent-1")
        kb.add_fact(middle, "parent", target, f"{name}:parent-2")
        kb.add_fact(subject, "ancestor", target, f"{name}:ancestor")
    kb.add_inference_rule("parent-transitivity", "parent", "parent", "ancestor")
    kb.teach_fact_pattern(
        "Ada is an ancestor of Cal.", subject="Ada", relation="ancestor",
        obj="Cal", source="one:ancestor", predicate_phrase="is an ancestor of")
    kb.teach_fact_pattern(
        "Dee is an ancestor of Fay.", subject="Dee", relation="ancestor",
        obj="Fay", source="two:ancestor", predicate_phrase="is an ancestor of")
    kb.add_fact("Nia", "parent", "Oren", "three:parent-1")
    kb.add_fact("Oren", "parent", "Pia", "three:parent-2")
    return kb


def main() -> None:
    kb = seed()
    deduplicated = kb.write_about("Ada")
    ada_ancestor_sentences = [
        statement for statement in deduplicated.statements
        if statement["fact"]["relation"] == "ancestor"
        and statement["fact"]["object"] == "Cal"]
    if (len(ada_ancestor_sentences) != 1
            or ada_ancestor_sentences[0].get("inferred")):
        raise SystemExit(
            "an explicitly stored relation was repeated as a derived statement: "
            f"{ada_ancestor_sentences}")

    result = kb.write_about("Nia")
    inferred = [statement for statement in result.statements
                if statement.get("inferred")]
    if result.status != "partial" or len(inferred) != 1:
        raise SystemExit(f"derived statement was not composed with omissions tracked: {result}")
    statement = inferred[0]
    if (statement["fact"] != {"subject": "Nia", "relation": "ancestor", "object": "Pia"}
            or "parent-transitivity" not in statement["rules"]
            or not {"three:parent-1", "three:parent-2"}.issubset(statement["sources"])):
        raise SystemExit(f"derived writing lost its proof provenance: {statement}")
    if "Derived: Nia is an ancestor of Pia." not in result.text:
        raise SystemExit(f"derived statement was not marked in generated text:\n{result.text}")
    if any(fact.subject == "Nia" and fact.relation == "ancestor"
           for fact in kb.facts()):
        raise SystemExit("writing inserted its inferred conclusion into the fact store")

    kb.add_negative_fact("Nia", "ancestor", "Pia", "negative:source")
    conflict = kb.write_about("Nia")
    if (conflict.status != "ambiguous" or not conflict.conflicts
            or any(statement.get("fact", {}).get("relation") == "ancestor"
                   for statement in conflict.statements)):
        raise SystemExit(f"conflicting derived statement was written as fact: {conflict}")

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        paths = {name: root / name for name in (
            "knowledge.json", "index.json", "dialogue.json", "rules.json", "session.json")}
        cli_kb = seed()
        cli_kb.save(paths["knowledge.json"])
        CRMSResearchIndex().save(paths["index.json"])
        cli = [sys.executable, str(PROJECT / "crms_chat.py"),
               "--knowledge", str(paths["knowledge.json"]),
               "--index", str(paths["index.json"]),
               "--dialogue-state", str(paths["dialogue.json"]),
               "--rules", str(paths["rules.json"]),
               "--rule-session", str(paths["session.json"])]
        output = subprocess.run(
            cli, input="/write-about Nia\n/quit\n", text=True,
            capture_output=True, check=True, timeout=20).stdout
        if ("Derived: Nia is an ancestor of Pia." not in output
                or "parent-transitivity" not in output
                or "three:parent-1" not in output):
            raise SystemExit(f"CLI omitted the grounded derived sentence:\n{output}")
    print("writing over inference diagnostic: PASS")
    print("licensed realization, recursive proof citations, no fact mutation, contradiction abstention, CLI: PASS")


if __name__ == "__main__":
    main()
