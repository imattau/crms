"""Check SQLite search-stat caching, external-write invalidation, and parity."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex


QUERIES = (
    "What is the Pacific Ocean?",
    "What is the Atlantic Ocean?",
    "What is the Indian Ocean?",
    "Who wrote Hamlet?",
    "Who wrote Frankenstein?",
    "What is photosynthesis?",
    "What is Mount Everest?",
    "What is the Mona Lisa?",
    "What is the capital of France?",
    "Who created Python?",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def signature(index: CRMSSQLiteResearchIndex, hits) -> tuple:
    return tuple((hit.document_id, hit.title, hit.snippet, hit.start, hit.end,
                  hit.matched_terms, hit.score, index.citation(hit))
                 for hit in hits)


def benchmark_large_index(path: Path) -> None:
    index = CRMSSQLiteResearchIndex(path, read_only=True)
    try:
        uncached_results = []
        uncached_ms = []
        for query in QUERIES:
            index._term_document_frequency_cache.clear()
            started = time.perf_counter()
            hits = index.search(query, limit=5, context_chars=240)
            uncached_ms.append((time.perf_counter() - started) * 1000)
            uncached_results.append(signature(index, hits))

        index._term_document_frequency_cache.clear()
        cached_results = []
        cached_ms = []
        for query in QUERIES:
            started = time.perf_counter()
            hits = index.search(query, limit=5, context_chars=240)
            cached_ms.append((time.perf_counter() - started) * 1000)
            cached_results.append(signature(index, hits))
        require(uncached_results == cached_results,
                "term-frequency caching changed hits, snippets, scores, or citations")
        uncached_total = sum(uncached_ms)
        cached_total = sum(cached_ms)
        print(f"read-only corpus documents: {index.document_count():,}")
        print(f"10-query search total uncached: {uncached_total:.1f} ms")
        print(f"10-query search total cached:   {cached_total:.1f} ms")
        print("uncached per-query ms:", ", ".join(f"{value:.1f}" for value in uncached_ms))
        print("cached per-query ms:  ", ", ".join(f"{value:.1f}" for value in cached_ms))
        print("search result and exact-citation parity: PASS")
    finally:
        index.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--large-index", type=Path,
                        help="optionally benchmark a read-only corpus index")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="crms-term-frequency-cache-") as folder:
        path = Path(folder) / "corpus.sqlite3"
        writer = CRMSSQLiteResearchIndex(path)
        writer.add_document("one", "Alpha note", "Alpha and beta meet in note one.")
        writer.add_document("two", "Beta note", "Beta and alpha meet in note two.")
        writer.save()
        writer.search("gamma", limit=5)
        require(writer._term_document_frequency_cache.get("gamma") == 0,
                "writer did not cache the missing-term frequency")
        writer.add_document("local", "Gamma note", "Gamma appears in a new note.")
        writer.save()
        require(any(hit.document_id == "local"
                    for hit in writer.search("gamma", limit=5)),
                "same-connection write left cached corpus frequencies stale")
        reader = CRMSSQLiteResearchIndex(path, read_only=True)
        try:
            original = reader.search("alpha beta", limit=5)
            original_signature = signature(reader, original)
            require({"alpha", "beta"} <=
                    set(reader._term_document_frequency_cache),
                    "term frequencies were not cached")
            repeated = reader.search("alpha beta", limit=5)
            require(signature(reader, repeated) == original_signature,
                    "a cache hit changed retrieval results")

            writer.add_document("three", "Alpha beta update",
                                "Alpha and beta meet in a new note.")
            writer.save()
            updated = reader.search("alpha beta", limit=5)
            fresh = CRMSSQLiteResearchIndex(path, read_only=True)
            try:
                fresh_results = fresh.search("alpha beta", limit=5)
                require(signature(reader, updated) == signature(fresh, fresh_results),
                        "external index write left cached corpus frequencies stale")
                require(any(hit.document_id == "three" for hit in updated),
                        "reader did not observe the newly indexed document")
            finally:
                fresh.close()
        finally:
            reader.close()
            writer.close()

    print("repeated-query cache preserves ranking and citations: PASS")
    print("same-connection writer clears cached corpus frequencies: PASS")
    print("external writer invalidates cached corpus frequencies: PASS")
    if args.large_index:
        benchmark_large_index(args.large_index.expanduser().resolve())


if __name__ == "__main__":
    main()
