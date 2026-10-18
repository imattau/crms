"""Optional indexed SQLite mapping for CRMS positive and negative facts."""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
import json
import sqlite3
from typing import Any


def _freeze(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


class SQLiteFactMap(MutableMapping):
    """Dictionary-compatible fact mapping backed by indexed SQLite rows."""

    TABLES = {"positive_facts", "negative_facts"}

    def __init__(self, connection: sqlite3.Connection, table: str) -> None:
        if table not in self.TABLES:
            raise ValueError("unsupported SQLite fact table")
        self.connection = connection
        self.table = table
        connection.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
            key_json TEXT PRIMARY KEY,
            relation_key TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            object_key TEXT NOT NULL,
            payload_json TEXT NOT NULL
        ) WITHOUT ROWID""")
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_relation_subject "
            f"ON {table}(relation_key, subject_key)")
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_relation_object "
            f"ON {table}(relation_key, object_key)")
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_subject "
            f"ON {table}(subject_key)")
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_object "
            f"ON {table}(object_key)")

    @staticmethod
    def _encode_key(key: tuple[Any, ...]) -> str:
        return json.dumps(key, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_key(value: str) -> tuple[Any, ...]:
        result = _freeze(json.loads(value))
        if not isinstance(result, tuple):
            raise ValueError("stored SQLite fact key is malformed")
        return result

    @staticmethod
    def _decode_fact(value: str):
        from crms_knowledge import FactEvidence
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("stored SQLite fact is malformed")
        data["sources"] = tuple(data.get("sources", ()))
        data["qualifiers"] = tuple(tuple(item)
                                   for item in data.get("qualifiers", ()))
        return FactEvidence(**data)

    def __getitem__(self, key: tuple[Any, ...]):
        row = self.connection.execute(
            f"SELECT payload_json FROM {self.table} WHERE key_json=?",
            (self._encode_key(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        return self._decode_fact(row[0])

    def __setitem__(self, key: tuple[Any, ...], fact: Any) -> None:
        subject = json.dumps(key[0], ensure_ascii=False, separators=(",", ":"))
        relation = json.dumps(key[1], ensure_ascii=False, separators=(",", ":"))
        obj = json.dumps(key[2], ensure_ascii=False, separators=(",", ":"))
        payload = json.dumps({
            "subject": fact.subject, "relation": fact.relation,
            "object": fact.object, "sources": list(fact.sources),
            "qualifiers": [list(item) for item in fact.qualifiers],
        }, ensure_ascii=False, separators=(",", ":"))
        self.connection.execute(
            f"""INSERT INTO {self.table}
               (key_json,relation_key,subject_key,object_key,payload_json)
               VALUES (?,?,?,?,?)
               ON CONFLICT(key_json) DO UPDATE SET
                 relation_key=excluded.relation_key,
                 subject_key=excluded.subject_key,
                 object_key=excluded.object_key,
                 payload_json=excluded.payload_json""",
            (self._encode_key(key), relation, subject, obj, payload))

    def __delitem__(self, key: tuple[Any, ...]) -> None:
        cursor = self.connection.execute(
            f"DELETE FROM {self.table} WHERE key_json=?",
            (self._encode_key(key),))
        if cursor.rowcount == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        cursor = self.connection.execute(
            f"SELECT key_json FROM {self.table} ORDER BY key_json")
        for (key_json,) in cursor:
            yield self._decode_key(key_json)

    def __len__(self) -> int:
        return int(self.connection.execute(
            f"SELECT count(*) FROM {self.table}").fetchone()[0])

    def values(self):
        cursor = self.connection.execute(
            f"SELECT payload_json FROM {self.table} ORDER BY key_json")
        for (payload,) in cursor:
            yield self._decode_fact(payload)

    def items(self):
        cursor = self.connection.execute(
            f"SELECT key_json,payload_json FROM {self.table} ORDER BY key_json")
        for key_json, payload in cursor:
            yield self._decode_key(key_json), self._decode_fact(payload)

    def lookup(self, relation: tuple[str, ...], bound: tuple[str, ...],
               bound_field: str):
        column = "object_key" if bound_field == "object" else "subject_key"
        relation_json = json.dumps(relation, ensure_ascii=False,
                                   separators=(",", ":"))
        bound_json = json.dumps(bound, ensure_ascii=False,
                                separators=(",", ":"))
        cursor = self.connection.execute(
            f"SELECT payload_json FROM {self.table} "
            f"WHERE relation_key=? AND {column}=? ORDER BY key_json",
            (relation_json, bound_json))
        for (payload,) in cursor:
            yield self._decode_fact(payload)

    def select_relations(self, relations):
        relation_json = sorted({
            json.dumps(tuple(value), ensure_ascii=False, separators=(",", ":"))
            for value in relations
        })
        for offset in range(0, len(relation_json), 500):
            batch = relation_json[offset:offset + 500]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            cursor = self.connection.execute(
                f"SELECT payload_json FROM {self.table} "
                f"WHERE relation_key IN ({placeholders}) ORDER BY key_json",
                batch)
            for (payload,) in cursor:
                yield self._decode_fact(payload)

    def relation_keys(self):
        """Return distinct normalized relations without scanning fact payloads."""
        cursor = self.connection.execute(
            f"SELECT DISTINCT relation_key FROM {self.table} "
            "ORDER BY relation_key")
        for (value,) in cursor:
            relation = _freeze(json.loads(value))
            if not isinstance(relation, tuple):
                raise ValueError("stored fact relation key is malformed")
            yield relation

    def rule_discovery_values(self):
        """Yield only facts that can participate in a two-edge join.

        Facts whose object is never a subject, and whose subject is never an
        object, cannot participate in any chain. Keep standalone ``is-a``
        facts because the typed three-premise discovery path uses them as
        middle-entity declarations. The indexed endpoint columns make this
        filter cheap while preserving every possible rule example.
        """
        is_a = json.dumps(("is", "a"), ensure_ascii=False,
                          separators=(",", ":"))
        cursor = self.connection.execute(
            f"""SELECT fact.payload_json FROM {self.table} AS fact
                WHERE fact.relation_key=?
                   OR EXISTS (SELECT 1 FROM {self.table} AS following
                              WHERE following.subject_key=fact.object_key)
                   OR EXISTS (SELECT 1 FROM {self.table} AS preceding
                              WHERE preceding.object_key=fact.subject_key)
                   OR EXISTS (SELECT 1 FROM {self.table} AS first_edge
                              JOIN {self.table} AS second_edge
                                ON second_edge.subject_key=first_edge.object_key
                              WHERE first_edge.subject_key=fact.subject_key
                                AND second_edge.object_key=fact.object_key)
                   OR EXISTS (SELECT 1 FROM {self.table} AS first_edge
                              JOIN {self.table} AS second_edge
                                ON second_edge.subject_key=first_edge.object_key
                              JOIN {self.table} AS third_edge
                                ON third_edge.subject_key=second_edge.object_key
                              WHERE first_edge.subject_key=fact.subject_key
                                AND third_edge.object_key=fact.object_key)
                ORDER BY fact.key_json""", (is_a,))
        for (payload,) in cursor:
            yield self._decode_fact(payload)

    def contains_any_phrase(self, phrases) -> bool:
        """Check exact normalized subject/relation/object phrases by index."""
        encoded = sorted({self._encode_key(tuple(phrase)) for phrase in phrases})
        for offset in range(0, len(encoded), 200):
            batch = encoded[offset:offset + 200]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            row = self.connection.execute(
                f"SELECT 1 FROM {self.table} WHERE "
                f"subject_key IN ({placeholders}) OR "
                f"relation_key IN ({placeholders}) OR "
                f"object_key IN ({placeholders}) LIMIT 1",
                (*batch, *batch, *batch)).fetchone()
            if row is not None:
                return True
        return False

    def select_relation_subjects(self, relation: tuple[str, ...], subjects):
        relation_json = json.dumps(tuple(relation), ensure_ascii=False,
                                   separators=(",", ":"))
        subject_json = sorted({
            json.dumps(tuple(value), ensure_ascii=False, separators=(",", ":"))
            for value in subjects
        })
        for offset in range(0, len(subject_json), 500):
            batch = subject_json[offset:offset + 500]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            cursor = self.connection.execute(
                f"SELECT payload_json FROM {self.table} "
                f"WHERE relation_key=? AND subject_key IN ({placeholders}) "
                "ORDER BY key_json", (relation_json, *batch))
            for (payload,) in cursor:
                yield self._decode_fact(payload)

    def clear(self) -> None:
        self.connection.execute(f"DELETE FROM {self.table}")

    def close(self) -> None:
        self.connection.close()

    def __deepcopy__(self, memo):
        # Candidate simulations need an isolated mutable snapshot. Keep the
        # normal dict representation for those short-lived copies.
        import copy
        return copy.deepcopy(dict(self.items()), memo)
