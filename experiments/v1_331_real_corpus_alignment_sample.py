"""Sample bounded corpus-only relation and predicate-alignment discovery.

This diagnostic never writes to the research index or accepts a language rule.
It reports how often repeated relation frames and cross-predicate alignments
appear in selected windows of a local SQLite corpus.

Run with:
    python3 experiments/v1_331_real_corpus_alignment_sample.py [INDEX]
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


DEFAULT_INDEX = PROJECT / "data" / "crms_simplewiki_research.sqlite"
WINDOW_OFFSETS = (0, 25_000, 75_000, 150_000)
DOCUMENTS_PER_WINDOW = 1_000
SENTENCES_PER_WINDOW = 12_000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()
    if not args.index.is_file():
        raise SystemExit(f"SQLite research index not found: {args.index}")

    index = CRMSSQLiteResearchIndex(args.index, read_only=True)
    try:
        print(f"Index: {args.index}")
        print(f"Documents: {index.document_count()}")
        print("Mode: read-only; no proposals are accepted or stored")
        for offset in WINDOW_OFFSETS:
            learner = CRMSKnowledgeBase()
            options = {
                "maximum_documents": DOCUMENTS_PER_WINDOW,
                "maximum_sentences": SENTENCES_PER_WINDOW,
                "maximum_proposals": 100,
                "document_offset": offset,
            }
            frames = learner.propose_corpus_relation_frames(index, **options)
            alignments = learner.propose_corpus_predicate_alignments(
                index, maximum_proposals=30, **{
                    key: value for key, value in options.items()
                    if key != "maximum_proposals"})
            print(f"offset={offset}: frames={len(frames)}, "
                  f"predicate_alignments={len(alignments)}")
            for frame in frames[:3]:
                sample = frame["support"][0]
                print("  frame:", frame["relation"], "|",
                      sample["sentence"], "|", sample["source"])
            for alignment in alignments[:3]:
                print("  alignment:", alignment["relation"], "~",
                      alignment["predicate_phrase"], "| pairs:",
                      alignment["distinct_pairs"], "| review required:",
                      alignment["review_required"])
    finally:
        index.close()


if __name__ == "__main__":
    main()
