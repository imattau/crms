"""Reject morphology rules supported only by one source document.

Run from the project root with:
    python3 experiments/v1_77_morphology_source_independence.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def teach_relation(kb: CRMSKnowledgeBase, relation: str, surface: str,
                   document_id: str) -> None:
    for number, (subject, obj) in enumerate((("Ada", "Engine"),
                                              ("Bea", "Compiler")), start=1):
        sentence = f"{subject} {surface} {obj}."
        source = f"{document_id}#fragment-{number}"
        kb.add_fact(subject, relation, obj, source)
        kb.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=source, predicate_phrase=surface)


def main() -> None:
    kb = CRMSKnowledgeBase()
    # Distinct citations and relation families from one document are not
    # independent source evidence for a productive spelling rule.
    teach_relation(kb, "study", "studied", "single-paper")
    teach_relation(kb, "carry", "carried", "single-paper")
    teach_relation(kb, "worry", "worry", "single-paper")
    candidates = kb.propose_facts(
        "Sage worried Sculpture", source="review:single-paper")
    if any(item.relation == "worry" and item.subject == "Sage"
           for item in candidates):
        raise SystemExit("one source document licensed cross-relation morphology")
    if kb._licensed_predicate_spelling_rules():
        raise SystemExit("same-document fragments were counted as independent sources")

    # The same observed transformations become available when relation
    # families are grounded in separate documents.
    independent = CRMSKnowledgeBase()
    teach_relation(independent, "study", "studied", "study-doc")
    teach_relation(independent, "carry", "carried", "carry-doc")
    teach_relation(independent, "worry", "worry", "worry-doc")
    candidate = next((item for item in independent.propose_facts(
        "Sage worried Sculpture", source="review:independent")
        if item.relation == "worry" and item.subject == "Sage"), None)
    if candidate is None:
        raise SystemExit("independent source documents failed to license morphology")

    print("morphology source-independence diagnostic: PASS")
    print("same-document fragments rejected; distinct-document grounded transfer retained: PASS")


if __name__ == "__main__":
    main()
