"""Measure reviewed predicate-alignment yield on separated real-corpus windows.

This is a read-only diagnostic: it never accepts proposals or writes to the
research index. It helps distinguish a sound discovery mechanism from one
that has enough naturally recurring evidence to support useful learning.

Run with:
    python3 experiments/v1_343_real_corpus_predicate_alignment_yield.py
    python3 experiments/v1_343_real_corpus_predicate_alignment_yield.py INDEX
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


DEFAULT_INDEX = PROJECT / "data/crms_academic_simplewiki_research.sqlite"
OFFSETS = (0, 5_000, 20_000, 50_000, 100_000, 150_000, 200_000, 275_000)
WINDOW_DOCUMENTS = 125
WINDOW_SENTENCES = 6_000


def main() -> None:
    index_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_INDEX
    if not index_path.is_file():
        raise SystemExit(f"research index does not exist: {index_path}")
    before = index_path.stat()
    index = CRMSSQLiteResearchIndex(index_path, read_only=True)
    knowledge = CRMSKnowledgeBase()
    windows = []
    try:
        for offset in OFFSETS:
            proposals = knowledge.propose_corpus_predicate_alignments(
                index, minimum_pairs=2,
                maximum_documents=WINDOW_DOCUMENTS,
                maximum_sentences=WINDOW_SENTENCES,
                maximum_proposals=100, document_offset=offset)
            windows.append({
                "document_offset": offset,
                "documents_requested": WINDOW_DOCUMENTS,
                "proposal_count": len(proposals),
                "proposals": [{
                    "relation": row["relation"],
                    "predicate_phrase": row["predicate_phrase"],
                    "distinct_pairs": row["distinct_pairs"],
                    "canonical_documents": row["canonical_documents"],
                    "alias_documents": row["alias_documents"],
                } for row in proposals],
            })
    finally:
        index.close()
    after = index_path.stat()
    unchanged = (before.st_size == after.st_size
                 and before.st_mtime_ns == after.st_mtime_ns)
    if not unchanged:
        raise SystemExit("read-only alignment probe changed the index file")
    result = {
        "diagnostic": "real-corpus-predicate-alignment-yield-v1",
        "index": str(index_path),
        "window_documents": WINDOW_DOCUMENTS,
        "window_sentences": WINDOW_SENTENCES,
        "minimum_shared_pairs": 2,
        "total_proposals": sum(row["proposal_count"] for row in windows),
        "index_unchanged": unchanged,
        "windows": windows,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
