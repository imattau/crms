#!/usr/bin/env python3
"""Build the word-rarity table (document frequency) used by the answerability gate.

Counts, over a deterministic sample of documents from the shipped corpora, how many documents
contain each word. Words in fewer than MIN_DF documents are left out (an unknown word is treated
as rare). Output: corpus/phase13_model/word_df.tsv with a header line `# N=<documents>`."""
from __future__ import annotations

import collections
from pathlib import Path
import sqlite3
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_intent_rules import words  # noqa: E402

SOURCES = [(PROJECT / "data" / "crms_simplewiki_research.sqlite", 60000),
           (PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite", 2000)]
MIN_DF = 12
OUT = PROJECT / "corpus" / "phase13_model" / "word_df.tsv"


def main() -> int:
    df: collections.Counter = collections.Counter()
    n = 0
    for path, limit in SOURCES:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        for (body,) in connection.execute(
                "SELECT substr(body,1,3000) FROM source_documents "
                "ORDER BY (rowid*2654435761+17)%4294967296 LIMIT ?", (limit,)):
            seen = set(words(body))
            df.update(seen)
            n += 1
    kept = sorted(((w, c) for w, c in df.items() if c >= MIN_DF), key=lambda x: (-x[1], x[0]))
    OUT.write_text(f"# N={n}\n" + "".join(f"{w}\t{c}\n" for w, c in kept), encoding="utf-8")
    print(f"{n} documents, {len(kept)} words kept, {OUT.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
