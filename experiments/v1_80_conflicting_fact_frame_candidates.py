"""Preserve opposite-polarity source candidates from overlapping frames."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach(kb: CRMSKnowledgeBase, *, subject: str, obj: str,
          source: str, negative: bool, article: bool) -> None:
    surface_object = f"the {obj}" if article else obj
    sentence = f"{subject} designed {surface_object}."
    if negative:
        kb.add_negative_fact(subject, "design", obj, source)
    else:
        kb.add_fact(subject, "design", obj, source)
    kb.teach_fact_pattern(
        sentence, subject=subject, relation="design", obj=obj,
        source=source, predicate_phrase="designed", polarity=not negative)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, subject="Ada", obj="Engine", source="positive-1",
          negative=False, article=False)
    teach(kb, subject="Bea", obj="Compiler", source="positive-2",
          negative=False, article=False)
    kb.teach_entity_alias("the Engine", "Engine", source="alias:engine")
    kb.teach_entity_alias("the Compiler", "Compiler", source="alias:compiler")
    teach(kb, subject="Cora", obj="Engine", source="negative-1",
          negative=True, article=True)
    teach(kb, subject="Dee", obj="Compiler", source="negative-2",
          negative=True, article=True)

    direct = kb.propose_facts("Ada designed the Engine.", source="review:direct")
    matching = [candidate for candidate in direct
                if candidate.subject == "Ada"
                and candidate.relation == "design"
                and candidate.object == "Engine"]
    if len(matching) != 2 or {candidate.polarity for candidate in matching} != {True, False}:
        raise SystemExit(f"overlapping positive/negative frames were collapsed: {matching}")

    index = CRMSResearchIndex()
    target = "Bob designed the Engine."
    index.add_document("target", "target", target, "sources/target.txt")
    result = kb.research(target, index, limit=5)
    reviewed = [candidate for candidate in result.candidates or []
                if candidate.subject == "Bob" and candidate.object == "Engine"]
    if len(reviewed) != 2 or {candidate.polarity for candidate in reviewed} != {True, False}:
        raise SystemExit(
            f"research candidate map lost a polarity:\n{kb.render_research(result)}")
    rendered = kb.render_research(result)
    if ("Proposed for review (fact)" not in rendered
            or "Proposed for review (negative fact)" not in rendered):
        raise SystemExit("review rendering did not expose both polarities")

    print("conflicting fact-frame candidate diagnostic: PASS")
    print("overlapping frames, canonicalized entities, research deduplication, polarity-visible review: PASS")


if __name__ == "__main__":
    main()
