"""Check whether a learned phrase occurs in a second source corpus.

This is a read-only lexical attestation probe, not a semantic-equivalence
test. It reports exact sentence evidence and resolvable citations from the
local arXiv CC0/CC-BY index.

Run with:
    python3 experiments/v1_459_academic_phrase_attestation.py
    python3 experiments/v1_459_academic_phrase_attestation.py INDEX --phrases "capital city of" "capital of"
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex, _sentence_spans  # noqa: E402


DEFAULT_INDEX = PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    words = phrase.strip().split()
    if not words:
        raise ValueError("phrase must contain at least one word")
    return re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"\b",
                      re.IGNORECASE)


def attest(index_path: Path, phrases: list[str], *, example_limit: int = 5) -> None:
    if not index_path.is_file():
        raise SystemExit(f"SQLite research index not found: {index_path}")
    if not phrases or any(not phrase.strip() for phrase in phrases):
        raise SystemExit("provide one or more nonempty phrases")
    patterns = {phrase: phrase_pattern(phrase) for phrase in phrases}
    counts = {phrase: {"sentences": 0, "documents": set(), "examples": []}
              for phrase in phrases}
    index = CRMSSQLiteResearchIndex(index_path, read_only=True)
    try:
        for source_row in index.source_list(limit=index.document_count()):
            document = index.document(source_row[0])
            digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
            for start, end in _sentence_spans(document.text):
                sentence = document.text[start:end].strip()
                for phrase, pattern in patterns.items():
                    if not pattern.search(sentence):
                        continue
                    record = counts[phrase]
                    record["sentences"] += 1
                    record["documents"].add(document.document_id)
                    if len(record["examples"]) < example_limit:
                        citation = (f"{document.document_id}#sha256={digest}"
                                    f"&chars={start}:{end}")
                        resolved = index.resolve_citation(citation)
                        if not resolved or sentence not in resolved:
                            raise AssertionError(
                                f"phrase citation failed to resolve: {citation}")
                        record["examples"].append(
                            (document.document_id, document.title,
                             sentence, citation))
    finally:
        index.close()

    print(f"Index: {index_path}")
    print("Mode: read-only; lexical attestation only")
    for phrase in phrases:
        record = counts[phrase]
        print(f"{phrase!r}: sentences={record['sentences']}, "
              f"documents={len(record['documents'])}")
        for document_id, title, sentence, citation in record["examples"]:
            print(f"  {document_id} | {title}\n    {sentence}\n    {citation}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--phrases", nargs="+",
                        default=["capital city of", "capital of"])
    args = parser.parse_args()
    attest(args.index, args.phrases)


if __name__ == "__main__":
    main()
