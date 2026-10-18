"""Check ordered-term proximity in deterministic source retrieval.

Run from the project root with:
    python3 experiments/v1_122_ordered_proximity_retrieval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSResearchIndex


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        "a_scattered", "Source A",
        "Ada engine designed plus notes today.",
        "https://research.test/scattered")
    index.add_document(
        "m_sentence_boundary", "Source M",
        "Ada. Designed engine plus notes today.",
        "https://research.test/boundary")
    index.add_document(
        "b_spaced", "Source B",
        "Ada perhaps designed engine plus notes.",
        "https://research.test/spaced")
    index.add_document(
        "z_ordered", "Source Z",
        "Ada designed engine plus notes today.",
        "https://research.test/ordered")

    hits = index.search("Ada designed engine", limit=4)
    order = [hit.document_id for hit in hits]
    if order != ["z_ordered", "b_spaced", "m_sentence_boundary",
                 "a_scattered"]:
        raise SystemExit(f"ordered-term proximity ranked sources incorrectly: {order}")
    if any(set(hit.matched_terms) != {"ada", "designed", "engine"}
           for hit in hits):
        raise SystemExit("proximity changed lexical match attribution")
    for hit in hits:
        citation = index.citation(hit)
        if index.resolve_citation(citation) != hit.snippet:
            raise SystemExit("proximity result lost its exact source citation")
    if index.search("unmatched phrase", limit=3):
        raise SystemExit("proximity ranking created a result for an unmatched query")

    print("ordered proximity retrieval diagnostic: PASS")
    print("query-order and distance boost, sentence-boundary handling, exact citations, no-match behavior: PASS")


if __name__ == "__main__":
    main()
