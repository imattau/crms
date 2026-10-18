"""Extract claims from a bounded, learned subject-relative construction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


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
        "Ada Lovelace, who designed the Analytical Engine, built the Compiler.")
    proposals = kb.propose_facts(sentence, source="review:relative")
    claims = {(item.subject, item.relation, item.object) for item in proposals}
    expected = {
        ("Ada Lovelace", "designed", "the Analytical Engine"),
        ("Ada Lovelace", "built", "the Compiler"),
    }
    if claims != expected:
        raise SystemExit(f"relative-clause extraction failed: {claims}")
    if any(item.sentence != sentence for item in proposals):
        raise SystemExit("relative-clause proposals lost their full source sentence")
    if len(kb.facts()) != 4:
        raise SystemExit("relative-clause proposals were committed automatically")

    index = CRMSResearchIndex()
    index.add_document("relative", "Relative clause", sentence,
                       "https://research.test/relative")
    research = kb.research(sentence, index, limit=10)
    research_claims = {
        (item.subject, item.relation, item.object)
        for item in research.candidates or []
    }
    # Research suppresses the embedded claim already present in taught facts;
    # the novel main-clause claim remains for explicit review.
    novel_claim = {("Ada Lovelace", "built", "the Compiler")}
    citation = index.citation(next(
        hit for hit in index.search(sentence, limit=10)
        if hit.document_id == "relative"))
    if (research.status != "needs_review" or research_claims != novel_claim
            or any(item.source != citation or item.sentence != sentence
                   for item in research.candidates or [])):
        raise SystemExit("research did not preserve review-only relative claims")
    if len(kb.facts()) != 4:
        raise SystemExit("research auto-committed relative-clause proposals")

    # The main clause must not be returned if the embedded relation lacks a
    # learned frame; otherwise an unsupported clause could be silently dropped.
    unsupported = (
        "Ada Lovelace, who invented the Widget, built the Compiler.")
    if kb.propose_facts(unsupported, source="review:unsupported-relative"):
        raise SystemExit("partial relative-clause analysis did not abstain")

    # Multiple embedded clauses exceed this parser's deliberately small scope.
    nested = (
        "Ada Lovelace, who designed the Engine, who built the Compiler, "
        "worked in London.")
    if kb.propose_facts(nested, source="review:multiple-relatives"):
        raise SystemExit("multiple relative clauses were partly extracted")

    print("grounded relative-clause diagnostic: PASS")
    print("learned subject-relative frames, complete-source attribution, no auto-commit, partial/multiple-clause abstention: PASS")


if __name__ == "__main__":
    main()
