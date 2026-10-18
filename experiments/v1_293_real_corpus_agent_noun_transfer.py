"""Learn an agent-noun question form from reviewed real-corpus evidence.

Run with the packaged SimpleWiki index or pass another research SQLite path:
    python3 experiments/v1_293_real_corpus_agent_noun_transfer.py [INDEX]
"""
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
        knowledge = CRMSKnowledgeBase()
        selected = []
        seen_pairs = set()
        seen_documents = set()
        for hit in index.search("inventor of", limit=100,
                                context_chars=500):
            for candidate in knowledge._discover_surface_relation_candidates(
                    hit.snippet, source=index.citation(hit)):
                pair = (candidate.subject.casefold(), candidate.object.casefold())
                if (candidate.relation != "inventor of"
                        or pair in seen_pairs
                        or hit.document_id in seen_documents
                        or not candidate.language_evidence
                        or not candidate.language_evidence[0].get(
                            "review_required")):
                    continue
                selected.append((candidate, hit))
                seen_pairs.add(pair)
                seen_documents.add(hit.document_id)
                if len(selected) == 3:
                    break
            if len(selected) == 3:
                break

        if len(selected) < 2:
            raise SystemExit(
                "fewer than two independent inventor-of examples were found")

        one_example = CRMSKnowledgeBase()
        first_candidate, _first_hit = selected[0]
        first_fact = one_example.accept_fact_candidate(first_candidate, index)
        first_question = f"Who invented {first_candidate.object}?"
        if one_example.ask(first_question).status == "answered":
            raise SystemExit(
                "one reviewed nominal example unexpectedly licensed a verb form")

        reviewed_facts = [first_fact]
        for candidate, _hit in selected[1:]:
            reviewed_facts.append(
                knowledge.accept_fact_candidate(candidate, index))
        # Add the first identical, independently cited example to the main KB.
        knowledge.accept_fact_candidate(first_candidate, index)

        result = knowledge.ask("Who invented the battery?")
        if (result.status != "answered"
                or result.answer != "Alessandro Volta"
                or not result.evidence
                or not any(
                    "wiki:simplewiki:" in source
                    for row in result.evidence
                    for source in row.get("sources", ()))):
            raise SystemExit(f"real-corpus held-out question failed: {result}")
        if len({fact.sources[0] for fact in reviewed_facts}) < 2:
            raise SystemExit("reviewed examples do not have independent citations")

        print("real-corpus agent-noun transfer: PASS")
        print("Reviewed source examples:")
        for fact in reviewed_facts:
            print(f"  {fact.subject} — {fact.relation} → {fact.object}")
        print(f"Held-out question: Who invented the battery? → {result.answer}")
        print("Answer evidence:")
        for row in result.evidence:
            for source in row.get("sources", ()):
                print(f"  {source}")
    finally:
        index.close()


if __name__ == "__main__":
    main()
