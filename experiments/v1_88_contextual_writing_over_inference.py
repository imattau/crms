"""Write contextual rule-derived relations with proof and scope attached."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def add_frame_example(kb: CRMSKnowledgeBase, subject: str, obj: str,
                      source: str) -> None:
    kb.add_fact(subject, "ancestor", obj, f"{source}#fact")
    kb.teach_fact_pattern(
        f"{subject} ancestors {obj}.", subject=subject, relation="ancestor",
        obj=obj, source=f"{source}#fact", predicate_phrase="ancestors")


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Mia", "parent", "Nia", "source:2024-a",
                qualifiers={"year": "2024"})
    kb.add_fact("Nia", "parent", "Ora", "source:2024-b",
                qualifiers={"year": "2024"})
    kb.add_fact("Mia", "parent", "Bea", "source:2025-a",
                qualifiers={"year": "2025"})
    kb.add_fact("Bea", "parent", "Wrong", "source:2025-b",
                qualifiers={"year": "2025"})
    kb.add_inference_rule("parent-chain", "parent", "parent", "ancestor")
    add_frame_example(kb, "Ada", "Cal", "frame:one")
    add_frame_example(kb, "Bob", "Eli", "frame:two")

    written = kb.write_about("Mia", qualifiers={"year": "2024"})
    derived = [statement for statement in written.statements
               if statement.get("inferred")]
    if len(derived) != 1:
        raise SystemExit(f"contextual writing did not produce one derived statement: {written}")
    statement = derived[0]
    if (statement["fact"].get("object") != "Ora"
            or statement["fact"].get("qualifiers") != [("year", "2024")]
            or "context: year=2024" not in written.text
            or "Wrong" in written.text):
        raise SystemExit("written inference lost context or used a mismatched premise")
    if not statement.get("proofs") or not statement.get("sources"):
        raise SystemExit("derived sentence omitted its proof or source lineage")

    kb.add_negative_fact("Mia", "parent", "Nia", "source:counter-2024",
                         qualifiers={"year": "2024"})
    conflicted = kb.write_about("Mia", qualifiers={"year": "2024"})
    if (conflicted.status != "ambiguous"
            or any(item.get("inferred") for item in conflicted.statements)):
        raise SystemExit("writing presented a derivation with a conflicted premise")

    print("contextual writing over inference diagnostic: PASS")
    print("licensed realization, exact-scope proof, lineage, context rendering, conflict abstention: PASS")


if __name__ == "__main__":
    main()
