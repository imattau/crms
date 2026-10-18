"""Extract fully grounded claims from a bounded restrictive relative clause."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def teach(kb: CRMSKnowledgeBase, subject: str, relation: str, obj: str,
          source: str) -> None:
    kb.add_fact(subject, relation, obj, source)
    kb.teach_fact_pattern(
        f"{subject} {relation} {obj}.", subject=subject, relation=relation,
        obj=obj, source=source, predicate_phrase=relation)


def main() -> None:
    kb = CRMSKnowledgeBase()
    teach(kb, "Ada Lovelace", "designed", "the Analytical Engine", "design")
    teach(kb, "Ada Lovelace", "built", "the Widget", "build")
    teach(kb, "Grace Hopper", "designed", "the Compiler", "design-2")
    teach(kb, "Grace Hopper", "built", "the Linker", "build-2")

    sentence = (
        "Ada Lovelace who designed the Analytical Engine built the Compiler.")
    proposals = kb.propose_facts(sentence, source="review:restrictive")
    claims = {(item.subject, item.relation, item.object) for item in proposals}
    expected = {
        ("Ada Lovelace", "designed", "the Analytical Engine"),
        ("Ada Lovelace", "built", "the Compiler"),
    }
    if claims != expected:
        raise SystemExit(f"restrictive relative parse failed: {claims}")
    if any(item.sentence != sentence for item in proposals):
        raise SystemExit("relative-clause proposals lost the source sentence")
    if len(kb.facts()) != 4:
        raise SystemExit("restrictive relative claims were committed automatically")

    index = CRMSResearchIndex()
    index.add_document("restrictive", "Restrictive relative", sentence,
                       "https://research.test/restrictive")
    research = kb.research(sentence, index, limit=10)
    research_claims = {
        (item.subject, item.relation, item.object)
        for item in research.candidates or []
    }
    citation = index.citation(next(
        hit for hit in index.search(sentence, limit=10)
        if hit.document_id == "restrictive"))
    if (research.status != "needs_review"
            or research_claims != {("Ada Lovelace", "built", "the Compiler")}
            or any(item.source != citation or item.sentence != sentence
                   for item in research.candidates or [])):
        raise SystemExit("research did not preserve review-only relative claims")
    if len(kb.facts()) != 4:
        raise SystemExit("research committed restrictive-relative proposals")

    object_kb = CRMSKnowledgeBase()
    teach(object_kb, "Ada Lovelace", "designed", "the Analytical Engine",
          "object-design-a")
    teach(object_kb, "Grace Hopper", "designed", "the Compiler",
          "object-design-b")
    teach(object_kb, "The Compiler", "passed", "testing", "pass-a")
    teach(object_kb, "The Widget", "passed", "a review", "pass-b")
    object_sentence = (
        "The Analytical Engine that Ada Lovelace designed passed testing.")
    object_proposals = object_kb.propose_facts(
        object_sentence, source="review:object-relative")
    object_claims = {
        (item.subject, item.relation, item.object)
        for item in object_proposals
    }
    if object_claims != {
            ("Ada Lovelace", "designed", "The Analytical Engine"),
            ("The Analytical Engine", "passed", "testing"),
    }:
        raise SystemExit(f"object-relative parse failed: {object_claims}")
    if any(item.sentence != object_sentence for item in object_proposals):
        raise SystemExit("object-relative proposals lost the full source sentence")

    object_index = CRMSResearchIndex()
    object_index.add_document(
        "object-relative", "Object relative", object_sentence,
        "https://research.test/object-relative")
    object_research = object_kb.research(object_sentence, object_index, limit=10)
    object_research_claims = {
        (item.subject, item.relation, item.object)
        for item in object_research.candidates or []
    }
    object_citation = object_index.citation(next(
        hit for hit in object_index.search(object_sentence, limit=10)
        if hit.document_id == "object-relative"))
    if (object_research.status != "needs_review"
            or object_research_claims != {
                ("The Analytical Engine", "passed", "testing")}
            or any(item.source != object_citation
                   or item.sentence != object_sentence
                   for item in object_research.candidates or [])):
        raise SystemExit("object-relative research lost citation/review boundaries")
    if len(object_kb.facts()) != 4:
        raise SystemExit("object-relative research committed a proposal")

    unsupported = (
        "Ada Lovelace who invented the Widget built the Compiler.")
    if kb.propose_facts(unsupported, source="review:unsupported"):
        raise SystemExit("unsupported relative clause was partly extracted")

    multiple = (
        "Ada Lovelace who designed the Engine who built the Compiler worked in London.")
    if kb.propose_facts(multiple, source="review:multiple"):
        raise SystemExit("multiple restrictive relatives were partly extracted")

    unsupported_object = (
        "The Analytical Engine that Ada invented passed testing.")
    if object_kb.propose_facts(
            unsupported_object, source="review:unsupported-object"):
        raise SystemExit("unsupported object-relative clause was partly extracted")

    multiple_object = (
        "The Analytical Engine that Ada designed that passed testing failed.")
    if object_kb.propose_facts(
            multiple_object, source="review:multiple-object"):
        raise SystemExit("multiple object-relative clauses were partly extracted")

    comma_form = (
        "Ada Lovelace, who designed the Analytical Engine, built the Compiler.")
    comma_proposals = kb.propose_facts(comma_form, source="review:comma")
    if {(item.subject, item.relation, item.object)
            for item in comma_proposals} != expected:
        raise SystemExit("existing comma-delimited form regressed")

    print("restrictive relative-clause diagnostic: PASS")
    print("subject/object role resolution, research citation, no partial extraction, review-only behavior: PASS")


if __name__ == "__main__":
    main()
