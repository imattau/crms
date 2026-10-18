"""Review and answer a copular type claim from the full SimpleWiki index."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase
from crms_research import CRMSSQLiteResearchIndex


def main() -> None:
    index_path = (Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1
                  else PROJECT / "data" / "crms_simplewiki_research.sqlite")
    if not index_path.is_file():
        raise SystemExit(f"research SQLite index not found: {index_path}")

    index = CRMSSQLiteResearchIndex(index_path)
    try:
        hit = next((item for item in index.search(
            "Ogun River waterway Nigeria Lagos Lagoon", limit=20,
            context_chars=600) if item.title == "Ogun River"), None)
        if hit is None:
            raise SystemExit("the cited Ogun River source sentence was not found")
        sentence = "The Ogun River is a waterway in Nigeria that discharges into the Lagos Lagoon."
        if sentence not in hit.snippet:
            raise SystemExit(f"source snippet changed: {hit.snippet}")

        knowledge = CRMSKnowledgeBase()
        source = index.citation(hit)
        candidates = knowledge._discover_surface_relation_candidates(
            hit.snippet, source=source, research_index=index)
        if (len(candidates) != 1
                or (candidates[0].subject, candidates[0].relation,
                    candidates[0].object) != ("Ogun River", "is-a", "waterway")
                or not candidates[0].language_evidence[0].get("review_required")
                or candidates[0].language_evidence[0].get("adjunct")
                != "in Nigeria that discharges into the Lagos Lagoon"):
            raise SystemExit(f"bounded type extraction failed: {candidates}")
        if knowledge.facts():
            raise SystemExit("source parsing stored a type claim before review")

        # A negated statement is excluded from the positive type proposal path.
        negative = knowledge._discover_surface_relation_candidates(
            "The Ogun River is not a waterway in Nigeria.",
            source="fixture://negative")
        if negative:
            raise SystemExit(f"negated type claim was proposed as positive: {negative}")

        fact = knowledge.accept_fact_candidate(candidates[0], index)
        if (fact.subject, fact.relation, fact.object) != (
                "Ogun River", "is-a", "waterway"):
            raise SystemExit(f"reviewed type fact was altered: {fact}")
        answer = knowledge.ask_polar_question(
            "Is the Ogun River a waterway?")
        if (answer.status != "answered" or answer.truth is not True
                or not answer.evidence
                or source not in answer.evidence[0]["sources"]):
            raise SystemExit(f"reviewed real-corpus type question failed: {answer}")

        print("real-corpus named type extraction: PASS")
        print(f"Reviewed claim: {fact.subject} — {fact.relation} → {fact.object}")
        print("Negated control abstained before storage")
        print(f"Question: Is the Ogun River a waterway? → {answer.answer}")
        print(f"Citation: {source}")
    finally:
        index.close()


if __name__ == "__main__":
    main()
