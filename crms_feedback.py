"""Persistent user feedback attributed to the evidence behind a CRMS answer.

Feedback is recorded for later review. It does not accept, reject, or reweight
knowledge by itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping


_APPLICATION_ID = 0x43524642  # CRFB
_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def feedback_answer_id(question: str, answer: str,
                       evidence_refs: Iterable[Mapping[str, str]]) -> str:
    """Return a deterministic identifier for an answer and its evidence set."""
    payload = {
        "question": question.strip(),
        "answer": answer.strip(),
        "evidence": sorted(
            ({"kind": str(row["kind"]), "id": str(row["id"])}
             for row in evidence_refs), key=lambda row: (row["kind"], row["id"])),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def collect_feedback_refs(response: Any = None, research: Any = None
                          ) -> list[dict[str, str]]:
    """Collect stable fact, rule, and source references from a chat answer."""
    refs: set[tuple[str, str]] = set()

    def add_sources(row: Mapping[str, Any], kind: str = "source") -> None:
        for field in ("fact_id", "rule_id", "schema_id", "source_id",
                      "document_id", "citation", "source", "chunk_id",
                      "sentence_id"):
            value = row.get(field)
            if value is not None and str(value).strip():
                ref_kind = ("rule" if field == "rule_id" else
                            "fact" if field == "fact_id" else kind)
                refs.add((ref_kind, str(value).strip()))
        for value in row.get("sources", ()) or ():
            if str(value).strip():
                refs.add((kind, str(value).strip()))

    def visit_proof(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        fact = node.get("fact")
        if isinstance(fact, Mapping):
            add_sources(fact, "source")
        rule = node.get("rule")
        if isinstance(rule, Mapping):
            add_sources(rule)
        schema = node.get("schema")
        if isinstance(schema, Mapping):
            add_sources(schema)
        type_fact = node.get("relation_type_fact")
        if isinstance(type_fact, Mapping):
            add_sources(type_fact, "source")
        for item in node.get("middle_kind_facts", ()) or ():
            if isinstance(item, Mapping):
                add_sources(item, "source")
        single_kind = node.get("middle_kind_fact")
        if isinstance(single_kind, Mapping):
            add_sources(single_kind, "source")
        for premise in node.get("premises", ()) or ():
            visit_proof(premise)

    if response is not None:
        for row in (getattr(response, "evidence", None) or []):
            if isinstance(row, Mapping):
                add_sources(row, "source")
        for proof in (getattr(response, "proofs", None) or []):
            for row in proof:
                if isinstance(row, Mapping):
                    add_sources(row, "source")
        for proof in (getattr(response, "inference_proofs", None) or []):
            visit_proof(proof)
    if research is not None:
        for field in ("source_sentences", "passages"):
            for row in (getattr(research, field, None) or []):
                if isinstance(row, Mapping):
                    add_sources(row, "source")
    return [{"kind": kind, "id": value}
            for kind, value in sorted(refs)]


class AnswerFeedbackStore:
    """Small SQLite append-only log for explicit `/right` and `/wrong` signals."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if tables and (tables != {"answer_feedback"}
                           or app_id != _APPLICATION_ID
                           or version != _SCHEMA_VERSION):
                raise ValueError("existing file is not a CRMS feedback database")
            connection.execute("""CREATE TABLE IF NOT EXISTS answer_feedback (
                feedback_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK(verdict IN ('right','wrong')),
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                UNIQUE(answer_id, verdict)
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS feedback_answer_id "
                               "ON answer_feedback(answer_id)")
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def record(self, verdict: str, question: str, answer: str,
               evidence_refs: Iterable[Mapping[str, str]]) -> tuple[str, bool]:
        if verdict not in {"right", "wrong"}:
            raise ValueError("verdict must be 'right' or 'wrong'")
        refs = sorted(
            ({"kind": str(row["kind"]), "id": str(row["id"])}
             for row in evidence_refs), key=lambda row: (row["kind"], row["id"]))
        answer_id = feedback_answer_id(question, answer, refs)
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO answer_feedback "
                "(answer_id,verdict,question,answer,evidence_json) "
                "VALUES (?,?,?,?,?)",
                (answer_id, verdict, question.strip(), answer.strip(),
                 _canonical_json(refs)))
            return answer_id, cursor.rowcount == 1

    def events(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT feedback_seq,answer_id,verdict,question,answer,evidence_json "
                "FROM answer_feedback ORDER BY feedback_seq").fetchall()
        return [{"feedback_seq": row["feedback_seq"],
                 "answer_id": row["answer_id"], "verdict": row["verdict"],
                 "question": row["question"], "answer": row["answer"],
                 "evidence": json.loads(row["evidence_json"])} for row in rows]
