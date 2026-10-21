"""SQLite memory for Phase 10 generation rules.

The visible seed file remains `crms_generation_rules.json`. This store versions
accepted rule snapshots, records teacher/human judgments and changes, and can
roll back a snapshot in one operation. Generation itself reads a snapshot and
never needs the JSON file at answer time.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from crms_generation_rules import GenerationRules, rules_from_mapping

FORMAT = "crms-composition-memory"
VERSION = 1
APPLICATION_ID = int.from_bytes(b"CRGN", "big")
ORIGINS = frozenset({"seed", "teacher", "conversation", "human", "rollback"})
JUDGMENT_SOURCES = frozenset({"teacher", "human", "automated", "exact"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class CompositionMemoryError(ValueError):
    """The composition store is malformed or an operation is invalid."""


class GenerationRuleStore:
    """Versioned generation-rule snapshots with audit and rollback."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._initialize()

    def _initialize(self) -> None:
        application_id = self.connection.execute(
            "PRAGMA application_id").fetchone()[0]
        if application_id not in (0, APPLICATION_ID):
            raise CompositionMemoryError(
                "database belongs to another CRMS store")
        self.connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        self.connection.execute(f"PRAGMA user_version={VERSION}")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS comp_rule_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL UNIQUE,
                origin TEXT NOT NULL,
                rationale TEXT NOT NULL,
                digest TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                created_at TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS comp_change (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                tier TEXT NOT NULL,
                action TEXT NOT NULL,
                before_digest TEXT,
                after_digest TEXT,
                score_before REAL,
                score_after REAL,
                accepted INTEGER NOT NULL,
                reference TEXT
            );
            CREATE TABLE IF NOT EXISTS comp_judgment (
                judgment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                source TEXT NOT NULL,
                model TEXT,
                score REAL NOT NULL,
                faithfulness REAL NOT NULL,
                clarity REAL NOT NULL,
                coverage REAL NOT NULL,
                note TEXT
            );
            CREATE TABLE IF NOT EXISTS comp_pattern (
                pattern_id TEXT PRIMARY KEY,
                genre TEXT NOT NULL,
                pattern TEXT NOT NULL,
                origin TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 0
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS comp_lexicon (
                term TEXT NOT NULL,
                kind TEXT NOT NULL,
                value TEXT NOT NULL,
                origin TEXT NOT NULL,
                PRIMARY KEY(term, kind, value)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS comp_triple (
                triple_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                split TEXT NOT NULL,
                origin TEXT NOT NULL
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS comp_frame_stat (
                frame TEXT PRIMARY KEY,
                uses INTEGER NOT NULL DEFAULT 0,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0
            ) WITHOUT ROWID;
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GenerationRuleStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _next_version(self) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM comp_rule_snapshot"
        ).fetchone()
        return int(row[0])

    def put_snapshot(self, payload: Mapping[str, Any], *, origin: str,
                     rationale: str, accepted: bool = True,
                     reference: str | None = None) -> str:
        """Validate and store a rule snapshot; return its snapshot id."""
        if origin not in ORIGINS:
            raise CompositionMemoryError(f"unknown origin: {origin!r}")
        if not rationale.strip():
            raise CompositionMemoryError("rationale is required")
        # Validation is intentionally repeated here: no unvalidated payload
        # can enter the active generation path.
        rules_from_mapping(dict(payload), path=self.path)
        digest = _digest(payload)
        version = self._next_version()
        snapshot_id = f"gen-{version:04d}-{digest[:12]}"
        created = _now()
        before = self.active_snapshot()
        self.connection.execute(
            "INSERT INTO comp_rule_snapshot("
            "snapshot_id,version,origin,rationale,digest,payload_json,"
            "accepted,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (snapshot_id, version, origin, rationale, digest,
             json.dumps(payload, sort_keys=True, ensure_ascii=False),
             1 if accepted else 0, created),
        )
        self.record_change(
            tier="rule", action="snapshot", reference=reference,
            before_digest=(before["digest"] if before else None),
            after_digest=digest, score_before=None, score_after=None,
            accepted=accepted)
        self.connection.commit()
        return snapshot_id

    def active_snapshot(self) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM comp_rule_snapshot WHERE accepted=1 "
            "ORDER BY version DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "version": row["version"],
            "origin": row["origin"],
            "rationale": row["rationale"],
            "digest": row["digest"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def load_rules(self) -> GenerationRules:
        snapshot = self.active_snapshot()
        if snapshot is None:
            raise CompositionMemoryError("no active generation snapshot")
        return rules_from_mapping(
            snapshot["payload"], path=self.path, digest=snapshot["digest"])

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM comp_rule_snapshot WHERE snapshot_id=?",
            (snapshot_id,)).fetchone()
        if row is None:
            raise CompositionMemoryError(f"unknown snapshot: {snapshot_id!r}")
        return {
            "snapshot_id": row["snapshot_id"],
            "version": row["version"],
            "origin": row["origin"],
            "rationale": row["rationale"],
            "digest": row["digest"],
            "payload": json.loads(row["payload_json"]),
            "accepted": bool(row["accepted"]),
            "created_at": row["created_at"],
        }

    def rollback(self, snapshot_id: str, *, rationale: str) -> str:
        """Restore a snapshot as a new accepted version in one operation."""
        target = self.get_snapshot(snapshot_id)
        return self.put_snapshot(
            target["payload"], origin="rollback",
            rationale=rationale or f"rollback to {snapshot_id}",
            accepted=True, reference=snapshot_id)

    def record_change(self, *, tier: str, action: str,
                      before_digest: str | None, after_digest: str | None,
                      score_before: float | None, score_after: float | None,
                      accepted: bool, reference: str | None = None) -> None:
        if tier not in {"data", "rule", "code"}:
            raise CompositionMemoryError(f"unknown change tier: {tier!r}")
        self.connection.execute(
            "INSERT INTO comp_change(at,tier,action,before_digest,"
            "after_digest,score_before,score_after,accepted,reference) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (_now(), tier, action, before_digest, after_digest,
             score_before, score_after, 1 if accepted else 0, reference),
        )
        self.connection.commit()

    def record_judgment(self, *, snapshot_id: str, source: str, score: float,
                        faithfulness: float, clarity: float, coverage: float,
                        model: str | None = None, note: str = "") -> None:
        if source not in JUDGMENT_SOURCES:
            raise CompositionMemoryError(f"unknown judgment source: {source!r}")
        self.connection.execute(
            "INSERT INTO comp_judgment(at,snapshot_id,source,model,score,"
            "faithfulness,clarity,coverage,note) VALUES(?,?,?,?,?,?,?,?,?)",
            (_now(), snapshot_id, source, model, score, faithfulness,
             clarity, coverage, note),
        )
        self.connection.commit()

    def record_frame_stat(self, frame: str, *, success: bool) -> None:
        self.connection.execute(
            "INSERT INTO comp_frame_stat(frame,uses,successes,failures) "
            "VALUES(?,1,?,?) ON CONFLICT(frame) DO UPDATE SET "
            "uses=uses+1, successes=successes+excluded.successes, "
            "failures=failures+excluded.failures",
            (frame, 1 if success else 0, 0 if success else 1),
        )
        self.connection.commit()

    def stats(self) -> dict[str, Any]:
        def count(table: str) -> int:
            return int(self.connection.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return {
            "snapshots": count("comp_rule_snapshot"),
            "changes": count("comp_change"),
            "judgments": count("comp_judgment"),
            "patterns": count("comp_pattern"),
            "lexicon": count("comp_lexicon"),
            "triples": count("comp_triple"),
            "frame_stats": count("comp_frame_stat"),
            "active": self.active_snapshot(),
        }


def seed_store(store: GenerationRuleStore, payload: Mapping[str, Any], *,
               rationale: str = "initial seed snapshot") -> str:
    """Store the visible seed rules and return the snapshot id."""
    return store.put_snapshot(payload, origin="seed", rationale=rationale)
