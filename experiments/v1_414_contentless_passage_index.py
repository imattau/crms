"""Verify the contentless passage index returns the same hits as the legacy one.

Run from the project root with:
    python3 experiments/v1_414_contentless_passage_index.py
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_research import CRMSSQLiteResearchIndex

DOCUMENTS = [
    ("a", "Eiffel Tower",
     "The Eiffel Tower is a wrought-iron tower in Paris. " * 40
     + "Gustave Eiffel's company designed and built the tower."),
    ("b", "Colosseum", "The Colosseum is an amphitheatre in Rome. " * 60),
    ("c", "Paris", "Paris is the capital of France. The Seine flows through it. " * 50),
    ("d", "Rome", "Rome is the capital of Italy and sits on the Tiber. " * 50),
]
QUERIES = ["Eiffel Tower", "capital", "tower built", "Tiber Rome", "amphitheatre"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def hits(index: CRMSSQLiteResearchIndex) -> list:
    return [[(h.document_id, round(h.score, 9), h.start, h.end)
             for h in index.search(query, limit=5)] for query in QUERIES]


def fill(index: CRMSSQLiteResearchIndex) -> None:
    for document_id, title, text in DOCUMENTS:
        index.add_document(document_id, title, text)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="crms-contentless-") as folder:
        root = Path(folder)
        legacy_path = root / "legacy.sqlite"
        original = CRMSSQLiteResearchIndex._create_fts_table
        CRMSSQLiteResearchIndex._create_fts_table = (
            lambda self: self._db.execute(self._LEGACY_FTS_SQL))
        try:
            legacy = CRMSSQLiteResearchIndex(legacy_path)
        finally:
            CRMSSQLiteResearchIndex._create_fts_table = original
        require(not legacy._fts_contentless, "legacy index should store text")
        fill(legacy)
        before = hits(legacy)
        require(all(before), "every query should hit the legacy index")
        titles_before = legacy.exact_title_matches("Colosseum")
        require(titles_before, "legacy title match missing")

        require(legacy.rebuild_contentless_index(), "rebuild should convert")
        require(legacy._fts_contentless, "rebuilt index should be contentless")
        require(not legacy.rebuild_contentless_index(), "rebuild is idempotent")
        require(hits(legacy) == before, "rebuilt hits differ from legacy hits")
        require(legacy.exact_title_matches("Colosseum") == titles_before,
                "title matches changed after rebuild")

        fresh = CRMSSQLiteResearchIndex(root / "fresh.sqlite")
        require(fresh._fts_contentless, "new indexes should be contentless")
        fill(fresh)
        require(hits(fresh) == before, "fresh contentless hits differ")
        names = {row[0] for row in sqlite3.connect(root / "fresh.sqlite").execute(
            "SELECT name FROM sqlite_master")}
        require("source_fts_content" not in names,
                "contentless index must not keep a content table")

        fresh.add_document("a", "Eiffel Tower", "Replacement text about iron.",
                           replace=True)
        require(not any(h.document_id == "a"
                        for h in fresh.search("amphitheatre wrought", limit=5)),
                "replaced passages still match")
        require(any(h.document_id == "a"
                    for h in fresh.search("replacement iron", limit=5)),
                "replacement passage not indexed")

        reopened = CRMSSQLiteResearchIndex(root / "fresh.sqlite", read_only=True)
        require(reopened._fts_contentless, "read-only open misdetected layout")
        require(any(h.document_id == "b"
                    for h in reopened.search("amphitheatre", limit=5)),
                "read-only search failed")
    print("contentless passage index matches the legacy index")


if __name__ == "__main__":
    main()
