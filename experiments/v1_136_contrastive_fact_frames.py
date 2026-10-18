"""Extract independently grounded assertions joined by ``but``.

Run from the project root with:
    python3 experiments/v1_136_contrastive_fact_frames.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase


def teach(kb: CRMSKnowledgeBase, subject: str, relation: str, obj: str,
          source: str) -> None:
    sentence = f"{subject} {relation} {obj}."
    kb.add_fact(subject, relation, obj, source)
    kb.teach_fact_pattern(sentence, subject=subject, relation=relation,
                          obj=obj, source=source, predicate_phrase=relation)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "Ada Lovelace", "designed", "the Analytical Engine", "design-a")
    teach(kb, "Grace Hopper", "designed", "the Compiler", "design-b")
    teach(kb, "James Watt", "built", "the Difference Engine", "build-a")
    teach(kb, "Katherine Johnson", "built", "the Trajectory Table", "build-b")

    sentence = (
        "Ada Lovelace designed the Analytical Engine, but Grace Hopper built "
        "the Trajectory Table.")
    candidates = kb.propose_facts(sentence, source="review:contrast")
    claims = {(item.subject, item.relation, item.object) for item in candidates}
    expected = {
        ("Ada Lovelace", "designed", "the Analytical Engine"),
        ("Grace Hopper", "built", "the Trajectory Table"),
    }
    if claims != expected:
        raise SystemExit(f"contrastive assertion extraction failed: {claims}")
    if any(item.sentence != sentence for item in candidates):
        raise SystemExit("claims did not retain the complete cited sentence")
    if len(kb.facts()) != 4:
        raise SystemExit("review-only assertions were committed automatically")

    semicolon = (
        "Ada Lovelace designed the Analytical Engine; Grace Hopper built the "
        "Trajectory Table.")
    semicolon_candidates = kb.propose_facts(
        semicolon, source="review:semicolon")
    semicolon_claims = {(item.subject, item.relation, item.object)
                        for item in semicolon_candidates}
    if semicolon_claims != expected or any(
            item.sentence != semicolon for item in semicolon_candidates):
        raise SystemExit(
            f"semicolon clause composition failed: {semicolon_claims}")

    shared = "Ada Lovelace designed the Analytical Engine but built the Compiler."
    shared_candidates = kb.propose_facts(shared, source="review:shared-subject")
    shared_claims = {(item.subject, item.relation, item.object)
                     for item in shared_candidates}
    if shared_claims != {
            ("Ada Lovelace", "designed", "the Analytical Engine"),
            ("Ada Lovelace", "built", "the Compiler")}:
        raise SystemExit(f"shared-subject recovery failed across 'but': {shared_claims}")

    incomplete = "Ada Lovelace designed the Analytical Engine; built the Compiler."
    if kb.propose_facts(incomplete, source="review:semicolon-ellipsis"):
        raise SystemExit("semicolon incorrectly enabled shared-subject recovery")

    # Disjunction does not license either alternative as an asserted fact.
    disjunction = (
        "Ada Lovelace designed the Analytical Engine or Grace Hopper built "
        "the Trajectory Table.")
    disjuncts = kb.propose_facts(disjunction, source="review:or")
    if disjuncts:
        raise SystemExit("disjunctive alternatives were treated as asserted facts")

    print("contrastive fact-frame diagnostic: PASS")
    print("'but'/semicolon assertions, gated shared-subject recovery, review-only status, sentence preservation, 'or' abstention: PASS")


if __name__ == "__main__":
    main()
