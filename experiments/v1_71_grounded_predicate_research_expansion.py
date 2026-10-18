"""Check source-grounded predicate phrase expansion in research retrieval.

Run from the project root with:
    python3 experiments/v1_71_grounded_predicate_research_expansion.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    kb = CRMSKnowledgeBase()
    examples = (
        ("training-ada", "Ada built the Analytical Engine.",
         "Ada", "the Analytical Engine"),
        ("training-grace", "Grace built the Compiler.",
         "Grace", "the Compiler"),
    )
    for document_id, sentence, subject, obj in examples:
        index.add_document(document_id, document_id, sentence,
                           f"sources/{document_id}.txt")
        hit = next(hit for hit in index.search(sentence, limit=10)
                   if hit.document_id == document_id)
        kb.add_fact_from_hit(subject, "designed", obj, index, hit)
        kb.teach_fact_pattern_from_hit(
            sentence, subject=subject, relation="designed", obj=obj,
            predicate_phrase="built", research_index=index, hit=hit)

    alternative = "Mira constructed the Vessel."
    index.add_document("training-alternative", "training-alternative",
                       alternative, "sources/training-alternative.txt")
    alternative_hit = next(
        hit for hit in index.search(alternative, limit=10)
        if hit.document_id == "training-alternative")
    kb.add_fact_from_hit("Mira", "designed", "the Vessel", index,
                         alternative_hit)
    kb.teach_fact_pattern_from_hit(
        alternative, subject="Mira", relation="designed", obj="the Vessel",
        predicate_phrase="constructed", research_index=index,
        hit=alternative_hit)

    target_id = "target-canonical-wording"
    index.add_document(target_id, target_id,
                       "The word designed appears in the archive index.",
                       f"sources/{target_id}.txt")
    alias_target_id = "target-alternative-wording"
    index.add_document(alias_target_id, alias_target_id,
                       "The archive records the term constructed.",
                       f"sources/{alias_target_id}.txt")

    matched = kb.research("built", index, limit=10)
    query_expansions = matched.query_expansions or []
    if not any(record["kind"] == "licensed_predicate"
               and record["text"] == "designed"
               and record["sources"] for record in query_expansions):
        raise SystemExit("research result omitted independently available predicate expansions")
    if not any(record["kind"] == "licensed_predicate"
               and record["text"] == "constructed"
               for record in query_expansions):
        raise SystemExit("research result omitted an alternate licensed predicate form")
    retrieved_ids = {passage["citation"].split("#", 1)[0]
                      for passage in matched.passages or []}
    if not {target_id, alias_target_id} <= retrieved_ids:
        raise SystemExit("licensed predicate phrase did not retrieve canonical and alternate wording")
    canonical_passage = next(
        passage for passage in matched.passages or []
        if passage["citation"].startswith(target_id + "#"))
    alternate_passage = next(
        passage for passage in matched.passages or []
        if passage["citation"].startswith(alias_target_id + "#"))
    direct_passage = next(
        passage for passage in matched.passages or []
        if passage["citation"].startswith("training-ada#"))
    if ("built" not in direct_passage["matched_question_terms"]
            or "designed" not in canonical_passage[
                "matched_licensed_expansion_terms"]
            or "constructed" not in alternate_passage[
                "matched_licensed_expansion_terms"]):
        raise SystemExit("predicate retrieval lost query-versus-expansion attribution")
    if not any(
            license_record["kind"] == "licensed_predicate"
            and license_record["text"] == "designed"
            and "designed" in license_record["evidence"]
            and license_record["sources"]
            for license_record in canonical_passage[
                "matched_expansion_licenses"]):
        raise SystemExit("canonical predicate expansion lost its source-backed license")

    # An unseen word has no licensed mapping to the canonical relation.
    unseen = kb.research("fabricated", index, limit=10)
    if any(passage["citation"].split("#", 1)[0]
           in {target_id, alias_target_id}
           for passage in unseen.passages or []):
        raise SystemExit("unlearned predicate wording expanded retrieval")

    # A lone teaching example is insufficient to expand beyond its literal
    # retrieval terms.
    one_example = CRMSKnowledgeBase()
    first_hit = next(hit for hit in index.search(
        examples[0][1], limit=10) if hit.document_id == examples[0][0])
    one_example.add_fact_from_hit(
        examples[0][2], "designed", examples[0][3], index, first_hit)
    one_example.teach_fact_pattern_from_hit(
        examples[0][1], subject=examples[0][2], relation="designed",
        obj=examples[0][3], predicate_phrase="built",
        research_index=index, hit=first_hit)
    unlicensed = one_example.research("built", index, limit=10)
    if any(passage["citation"].split("#", 1)[0]
           in {target_id, alias_target_id}
           for passage in unlicensed.passages or []):
        raise SystemExit("one predicate example licensed research expansion")

    print("grounded predicate research expansion diagnostic: PASS")
    print("licensed canonical/observed predicate expansion, unlearned-word abstention, support threshold: PASS")


if __name__ == "__main__":
    main()
