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
_SCHEMA_VERSION = 2
_V1_TABLES = {"answer_feedback"}
_TABLES = {"answer_feedback", "feedback_context"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _normalize_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "kind": str(row["kind"]), "id": str(row["id"])}
    for field in ("subject", "relation", "object"):
        if row.get(field) is not None:
            normalized[field] = str(row[field])
    if row.get("qualifiers") is not None:
        normalized["qualifiers"] = [
            [str(name), str(value)] for name, value in row["qualifiers"]]
    if row.get("sources") is not None:
        normalized["sources"] = sorted({str(value)
                                         for value in row["sources"] if value})
    return normalized


def feedback_answer_id(question: str, answer: str,
                       evidence_refs: Iterable[Mapping[str, Any]]) -> str:
    """Return a deterministic identifier for an answer and its evidence set."""
    payload = {
        "question": question.strip(),
        "answer": answer.strip(),
        # Keep event identity stable as display metadata grows. The fact id is
        # itself a hash of its proposition and qualifiers; the richer triple
        # and source list are persisted separately in evidence_json.
        "evidence": sorted(
            ({"kind": str(row["kind"]), "id": str(row["id"])}
             for row in evidence_refs),
            key=lambda row: (row["kind"], row["id"])),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def collect_feedback_refs(response: Any = None, research: Any = None
                          ) -> list[dict[str, Any]]:
    """Collect stable fact triples, rule ids, and source refs for an answer."""
    refs: dict[tuple[str, str], dict[str, Any]] = {}

    def add_ref(kind: str, value: str, **details: Any) -> None:
        key = (kind, value)
        row = refs.setdefault(key, {"kind": kind, "id": value})
        for name, detail in details.items():
            if detail is not None:
                if name == "sources":
                    row[name] = sorted(set(row.get(name, ())) | set(detail))
                else:
                    row[name] = detail

    def add_fact(row: Mapping[str, Any]) -> None:
        fields = {field: str(row.get(field, "")).strip()
                  for field in ("subject", "relation", "object")}
        if not all(fields.values()):
            add_sources(row)
            return
        qualifiers = sorted((str(name), str(value))
                            for name, value in row.get("qualifiers", ()) or ())
        descriptor = {**fields, "qualifiers": qualifiers}
        fact_id = hashlib.sha256(
            _canonical_json(descriptor).encode("utf-8")).hexdigest()
        add_ref("fact", fact_id, **fields, qualifiers=qualifiers,
                sources=sorted({str(source) for source in row.get("sources", ())
                                if source}))
        add_sources(row)

    def add_sources(row: Mapping[str, Any], kind: str = "source") -> None:
        for field in ("fact_id", "rule_id", "schema_id", "source_id",
                      "document_id", "citation", "source", "chunk_id",
                      "sentence_id"):
            value = row.get(field)
            if value is not None and str(value).strip():
                ref_kind = ("rule" if field == "rule_id" else
                            "fact" if field == "fact_id" else
                            "schema" if field == "schema_id" else kind)
                add_ref(ref_kind, str(value).strip())
        for value in row.get("sources", ()) or ():
            if str(value).strip():
                add_ref(kind, str(value).strip())

    def visit_proof(node: Any) -> None:
        if not isinstance(node, Mapping):
            return
        fact = node.get("fact")
        if isinstance(fact, Mapping):
            add_fact(fact)
        rule = node.get("rule")
        if isinstance(rule, Mapping):
            add_sources(rule)
        schema = node.get("schema")
        if isinstance(schema, Mapping):
            add_sources(schema)
        type_fact = node.get("relation_type_fact")
        if isinstance(type_fact, Mapping):
            add_fact(type_fact)
        for item in node.get("middle_kind_facts", ()) or ():
            if isinstance(item, Mapping):
                add_fact(item)
        single_kind = node.get("middle_kind_fact")
        if isinstance(single_kind, Mapping):
            add_fact(single_kind)
        for premise in node.get("premises", ()) or ():
            visit_proof(premise)

    if response is not None:
        for row in (getattr(response, "evidence", None) or []):
            if isinstance(row, Mapping):
                add_fact(row)
        for proof in (getattr(response, "proofs", None) or []):
            if isinstance(proof, Mapping):
                visit_proof(proof)
            else:
                for row in proof:
                    if isinstance(row, Mapping):
                        add_fact(row)
        for proof in (getattr(response, "inference_proofs", None) or []):
            visit_proof(proof)
    if research is not None:
        for field in ("source_sentences", "passages"):
            for row in (getattr(research, field, None) or []):
                if isinstance(row, Mapping):
                    add_sources(row, "source")
    return [refs[key] for key in sorted(refs)]


def collect_translation_feedback_refs(result: Any) -> list[dict[str, Any]]:
    """Identify the aligned model examples behind a completed translation.

    Translation examples do not necessarily have document citations (some are
    taught directly), so the reference is a stable fingerprint of the exact
    language pair, frame, output, and aligned examples used. This records
    feedback provenance without treating the feedback as a new translation
    example or as a quality judgment by itself.
    """
    if (getattr(result, "status", None) != "translated"
            or not getattr(result, "output", None)
            or not getattr(result, "language_pair", None)):
        return []
    examples = []
    for row in getattr(result, "evidence", ()) or ():
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("source", "")).strip()
        target = str(row.get("target", "")).strip()
        if source and target:
            examples.append({"source": source, "target": target})
    if not examples:
        return []
    payload = {
        "language_pair": list(result.language_pair),
        "register": getattr(result, "register", None),
        "template": getattr(result, "template", None),
        "output": result.output,
        "examples": sorted(examples, key=lambda row: (row["source"], row["target"])),
    }
    frame_id = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    example_ids = sorted(hashlib.sha256(
        _canonical_json(row).encode("utf-8")).hexdigest() for row in examples)
    return [{"kind": "translation_frame", "id": frame_id,
             "sources": example_ids}]


def render_feedback_refs(evidence_refs: Iterable[Mapping[str, Any]]) -> str:
    """Render feedback references so a user can identify the proposition used."""
    rendered = []
    for item in evidence_refs:
        if (item.get("kind") == "fact"
                and all(item.get(field) for field in
                        ("subject", "relation", "object"))):
            sources = ", ".join(item.get("sources", ()))
            label = (f"fact {item['subject']} — {item['relation']} → "
                     f"{item['object']}")
            if sources:
                label += f" (sources: {sources})"
            rendered.append(label)
        elif item.get("kind") == "translation_frame":
            examples = ", ".join(item.get("sources", ()))
            label = f"translation frame {item['id']}"
            if examples:
                label += f" (aligned example ids: {examples})"
            rendered.append(label)
        else:
            rendered.append(f"{item['kind']}={item['id']}")
    return ", ".join(rendered) or "no evidence references"


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
            if tables:
                if (tables == _V1_TABLES and app_id == _APPLICATION_ID
                        and version == 1):
                    # Preserve the append-only event history while adding the
                    # one mutable pointer needed to resume feedback after a
                    # process restart.
                    pass
                elif (tables != _TABLES or app_id != _APPLICATION_ID
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
            connection.execute("""CREATE TABLE IF NOT EXISTS feedback_context (
                id INTEGER PRIMARY KEY CHECK(id=1),
                answer_id TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                evidence_json TEXT NOT NULL
            )""")
            connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    def record(self, verdict: str, question: str, answer: str,
               evidence_refs: Iterable[Mapping[str, Any]]) -> tuple[str, bool]:
        if verdict not in {"right", "wrong"}:
            raise ValueError("verdict must be 'right' or 'wrong'")
        refs = sorted((_normalize_ref(row) for row in evidence_refs),
                      key=lambda row: (row["kind"], row["id"]))
        answer_id = feedback_answer_id(question, answer, refs)
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO answer_feedback "
                "(answer_id,verdict,question,answer,evidence_json) "
                "VALUES (?,?,?,?,?)",
                (answer_id, verdict, question.strip(), answer.strip(),
                 _canonical_json(refs)))
            return answer_id, cursor.rowcount == 1

    def set_pending(self, question: str, answer: str,
                    evidence_refs: Iterable[Mapping[str, Any]]) -> None:
        """Remember the current answer target for feedback across restarts."""
        question = question.strip()
        answer = answer.strip()
        refs = sorted((_normalize_ref(row) for row in evidence_refs),
                      key=lambda row: (row["kind"], row["id"]))
        if not question or not answer or not refs:
            self.clear_pending()
            return
        answer_id = feedback_answer_id(question, answer, refs)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO feedback_context "
                "(id,answer_id,question,answer,evidence_json) VALUES (1,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET answer_id=excluded.answer_id, "
                "question=excluded.question, answer=excluded.answer, "
                "evidence_json=excluded.evidence_json",
                (answer_id, question, answer, _canonical_json(refs)))

    def pending(self) -> dict[str, Any] | None:
        """Return the validated answer target for a subsequent feedback turn."""
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT answer_id,question,answer,evidence_json "
                "FROM feedback_context WHERE id=1").fetchone()
        if row is None:
            return None
        try:
            if not all(isinstance(value, str) for value in row):
                raise ValueError
            refs = json.loads(row[3])
            if not isinstance(refs, list) or not refs:
                raise ValueError
            normalized = sorted((_normalize_ref(item) for item in refs),
                                key=lambda item: (item["kind"], item["id"]))
            if normalized != refs or feedback_answer_id(row[1], row[2], refs) != row[0]:
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("stored feedback context is malformed") from error
        return {"answer_id": row[0], "question": row[1], "answer": row[2],
                "evidence": refs}

    def clear_pending(self) -> None:
        """Forget the current answer target without changing feedback history."""
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM feedback_context WHERE id=1")

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

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT feedback_seq,answer_id,verdict,question,answer,evidence_json "
                "FROM answer_feedback ORDER BY feedback_seq DESC LIMIT ?",
                (limit,)).fetchall()
        rows.reverse()
        return [{"feedback_seq": row["feedback_seq"],
                 "answer_id": row["answer_id"], "verdict": row["verdict"],
                 "question": row["question"], "answer": row["answer"],
                 "evidence": json.loads(row["evidence_json"])} for row in rows]

    def event(self, feedback_seq: int) -> dict[str, Any] | None:
        if (not isinstance(feedback_seq, int) or isinstance(feedback_seq, bool)
                or feedback_seq < 1):
            raise ValueError("feedback sequence must be a positive integer")
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT feedback_seq,answer_id,verdict,question,answer,evidence_json "
                "FROM answer_feedback WHERE feedback_seq=?",
                (feedback_seq,)).fetchone()
        if row is None:
            return None
        return {"feedback_seq": row["feedback_seq"],
                "answer_id": row["answer_id"], "verdict": row["verdict"],
                "question": row["question"], "answer": row["answer"],
                "evidence": json.loads(row["evidence_json"])}

    def has_verdict(self, answer_id: str, verdict: str) -> bool:
        if verdict not in {"right", "wrong"}:
            raise ValueError("verdict must be 'right' or 'wrong'")
        with sqlite3.connect(self.path) as connection:
            return connection.execute(
                "SELECT 1 FROM answer_feedback WHERE answer_id=? AND verdict=?",
                (answer_id, verdict)).fetchone() is not None
