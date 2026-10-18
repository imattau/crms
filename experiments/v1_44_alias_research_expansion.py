"""Check that cited aliases expand local research retrieval."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document("fact", "Design history",
                       "Ada Lovelace designed the Analytical Engine.",
                       "sources/fact.txt")
    index.add_document("alias", "Terminology",
                       "The Analytical Engine is also called chronometer.",
                       "sources/alias.txt")
    hit = index.search("chronometer", limit=1, context_chars=100)[0]
    kb = CRMSKnowledgeBase()
    kb.add_fact("Ada Lovelace", "designed", "the Analytical Engine", "fact")
    kb.teach_entity_alias_from_hit(
        "chronometer", "the Analytical Engine", research_index=index, hit=hit)

    unexpanded = CRMSKnowledgeBase().research("Describe chronometer", index)
    expanded = kb.research("Describe chronometer", index)
    if any(passage["citation"].startswith("fact#")
           for passage in unexpanded.passages or []):
        raise SystemExit("control query unexpectedly retrieved the canonical fact source")
    if not any(passage["citation"].startswith("fact#")
               for passage in expanded.passages or []):
        raise SystemExit(f"learned alias did not expand retrieval: {expanded}")
    fact_passage = next(passage for passage in expanded.passages or []
                        if passage["citation"].startswith("fact#"))
    alias_passage = next(passage for passage in expanded.passages or []
                         if passage["citation"].startswith("alias#"))
    if ("chronometer" not in alias_passage["matched_question_terms"]
            or not {"analytical", "engine"}
            <= set(fact_passage["matched_licensed_expansion_terms"])):
        raise SystemExit(
            f"retrieval provenance did not distinguish alias expansion: {fact_passage}")
    alias_licenses = fact_passage["matched_expansion_licenses"]
    if not any(
            license_record["kind"] == "entity_alias"
            and license_record["evidence"] == "chronometer"
            and license_record["text"] == "the Analytical Engine"
            and any(source.startswith("alias#")
                    for source in license_record["sources"])
            for license_record in alias_licenses):
        raise SystemExit("expanded entity omitted its source-backed alias license")
    rendered = kb.render_research(expanded)
    if "licensed expansion terms: analytical, engine, the" not in rendered:
        raise SystemExit("rendered research omitted its licensed retrieval expansion")
    print("alias research expansion diagnostic: PASS")
    print("source-cited alias expands local retrieval; unlearned alias does not: PASS")


if __name__ == "__main__":
    main()
