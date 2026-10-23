"""Package the pattern tables with a release (Phase 13, workstream D).

A release directory holds the chat model and its metadata (`crms_phase8_model`). This module adds
`patterns.sqlite`: verbs, agent nouns, classes, relation specs with their evidence, intent rules,
gate policy, parameters, rewrites, the audit trail, and the word-rarity table, all as SQL tables in
one file with a manifest in `pat_meta`. The visible seed file stays the reviewed source; the
database is what ships and what the chat reads.

    build_pattern_db(path)        make a database from the seed and the rarity table
    verify_pattern_db(path)       integrity and content checks; returns a list of problems
    update_patterns(release, db)  install a new database; the previous one is kept
    rollback_patterns(release)    swap the previous database back (one operation)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from crms_pattern_memory import APPLICATION_ID, PatternMemory

PATTERNS_FILE = "patterns.sqlite"
PREVIOUS_FILE = "patterns.previous.sqlite"
PROJECT = Path(__file__).resolve().parent
WORD_DF = PROJECT / "corpus" / "phase13_model" / "word_df.tsv"
ASSOC = PROJECT / "corpus" / "phase13_model" / "responsiveness_assoc.json"
SCORER = PROJECT / "corpus" / "phase13_model" / "responsiveness_weights.json"
SEED = PROJECT / "crms_pattern_seed.json"
REQUIRED_TABLES = ("pat_assoc", "pat_scorer", "pat_verb", "pat_class", "pat_spec", "pat_intent", "pat_gate_policy",
                   "pat_param", "pat_rewrite", "pat_change", "pat_word_df", "pat_meta")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build_pattern_db(path: str | Path, *, version: str = "1", seed: Path = SEED,
                     word_df: Path = WORD_DF) -> dict[str, Any]:
    """Create `path` from the seed file and the rarity table; return its manifest."""
    target = Path(path)
    if target.exists():
        target.unlink()
    with PatternMemory(target) as memory:
        specs = memory.seed(seed)
        documents, words = 1, 0
        if word_df.is_file():
            rows = []
            for line in word_df.read_text(encoding="utf-8").splitlines():
                if line.startswith("# N="):
                    documents = int(line[4:])
                elif line:
                    word, _, count = line.partition("\t")
                    rows.append((word, int(count)))
            memory.connection.executemany("INSERT OR REPLACE INTO pat_word_df VALUES(?,?)", rows)
            words = len(rows)
        scorer_features = 0
        if SCORER.is_file():
            weights = json.loads(SCORER.read_text(encoding="utf-8"))["weights"]
            memory.put_scorer_weights(weights)
            scorer_features = len(weights)
        pairs = 0
        if ASSOC.is_file():
            table = json.loads(ASSOC.read_text(encoding="utf-8"))
            memory.put_associations(table)
            pairs = sum(len(v) for v in table.values())
        manifest = {
            "format": "crms-pattern-db", "version": version,
            "scorer_features": str(scorer_features), "association_pairs": str(pairs),
            "scorer_sha256": _sha256(SCORER) if SCORER.is_file() else "",
            "seed_sha256": _sha256(seed),
            "word_df_sha256": _sha256(word_df) if word_df.is_file() else "",
            "word_df_documents": str(documents), "word_df_words": str(words),
            "specs": str(specs),
            "intents": str(memory.connection.execute("SELECT count(*) FROM pat_intent").fetchone()[0]),
            "verbs": str(memory.connection.execute("SELECT count(DISTINCT lemma) FROM pat_verb").fetchone()[0]),
        }
        memory.connection.executemany("INSERT OR REPLACE INTO pat_meta VALUES(?,?)", sorted(manifest.items()))
        memory.connection.commit()
    return manifest


def verify_pattern_db(path: str | Path) -> list[str]:
    """Problems found in a pattern database (empty list = sound)."""
    target = Path(path)
    if not target.is_file():
        return [f"missing pattern database: {target}"]
    problems: list[str] = []
    try:
        connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.DatabaseError as error:
        return [f"cannot open: {error}"]
    try:
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            problems.append("not a CRMS pattern database (application id)")
        present = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in REQUIRED_TABLES:
            if table not in present:
                problems.append(f"missing table {table}")
        if problems:
            return problems
        meta = dict(connection.execute("SELECT key,value FROM pat_meta"))
        if meta.get("format") != "crms-pattern-db":
            problems.append("manifest is missing or has the wrong format")
        for table, key in (("pat_intent", "intents"),):
            count = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            if key in meta and str(count) != meta[key]:
                problems.append(f"manifest says {meta[key]} {key}, the table has {count}")
        if connection.execute("SELECT count(*) FROM pat_spec WHERE status='accepted'").fetchone()[0] == 0:
            problems.append("no accepted relation specs")
        if connection.execute("SELECT count(*) FROM pat_gate_policy").fetchone()[0] == 0:
            problems.append("no gate policy rows")
        for (blob,) in connection.execute("SELECT question_json FROM pat_spec WHERE status='accepted'"):
            try:
                json.loads(blob)
            except ValueError:
                problems.append("a spec has malformed question patterns")
                break
    except sqlite3.DatabaseError as error:
        problems.append(f"unreadable pattern database: {error}")
    finally:
        connection.close()
    return problems


def _record(release: Path) -> None:
    """Refresh the release manifest entry for the pattern database."""
    manifest_path = release / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    path = release / PATTERNS_FILE
    files = [f for f in manifest.get("files", []) if f["path"] != PATTERNS_FILE]
    files.append({"path": PATTERNS_FILE, "sha256": _sha256(path), "bytes": path.stat().st_size,
                  "role": "pattern-memory"})
    manifest["files"] = files
    manifest["total_bytes"] = sum(int(f["bytes"]) for f in files)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_patterns(release: str | Path, new_db: str | Path) -> dict[str, Any]:
    """Install `new_db` as the release's pattern database; keep the old one for rollback."""
    root = Path(release)
    problems = verify_pattern_db(new_db)
    if problems:
        raise ValueError("pattern database failed verification: " + "; ".join(problems))
    current = root / PATTERNS_FILE
    if current.is_file():
        shutil.copy2(current, root / PREVIOUS_FILE)
    shutil.copy2(new_db, current)
    _record(root)
    return {"installed": str(current), "previous_kept": (root / PREVIOUS_FILE).is_file()}


def rollback_patterns(release: str | Path) -> dict[str, Any]:
    """Swap the previous pattern database back in. One operation, reversible by calling it again."""
    root = Path(release)
    previous, current = root / PREVIOUS_FILE, root / PATTERNS_FILE
    if not previous.is_file():
        raise FileNotFoundError("no previous pattern database to roll back to")
    swap = root / "patterns.swap.sqlite"
    shutil.move(current, swap)
    shutil.move(previous, current)
    shutil.move(swap, previous)
    _record(root)
    return {"restored": str(current)}
