"""Find stored facts that the rest of the knowledge base already derives.

HPM's Observer only creates a node when existing ones leave residual surprise.
The CRMS analogue: a stored fact whose proof exists without it carries no
residual, so it can be kept as a derived case (cheap, re-verifiable) rather than
as primary evidence. This diagnostic only reports; it changes no store.

Run from the project root with:
    python3 experiments/v1_415_derivation_redundant_facts.py
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def derivation_redundant_facts(kb: CRMSKnowledgeBase) -> list:
    """Facts that stay provable (complete, via a rule) after their removal."""
    conclusions = {rule.conclusion_relation for rule in kb._inference_rules.values()}
    redundant = []
    for fact in list(kb.facts()):
        if fact.relation not in conclusions or fact.qualifiers:
            continue
        sources = list(fact.sources)
        for source in sources:
            kb.remove_fact(fact.subject, fact.relation, fact.object, source)
        try:
            result = kb.infer_relation(fact.subject, fact.relation, fact.object)
            derivable = (result.status == "answered" and result.complete
                         and bool(result.proofs))
        finally:
            for source in sources:
                kb.add_fact(fact.subject, fact.relation, fact.object, source)
        if derivable:
            redundant.append(fact)
    return redundant


def main() -> None:
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada", "works at", "Studio", "s:hr")
    kb.add_fact("Studio", "located in", "Paris", "s:addr")
    kb.add_fact("Paris", "in country", "France", "s:atlas")
    kb.add_fact("Ada", "works in", "Paris", "s:cache1")           # derivable
    kb.add_fact("Ada", "works in country", "France", "s:cache2")  # derivable
    kb.add_fact("Bo", "works in", "Rome", "s:hr2")                # not derivable
    kb.add_inference_rule("work-location", "works at", "located in", "works in")
    kb.add_inference_rule("location-country", "works in", "in country",
                          "works in country")
    before = len(kb.facts())
    found = {(f.subject, f.relation, f.object)
             for f in derivation_redundant_facts(kb)}
    require(found == {("Ada", "works in", "Paris"),
                      ("Ada", "works in country", "France")},
            f"unexpected redundant set: {found}")
    require(len(kb.facts()) == before, "analysis must leave the store unchanged")
    print(f"{len(found)} of {before} facts are derivable without themselves")


if __name__ == "__main__":
    main()
