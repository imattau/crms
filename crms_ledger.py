"""Deterministic, auditable evidence weights for accepted CRMS items.

The ledger records explicit support and correction events. Merely retrieving,
showing, or deriving from an item never changes its weight. Answer selection
must still use the normal evidence and proof gates before consulting preference.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import sqlite3
from typing import Iterable, Mapping


_KINDS = frozenset({"fact", "rule", "frame", "primitive", "derived_case"})
_EVENTS = frozenset({
    "corroborated", "confirmed", "contradicted", "rejected",
    "held_out_pass", "held_out_fail", "idle_tick",
})


@dataclass(frozen=True)
class LedgerParams:
    auto_initial: float = 0.20
    hit_rate: float = 0.15
    miss_rate: float = 0.35
    idle_decay: float = 0.00
    dormant_below: float = 0.02
    preference_margin: float = 0.30

    def __post_init__(self) -> None:
        for name in ("auto_initial", "hit_rate", "miss_rate", "idle_decay",
                     "dormant_below", "preference_margin"):
            value = getattr(self, name)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not 0 <= value <= 1):
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class Preference:
    outcome: str
    winner: str | None
    margin: float


class Ledger:
    """SQLite-backed event ledger attached to the caller's model connection."""

    def __init__(self, connection: sqlite3.Connection,
                 params: LedgerParams | None = None) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        self.connection = connection
        self.params = params or LedgerParams()
        self._savepoint = f"crms_ledger_{id(self):x}"
        with self._atomic():
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS item_ledger (
              item_kind TEXT NOT NULL,
              item_id TEXT NOT NULL,
              weight REAL NOT NULL,
              hits INTEGER NOT NULL DEFAULT 0,
              misses INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'active',
              protected INTEGER NOT NULL DEFAULT 0,
              updated_seq INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (item_kind, item_id),
              CHECK (weight >= 0.0 AND weight <= 1.0),
              CHECK (hits >= 0 AND misses >= 0),
              CHECK (status IN ('active', 'dormant')),
              CHECK (protected IN (0, 1))
            )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS ledger_event (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              item_kind TEXT NOT NULL,
              item_id TEXT NOT NULL,
              event TEXT NOT NULL,
              detail_json TEXT NOT NULL
            )
            """)

    @contextmanager
    def _atomic(self):
        """Use a savepoint so a shared connection's outer transaction survives."""
        self.connection.execute(f"SAVEPOINT {self._savepoint}")
        try:
            yield
            self.connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
        except Exception:
            self.connection.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint}")
            self.connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
            raise

    @staticmethod
    def _key(kind: str, item_id: str) -> tuple[str, str]:
        if not isinstance(kind, str) or kind not in _KINDS:
            raise ValueError(f"unsupported ledger item kind: {kind!r}")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("item_id must be nonempty text")
        return kind, item_id.strip()

    def register(self, kind: str, item_id: str, *, protected: bool = False,
                 weight: float | None = None) -> None:
        """Register an accepted item once; repeated registration is inert."""
        kind, item_id = self._key(kind, item_id)
        if type(protected) is not bool:
            raise ValueError("protected must be a bool")
        initial = (1.0 if protected else self.params.auto_initial) if weight is None else weight
        if (not isinstance(initial, (int, float)) or isinstance(initial, bool)
                or not 0 <= initial <= 1):
            raise ValueError("weight must be between 0 and 1")
        if protected and initial != 1.0:
            raise ValueError("protected items must start at weight 1.0")
        with self._atomic():
            self.connection.execute(
                "INSERT OR IGNORE INTO item_ledger "
                "(item_kind,item_id,weight,protected,updated_seq) VALUES (?,?,?,?,0)",
                (kind, item_id, float(initial), int(protected)))

    def record(self, kind: str, item_id: str, event: str, *,
               has_dependents: bool | None = None,
               **detail: object) -> float:
        """Append one supported event and return the resulting item weight."""
        kind, item_id = self._key(kind, item_id)
        if not isinstance(event, str) or event not in _EVENTS:
            raise ValueError(f"unsupported ledger event: {event!r}")
        if has_dependents is not None and type(has_dependents) is not bool:
            raise ValueError("has_dependents must be a bool or None")
        if has_dependents is not None:
            detail["has_dependents"] = has_dependents
        try:
            detail_json = json.dumps(detail, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"))
        except (TypeError, ValueError) as error:
            raise ValueError("ledger event details must be JSON serializable") from error
        with self._atomic():
            row = self.connection.execute(
                "SELECT weight,hits,misses,protected,status FROM item_ledger "
                "WHERE item_kind=? AND item_id=?", (kind, item_id)).fetchone()
            if row is None:
                raise ValueError(f"unregistered ledger item: {kind}:{item_id}")
            weight, hits, misses, protected, status = row
            cursor = self.connection.execute(
                "INSERT INTO ledger_event (item_kind,item_id,event,detail_json) "
                "VALUES (?,?,?,?)", (kind, item_id, event, detail_json))
            seq = int(cursor.lastrowid)
            if event in {"corroborated", "confirmed", "held_out_pass"}:
                hits += 1
                if not protected:
                    weight += self.params.hit_rate * (1.0 - weight)
                if event == "held_out_pass" and status == "dormant":
                    status = "active"
            elif event in {"contradicted", "rejected", "held_out_fail"}:
                misses += 1
                if not protected:
                    weight *= 1.0 - self.params.miss_rate
            elif event == "idle_tick" and not protected:
                weight *= 1.0 - self.params.idle_decay
            weight = min(1.0, max(0.0, float(weight)))
            if (not protected and has_dependents is False
                    and weight < self.params.dormant_below
                    and status != "dormant"):
                status = "dormant"
            self.connection.execute(
                "UPDATE item_ledger SET weight=?,hits=?,misses=?,status=?,updated_seq=? "
                "WHERE item_kind=? AND item_id=?",
                (weight, hits, misses, status, seq, kind, item_id))
        return weight

    def weight(self, kind: str, item_id: str) -> float:
        """Return an item's weight, or 0 for an unregistered item."""
        kind, item_id = self._key(kind, item_id)
        row = self.connection.execute(
            "SELECT weight FROM item_ledger WHERE item_kind=? AND item_id=?",
            (kind, item_id)).fetchone()
        return float(row[0]) if row else 0.0

    def prefer(self, kind: str, item_ids: Iterable[str]) -> Preference:
        """Choose only when two leading registered weights clear the margin."""
        if not isinstance(kind, str) or kind not in _KINDS:
            raise ValueError(f"unsupported ledger item kind: {kind!r}")
        ids = sorted({str(item_id).strip() for item_id in item_ids
                      if isinstance(item_id, str) and item_id.strip()})
        active = []
        for item_id in ids:
            row = self.connection.execute(
                "SELECT weight,status FROM item_ledger "
                "WHERE item_kind=? AND item_id=?", (kind, item_id)).fetchone()
            if row is not None and row[1] == "active":
                active.append((float(row[0]), item_id))
        ranked = sorted(active, key=lambda pair: (-pair[0], pair[1]))
        if not ranked:
            return Preference("ambiguous", None, 0.0)
        if len(ranked) == 1:
            return Preference("prefer", ranked[0][1], ranked[0][0])
        margin = ranked[0][0] - ranked[1][0]
        if margin >= self.params.preference_margin:
            return Preference("prefer", ranked[0][1], margin)
        return Preference("ambiguous", None, margin)

    def stale(self, kind: str, *, max_weight: float,
              min_misses: int) -> list[str]:
        """List low-weight, repeatedly rejected, unprotected items for review."""
        if not isinstance(kind, str) or kind not in _KINDS:
            raise ValueError(f"unsupported ledger item kind: {kind!r}")
        if (not isinstance(max_weight, (int, float)) or isinstance(max_weight, bool)
                or not 0 <= max_weight <= 1
                or type(min_misses) is not int or min_misses < 0):
            raise ValueError("stale thresholds are invalid")
        rows = self.connection.execute(
            "SELECT item_id FROM item_ledger WHERE item_kind=? AND weight<=? "
            "AND misses>=? AND protected=0 AND status='active' "
            "ORDER BY item_id", (kind, max_weight, min_misses)).fetchall()
        return [str(row[0]) for row in rows]

    def events(self) -> list[dict[str, object]]:
        """Return the append-only event log in deterministic sequence order."""
        rows = self.connection.execute(
            "SELECT seq,item_kind,item_id,event,detail_json "
            "FROM ledger_event ORDER BY seq").fetchall()
        return [{"seq": row[0], "kind": row[1], "id": row[2],
                 "event": row[3], "detail": json.loads(row[4])}
                for row in rows]
