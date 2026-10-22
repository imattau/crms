"""Word rarity from document frequency (Phase 13, workstream A).

The answerability gate used a hand-written list of generic words to decide which question terms
matter. Rarity replaces that judgement with data: the weight of a word is the log inverse of the
share of corpus documents containing it. A question term that is rare yet absent from a candidate
sentence is strong evidence the sentence is about something else (copper versus cobalt). The table
is `corpus/phase13_model/word_df.tsv` (built by `run_phase13_rarity.py` from the shipped corpora);
a word missing from it is treated as rare.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
import sqlite3

TABLE = Path(__file__).resolve().parent / "corpus" / "phase13_model" / "word_df.tsv"


@lru_cache(maxsize=1)
def _load() -> tuple[int, dict[str, int]]:
    """(documents, word -> document frequency) from the installed pattern database, else the TSV."""
    from crms_pattern_defaults import installed_path
    total, table = 1, {}
    path = installed_path()
    if path is not None:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(connection.execute("SELECT key,value FROM pat_meta"))
            total = int(meta.get("word_df_documents", 1))
            table = {w: int(c) for w, c in connection.execute("SELECT word,df FROM pat_word_df")}
        except sqlite3.DatabaseError:
            pass
        finally:
            connection.close()
        if table:
            return total, table
    if TABLE.is_file():
        for line in TABLE.read_text(encoding="utf-8").splitlines():
            if line.startswith("# N="):
                total = int(line[4:])
            elif line:
                word, _, count = line.partition("\t")
                table[word] = int(count)
    return total, table


def weight(word: str) -> float:
    """ln((N+1)/(df+1)); an unknown word gets the largest weight."""
    total, table = _load()
    return math.log((total + 1) / (table.get(word.casefold(), 0) + 1))


def max_weight() -> float:
    total, _table = _load()
    return math.log(total + 1)
