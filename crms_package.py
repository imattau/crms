"""Portable SQLite model files for learned CRMS memories and source text."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile


FORMAT = "crms-learned-model"
_VERSION_RULE_SQL = 2
_VERSION_KNOWLEDGE_SQL = 3
VERSION = 4
_LEGACY_VERSIONS = {1, _VERSION_RULE_SQL, _VERSION_KNOWLEDGE_SQL}
APPLICATION_ID = int.from_bytes(b"CRMS", "big")
_MEMORY_NAMES = ("knowledge", "rules", "math", "translations")
_MAX_MEMBER_BYTES = 512 * 1024 * 1024
_REQUIRED_TABLES = {"model_metadata", "learned_memories"}
_RESEARCH_TABLES = {"research_documents"}
_RULE_TABLES = {"model_rule_settings", "model_rule_examples",
                "model_rule_procedures", "model_rule_artifacts"}
_KNOWLEDGE_SQL_TABLES = {"knowledge_metadata", "knowledge_payload",
                         "inference_rules", "derived_cases",
                         "positive_facts", "negative_facts"}
_KNOWLEDGE_RECORD_TABLES = {"knowledge_records"}
_KNOWLEDGE_TABLES = _KNOWLEDGE_SQL_TABLES | _KNOWLEDGE_RECORD_TABLES
_KNOWLEDGE_RECORD_SECTIONS = frozenset({
    "entity_aliases", "entity_alias_explicit_sources",
    "fact_pattern_alias_sources", "question_examples",
    "induced_question_frames", "induced_qualified_question_frames",
    "induced_multi_qualified_question_frames", "qualified_question_examples",
    "multi_qualified_question_examples", "polar_question_examples",
    "qualified_polar_question_examples", "path_question_examples",
    "counterfactual_source_examples", "counterfactual_path_examples",
    "about_question_examples", "fact_pattern_examples",
    "context_fact_patterns", "fact_pattern_surfaces",
    "fact_pattern_predicates", "fact_pattern_predicate_sources",
    "fact_pattern_surface_sources", "fact_pattern_polarities",
})


def _knowledge_record_bytes(record: object) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _knowledge_record_anchor(record: object) -> str:
    if isinstance(record, dict):
        for field in ("relation", "relations", "template", "qualifier_names",
                      "alias", "prefix", "start", "target"):
            if field in record:
                return json.dumps(record[field], ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(_knowledge_record_bytes(record)).hexdigest()


def _create_rule_tables(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE model_rule_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE model_rule_examples (
        phrase TEXT NOT NULL, ordinal INTEGER NOT NULL,
        input_json TEXT NOT NULL, output_json TEXT NOT NULL,
        PRIMARY KEY(phrase,ordinal)
    ) WITHOUT ROWID""")
    db.execute("""CREATE TABLE model_rule_procedures (
        phrase TEXT PRIMARY KEY, steps_json TEXT NOT NULL
    ) WITHOUT ROWID""")
    db.execute("""CREATE TABLE model_rule_artifacts (
        kind TEXT NOT NULL, ordinal INTEGER NOT NULL, payload_json TEXT NOT NULL,
        PRIMARY KEY(kind,ordinal)
    ) WITHOUT ROWID""")


def _write_rule_tables(db: sqlite3.Connection, payload: dict) -> None:
    settings = {key: value for key, value in payload.items()
                if key not in {"examples", "procedures", "accepted_primitives",
                               "accepted_primitive_artifacts", "no_fit_cases"}}
    db.execute("INSERT INTO model_rule_settings VALUES (1,?)",
               (json.dumps(settings, ensure_ascii=False, separators=(",", ":")),))
    db.executemany(
        "INSERT INTO model_rule_examples VALUES (?,?,?,?)",
        ((phrase, ordinal,
          json.dumps(pair[0], ensure_ascii=False, separators=(",", ":")),
          json.dumps(pair[1], ensure_ascii=False, separators=(",", ":")))
         for phrase, examples in payload["examples"].items()
         for ordinal, pair in enumerate(examples)))
    db.executemany(
        "INSERT INTO model_rule_procedures VALUES (?,?)",
        ((phrase, json.dumps(steps, ensure_ascii=False, separators=(",", ":")))
         for phrase, steps in payload["procedures"].items()))
    db.executemany(
        "INSERT INTO model_rule_artifacts VALUES (?,?,?)",
        ((kind, ordinal,
          json.dumps(value, ensure_ascii=False, separators=(",", ":")))
         for kind in ("accepted_primitives", "accepted_primitive_artifacts",
                      "no_fit_cases")
         for ordinal, value in enumerate(payload[kind])))


def _read_rule_tables(db: sqlite3.Connection) -> dict:
    row = db.execute(
        "SELECT payload_json FROM model_rule_settings WHERE id=1").fetchone()
    if row is None:
        raise ValueError("model database has no normalized rule settings")
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        raise ValueError("model rule settings are malformed")
    examples: dict[str, list[list]] = {}
    for phrase, _ordinal, inputs, outputs in db.execute(
            "SELECT phrase,ordinal,input_json,output_json "
            "FROM model_rule_examples ORDER BY phrase,ordinal"):
        examples.setdefault(phrase, []).append([json.loads(inputs), json.loads(outputs)])
    payload["examples"] = examples
    payload["procedures"] = {
        phrase: json.loads(steps)
        for phrase, steps in db.execute(
            "SELECT phrase,steps_json FROM model_rule_procedures ORDER BY phrase")
    }
    artifacts: dict[str, list] = {}
    for kind, _ordinal, data in db.execute(
            "SELECT kind,ordinal,payload_json FROM model_rule_artifacts "
            "ORDER BY kind,ordinal"):
        artifacts.setdefault(kind, []).append(json.loads(data))
    for kind in ("accepted_primitives", "accepted_primitive_artifacts", "no_fit_cases"):
        payload[kind] = artifacts.get(kind, [])
    if set(artifacts) - {"accepted_primitives", "accepted_primitive_artifacts",
                         "no_fit_cases"}:
        raise ValueError("model database has an unknown rule-artifact kind")
    return payload


def _create_knowledge_tables(db: sqlite3.Connection) -> None:
    db.execute("CREATE TABLE knowledge_metadata (key TEXT PRIMARY KEY, "
               "value TEXT NOT NULL) WITHOUT ROWID")
    db.execute("CREATE TABLE knowledge_payload (section TEXT PRIMARY KEY, "
               "payload_json TEXT NOT NULL) WITHOUT ROWID")
    db.execute("CREATE TABLE inference_rules (rule_key TEXT PRIMARY KEY, "
               "payload_json TEXT NOT NULL) WITHOUT ROWID")
    db.execute("CREATE TABLE derived_cases (case_key TEXT PRIMARY KEY, "
               "subject_key TEXT NOT NULL, relation_key TEXT NOT NULL, "
               "object_key TEXT NOT NULL, payload_json TEXT NOT NULL) WITHOUT ROWID")
    for table in ("positive_facts", "negative_facts"):
        db.execute(f"CREATE TABLE {table} (key_json TEXT PRIMARY KEY, "
                   "relation_key TEXT NOT NULL, subject_key TEXT NOT NULL, "
                   "object_key TEXT NOT NULL, payload_json TEXT NOT NULL) WITHOUT ROWID")
        db.execute(f"CREATE INDEX {table}_relation_subject "
                   f"ON {table}(relation_key,subject_key)")
        db.execute(f"CREATE INDEX {table}_relation_object "
                   f"ON {table}(relation_key,object_key)")
    db.execute("CREATE INDEX derived_cases_conclusion "
               "ON derived_cases(relation_key,subject_key,object_key)")
    db.execute("CREATE TABLE knowledge_records (section TEXT NOT NULL, "
               "ordinal INTEGER NOT NULL, anchor_key TEXT NOT NULL, "
               "record_key TEXT NOT NULL, payload_json TEXT NOT NULL, "
               "PRIMARY KEY(section,ordinal)) WITHOUT ROWID")
    db.execute("CREATE INDEX knowledge_records_anchor "
               "ON knowledge_records(section,anchor_key)")
    db.execute("CREATE INDEX knowledge_records_digest "
               "ON knowledge_records(section,record_key)")


def _write_knowledge_tables(db: sqlite3.Connection, payload: dict) -> None:
    from crms_knowledge import CRMSKnowledgeBase, _tokens

    db.executemany("INSERT INTO knowledge_metadata VALUES (?,?)", [
        ("format", "crms-knowledge-database"), ("version", "2")])
    relational_sections = {"facts", "negative_facts", "inference_rules",
                           "derived_cases"}
    db.executemany(
        "INSERT INTO knowledge_payload VALUES (?,?)",
        ((name, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
         for name, value in payload.items()
         if name not in relational_sections
         and name not in _KNOWLEDGE_RECORD_SECTIONS))
    db.executemany(
        "INSERT INTO knowledge_records VALUES (?,?,?,?,?)",
        ((section, ordinal, _knowledge_record_anchor(record),
          _sha256(_knowledge_record_bytes(record)),
          _knowledge_record_bytes(record).decode("utf-8"))
         for section in sorted(_KNOWLEDGE_RECORD_SECTIONS)
         for ordinal, record in enumerate(payload.get(section, []))))
    db.executemany(
        "INSERT INTO inference_rules VALUES (?,?)",
        ((json.dumps(_tokens(item["rule_id"]), ensure_ascii=False,
                     separators=(",", ":")),
          json.dumps(item, ensure_ascii=False, separators=(",", ":")))
         for item in payload.get("inference_rules", [])))
    for name, table in (("facts", "positive_facts"),
                        ("negative_facts", "negative_facts")):
        for item in payload.get(name, []):
            qualifiers = tuple(tuple(pair) for pair in item.get("qualifiers", []))
            key = CRMSKnowledgeBase._fact_key(
                item["subject"], item["relation"], item["object"],
                CRMSKnowledgeBase._normalize_qualifiers(dict(qualifiers)))
            db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?)", (
                json.dumps(key, ensure_ascii=False, separators=(",", ":")),
                json.dumps(_tokens(item["relation"]), ensure_ascii=False,
                           separators=(",", ":")),
                json.dumps(_tokens(item["subject"]), ensure_ascii=False,
                           separators=(",", ":")),
                json.dumps(_tokens(item["object"]), ensure_ascii=False,
                           separators=(",", ":")),
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))))
    for item in payload.get("derived_cases", []):
        conclusion = item["conclusion"]
        qualifiers = CRMSKnowledgeBase._normalize_qualifiers(
            dict(item.get("qualifiers", [])))
        case_key = CRMSKnowledgeBase._fact_key(
            conclusion["subject"], conclusion["relation"],
            conclusion["object"], qualifiers)
        db.execute("INSERT INTO derived_cases VALUES (?,?,?,?,?)", (
            json.dumps(case_key, ensure_ascii=False, separators=(",", ":")),
            json.dumps(_tokens(conclusion["subject"]), ensure_ascii=False,
                       separators=(",", ":")),
            json.dumps(_tokens(conclusion["relation"]), ensure_ascii=False,
                       separators=(",", ":")),
            json.dumps(_tokens(conclusion["object"]), ensure_ascii=False,
                       separators=(",", ":")),
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))))


def _read_knowledge_tables(db: sqlite3.Connection) -> dict:
    metadata = dict(db.execute("SELECT key,value FROM knowledge_metadata"))
    version = metadata.get("version")
    if (metadata.get("format") != "crms-knowledge-database"
            or version not in {"1", "2"}):
        raise ValueError("model database knowledge metadata is invalid")
    payload = {section: json.loads(value) for section, value in db.execute(
        "SELECT section,payload_json FROM knowledge_payload")}
    if version == "2":
        records: dict[str, list[tuple[int, object]]] = {}
        for section, ordinal, anchor, digest, raw in db.execute(
                "SELECT section,ordinal,anchor_key,record_key,payload_json "
                "FROM knowledge_records ORDER BY section,ordinal"):
            if section not in _KNOWLEDGE_RECORD_SECTIONS:
                raise ValueError("model database has an unknown knowledge record section")
            record = json.loads(raw)
            if (_sha256(_knowledge_record_bytes(record)) != digest
                    or _knowledge_record_anchor(record) != anchor):
                raise ValueError("model database knowledge record failed integrity check")
            records.setdefault(section, []).append((ordinal, record))
        for section in _KNOWLEDGE_RECORD_SECTIONS:
            rows = records.get(section, [])
            if [ordinal for ordinal, _ in rows] != list(range(len(rows))):
                raise ValueError("model database knowledge record order is malformed")
            if section in payload:
                raise ValueError("model database duplicates a knowledge record section")
            payload[section] = [record for _, record in rows]
    payload["inference_rules"] = [json.loads(value) for (value,) in db.execute(
        "SELECT payload_json FROM inference_rules ORDER BY rule_key")]
    payload["derived_cases"] = [json.loads(value) for (value,) in db.execute(
        "SELECT payload_json FROM derived_cases ORDER BY case_key")]
    for name, table in (("facts", "positive_facts"),
                        ("negative_facts", "negative_facts")):
        payload[name] = [json.loads(value) for (value,) in db.execute(
            f"SELECT payload_json FROM {table} ORDER BY key_json")]
    return payload


def _knowledge_payload_signature(payload: dict) -> str:
    normalized = dict(payload)
    for name in ("facts", "negative_facts", "inference_rules", "derived_cases"):
        normalized[name] = sorted(
            normalized.get(name, []),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")))
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_model_database(output: str | Path, *, knowledge: str | Path,
                          rules: str | Path, math: str | Path | None = None,
                          translations: str | Path | None = None,
                          research_index: str | Path | None = None) -> Path:
    """Create one SQLite model database from learned memories and sources."""
    sources = {"knowledge": Path(knowledge), "rules": Path(rules)}
    if math is not None:
        sources["math"] = Path(math)
    if translations is not None:
        sources["translations"] = Path(translations)
    memories: dict[str, tuple[str, str, int]] = {}
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(f"{name} memory does not exist: {source}")
        if (name == "rules"
                and source.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}):
            from crms_model import _rule_database_payload
            payload = _rule_database_payload(source)
            source_bytes = source.stat().st_size
        elif (name == "knowledge"
              and source.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}):
            from crms_knowledge import _knowledge_database_payload
            payload = _knowledge_database_payload(source)
            source_bytes = source.stat().st_size
        else:
            data = source.read_bytes()
            if len(data) > _MAX_MEMBER_BYTES:
                raise ValueError(
                    f"{name} memory exceeds the model database size limit")
            payload = json.loads(data.decode("utf-8"))
            source_bytes = len(data)
        canonical = json.dumps(payload, ensure_ascii=False,
                               separators=(",", ":"))
        if len(canonical.encode("utf-8")) > _MAX_MEMBER_BYTES:
            raise ValueError(f"{name} memory exceeds the model database size limit")
        memories[name] = (canonical, _sha256(canonical.encode("utf-8")),
                          source_bytes)

    research_source = None
    research_cursor = None
    research_database = None
    research_count = 0
    if research_index is not None:
        from crms_research import CRMSResearchIndex
        source_path = Path(research_index)
        if not source_path.is_file():
            raise FileNotFoundError(f"research index does not exist: {source_path}")
        if source_path.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}:
            research_database = sqlite3.connect(
                f"file:{source_path.resolve()}?mode=ro", uri=True)
            tables = {row[0] for row in research_database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "source_documents" not in tables:
                research_database.close()
                raise ValueError("SQLite research index has no source_documents table")
            research_count = research_database.execute(
                "SELECT count(*) FROM source_documents").fetchone()[0]
            research_cursor = research_database.execute(
                "SELECT document_id,title,location,body,pages_json "
                "FROM source_documents ORDER BY document_id")
        else:
            research_source = CRMSResearchIndex.load(source_path)
            research_count = len(research_source.documents())

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            prefix=destination.name + ".", suffix=".tmp", dir=destination.parent,
            delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with sqlite3.connect(temporary_path) as db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""CREATE TABLE model_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID""")
            db.execute("""CREATE TABLE learned_memories (
                kind TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                source_bytes INTEGER NOT NULL CHECK(source_bytes >= 0)
            ) WITHOUT ROWID""")
            _create_rule_tables(db)
            _create_knowledge_tables(db)
            if research_count:
                db.execute("""CREATE TABLE research_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    location TEXT,
                    body TEXT NOT NULL,
                    pages_json TEXT NOT NULL,
                    sha256 TEXT NOT NULL
                ) WITHOUT ROWID""")
                def package_row(row):
                    document_id, title, location, body, pages_json = row
                    body_bytes = body.encode("utf-8")
                    if len(body_bytes) > _MAX_MEMBER_BYTES:
                        raise ValueError(
                            "research document exceeds the model database size limit: "
                            f"{document_id}")
                    try:
                        pages = json.loads(pages_json)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"research document has invalid page data: {document_id}") from error
                    if (not isinstance(pages, list)
                            or any(not isinstance(page, str) for page in pages)
                            or (pages and "\n\f\n".join(pages) != body)):
                        raise ValueError(
                            f"research document page data is inconsistent: {document_id}")
                    return (document_id, title, location, body, pages_json,
                            _sha256(body_bytes))

                if research_cursor is not None:
                    while batch := research_cursor.fetchmany(64):
                        db.executemany(
                            "INSERT INTO research_documents VALUES (?,?,?,?,?,?)",
                            (package_row(row) for row in batch))
                else:
                    assert research_source is not None
                    for document in research_source.documents():
                        row = package_row((
                            document.document_id, document.title,
                            document.location, document.text,
                            json.dumps(document.pages, ensure_ascii=False,
                                       separators=(",", ":"))))
                        db.execute(
                            "INSERT INTO research_documents VALUES (?,?,?,?,?,?)", row)
            metadata = {
                "format": FORMAT,
                "version": str(VERSION),
                "contains_source_documents": str(bool(research_count)).lower(),
                "contains_research_index": str(bool(research_count)).lower(),
                "provenance_policy": (
                    "Original input files are excluded. Extracted source text may be "
                    "embedded for portable search; learned memories retain evidence "
                    "identifiers and provenance."),
            }
            db.executemany("INSERT INTO model_metadata VALUES (?, ?)",
                           sorted(metadata.items()))
            db.executemany("INSERT INTO learned_memories VALUES (?, ?, ?, ?)", [
                (name, payload, digest, size)
                for name, (payload, digest, size) in sorted(memories.items())])
            _write_rule_tables(db, json.loads(memories["rules"][0]))
            _write_knowledge_tables(db, json.loads(memories["knowledge"][0]))
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute(f"PRAGMA user_version={VERSION}")
            db.commit()
        # Confirm the completed database is readable before publishing it.
        inspect_model_database(temporary_path)
        temporary_path.replace(destination)
    finally:
        if research_database is not None:
            research_database.close()
        temporary_path.unlink(missing_ok=True)
    return destination


def inspect_model_database(path: str | Path) -> dict[str, dict[str, str | int]]:
    """Validate model format, learned memories, and optional source corpus."""
    try:
        db = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("model database failed SQLite integrity check")
            schema_version = db.execute("PRAGMA user_version").fetchone()[0]
            if (db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                    or schema_version not in _LEGACY_VERSIONS | {VERSION}):
                raise ValueError("unsupported CRMS model database header")
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            base_tables = _REQUIRED_TABLES
            if schema_version >= _VERSION_RULE_SQL:
                base_tables = base_tables | _RULE_TABLES
            if schema_version >= _VERSION_KNOWLEDGE_SQL:
                base_tables = base_tables | _KNOWLEDGE_SQL_TABLES
            if schema_version >= VERSION:
                base_tables = base_tables | _KNOWLEDGE_RECORD_TABLES
            expected_table_sets = [base_tables, base_tables | _RESEARCH_TABLES]
            if tables not in expected_table_sets:
                raise ValueError("database is not a CRMS learned-model database")
            metadata = dict(db.execute("SELECT key, value FROM model_metadata"))
            has_research = "research_documents" in tables
            if (metadata.get("format") != FORMAT
                    or metadata.get("version") != str(schema_version)
                    or metadata.get("contains_source_documents") != str(has_research).lower()
                    or metadata.get("contains_research_index") != str(has_research).lower()):
                raise ValueError("unsupported or non-portable CRMS model database")
            memories = {}
            for row in db.execute(
                    "SELECT kind, payload_json, sha256, source_bytes FROM learned_memories"):
                if row["kind"] not in _MEMORY_NAMES:
                    raise ValueError("model database contains an unknown memory type")
                raw = row["payload_json"].encode("utf-8")
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError("model database memory is invalid JSON") from error
                # Hashes refer to canonical payload bytes inside the DB, so a
                # model file is verifiable independent of original JSON layout.
                if _sha256(raw) != row["sha256"]:
                    raise ValueError(f"model database integrity check failed: {row['kind']}")
                memories[row["kind"]] = {
                    "bytes": len(raw), "source_bytes": row["source_bytes"],
                    "top_level_type": type(parsed).__name__,
                }
            if not {"knowledge", "rules"} <= memories.keys():
                raise ValueError("model database must include knowledge and rule memories")
            if schema_version >= _VERSION_RULE_SQL:
                stored_rules = json.loads(db.execute(
                    "SELECT payload_json FROM learned_memories WHERE kind='rules'"
                ).fetchone()[0])
                normalized_rules = _read_rule_tables(db)
                if normalized_rules != stored_rules:
                    raise ValueError(
                        "normalized rule tables disagree with the compatibility payload")
                memories["rules"]["storage"] = "sqlite"
            if schema_version >= _VERSION_KNOWLEDGE_SQL:
                stored_knowledge = json.loads(db.execute(
                    "SELECT payload_json FROM learned_memories "
                    "WHERE kind='knowledge'").fetchone()[0])
                normalized_knowledge = _read_knowledge_tables(db)
                if (_knowledge_payload_signature(normalized_knowledge)
                        != _knowledge_payload_signature(stored_knowledge)):
                    raise ValueError(
                        "normalized knowledge tables disagree with the compatibility payload")
                memories["knowledge"]["storage"] = "sqlite"
            if has_research:
                for document_id, title, body, pages_json, digest in db.execute(
                        "SELECT document_id,title,body,pages_json,sha256 "
                        "FROM research_documents"):
                    if (not document_id or not title or not body.strip()
                            or _sha256(body.encode("utf-8")) != digest):
                        raise ValueError(
                            f"model database source integrity check failed: {document_id}")
                    try:
                        pages = json.loads(pages_json)
                    except json.JSONDecodeError as error:
                        raise ValueError(
                            f"model database source pages are invalid: {document_id}") from error
                    if (not isinstance(pages, list)
                            or any(not isinstance(page, str) for page in pages)
                            or (pages and "\n\f\n".join(pages) != body)):
                        raise ValueError(
                            f"model database source pages failed validation: {document_id}")
            return memories
        finally:
            db.close()
    except sqlite3.DatabaseError as error:
        raise ValueError("invalid CRMS model database") from error


def model_database_rule_settings(path: str | Path, *,
                                validate: bool = True) -> dict[str, object]:
    """Return the rule search and retrieval configuration stored with a model."""
    if validate:
        inspect_model_database(path)
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        row = db.execute(
            "SELECT payload_json FROM learned_memories WHERE kind='rules'").fetchone()
    if row is None:
        raise ValueError("model database has no rule memory")
    payload = json.loads(row[0])
    if not isinstance(payload, dict):
        raise ValueError("model rule memory is malformed")
    settings = {
        "rule_depth": payload.get("max_composition_depth", 2),
        "rule_max_add": payload.get("max_add", 10),
        "rule_max_scale": payload.get("max_scale", 5),
        "rule_max_modulus": payload.get("max_modulus", 6),
        "rule_max_rotation": payload.get("max_rotation", 4),
        "rule_max_repeat": payload.get("max_repeat", 4),
        "rule_max_position_stride": payload.get("max_position_stride", 6),
        "rule_search_expansions": payload.get("max_search_expansions", 250_000),
        "rule_enable_position_arithmetic": payload.get(
            "enable_position_arithmetic", False),
    }
    settings.update({
        "rule_vsa_alpha": payload.get("vsa_alpha", 0.5),
        "rule_vsa_min_similarity": payload.get("vsa_min_similarity", 0.30),
        "rule_vsa_min_margin": payload.get("vsa_min_margin", 0.10),
    })
    return settings


def model_database_has_research(path: str | Path, *,
                                validate: bool = True) -> bool:
    """Whether this portable model embeds an extracted source corpus."""
    if validate:
        inspect_model_database(path)
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        return db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='research_documents'").fetchone() is not None


def model_database_research_stats(path: str | Path, *,
                                  validate: bool = True
                                  ) -> dict[str, int] | None:
    """Measure embedded source volume without treating words as model tokens."""
    if validate:
        inspect_model_database(path)
    from crms_text import iter_word_matches

    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='research_documents'").fetchone()
        if exists is None:
            return None
        documents = 0
        bytes_total = 0
        word_units = 0
        cursor = db.execute("SELECT body FROM research_documents")
        while batch := cursor.fetchmany(32):
            for (body,) in batch:
                documents += 1
                bytes_total += len(body.encode("utf-8"))
                word_units += sum(1 for _ in iter_word_matches(body))
    return {"documents": documents, "utf8_bytes": bytes_total,
            "word_units": word_units}


def install_model_database(path: str | Path,
                           destination: str | Path, *,
                           validated: bool = False) -> dict[str, Path]:
    """Materialize sidecar memories, retaining normalized SQLite rules."""
    memories = (inspect_model_database(path) if not validated else None)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    installed = {}
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
        memory_kinds = ([row[0] for row in db.execute(
            "SELECT kind FROM learned_memories ORDER BY kind")]
                        if memories is None else sorted(memories))
        has_research = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='research_documents'").fetchone() is not None
        rule_tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        has_sqlite_rules = _RULE_TABLES <= rule_tables
        has_sqlite_knowledge = _KNOWLEDGE_SQL_TABLES <= rule_tables
    with tempfile.TemporaryDirectory(dir=root) as staging_name:
        staging = Path(staging_name)
        with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
            for kind in memory_kinds:
                if kind == "knowledge" and has_sqlite_knowledge:
                    payload = _read_knowledge_tables(db)
                    from crms_knowledge import _write_knowledge_database_payload
                    _write_knowledge_database_payload(
                        staging / "knowledge.sqlite", payload)
                    continue
                if kind == "rules" and has_sqlite_rules:
                    payload = _read_rule_tables(db)
                    from crms_model import _write_rule_database
                    _write_rule_database(staging / "rules.sqlite", payload)
                    continue
                payload = db.execute(
                    "SELECT payload_json FROM learned_memories WHERE kind=?",
                    (kind,)).fetchone()[0]
                (staging / f"{kind}.json").write_text(
                    json.dumps(json.loads(payload), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
        for kind in memory_kinds:
            suffix = (".sqlite" if (kind == "rules" and has_sqlite_rules)
                      or (kind == "knowledge" and has_sqlite_knowledge)
                      else ".json")
            target = root / f"{kind}{suffix}"
            (staging / f"{kind}{suffix}").replace(target)
            installed[kind] = target
    if has_research:
        from crms_research import CRMSSQLiteResearchIndex
        index_path = root / "research.sqlite"
        index_path.unlink(missing_ok=True)
        Path(str(index_path) + "-wal").unlink(missing_ok=True)
        Path(str(index_path) + "-shm").unlink(missing_ok=True)
        index = CRMSSQLiteResearchIndex(index_path)
        try:
            with sqlite3.connect(
                    f"file:{Path(path).resolve()}?mode=ro", uri=True) as db:
                cursor = db.execute(
                    "SELECT document_id,title,location,body,pages_json "
                    "FROM research_documents ORDER BY document_id")
                while batch := cursor.fetchmany(64):
                    with index._bulk_write_context():
                        for document_id, title, location, body, pages_json in batch:
                            index.add_document(
                                document_id, title, body, location,
                                pages=json.loads(pages_json))
        finally:
            index.close()
        installed["research_index"] = index_path
    return installed


def repack_model_database(path: str | Path, memory_dir: str | Path,
                          output: str | Path) -> Path:
    """Embed updated sidecar memories and research into a new portable model.

    The input model is never overwritten. Sidecar JSON memories and an
    available research index take precedence; missing memories or indexes are
    recovered from the original model. An existing sidecar digest marker must
    match the input model before any state is reused.
    """
    source = Path(path).expanduser().resolve()
    sidecar = Path(memory_dir).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if source == destination:
        raise ValueError("repack output must differ from the input model")
    if destination.exists():
        raise FileExistsError(f"repack output already exists: {destination}")
    memories = inspect_model_database(source)
    marker = sidecar / ".model.sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() != _sha256(
            source.read_bytes()):
        raise ValueError("memory sidecar was created from a different model database")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix="crms-repack-", dir=destination.parent) as temporary_name:
        recovered = Path(temporary_name) / "recovered"
        install_model_database(source, recovered, validated=True)
        chosen_memories: dict[str, Path] = {}
        for name in _MEMORY_NAMES:
            candidates = (
                [sidecar / "rules.sqlite", sidecar / "rules.json"]
                if name == "rules" else
                [sidecar / "knowledge.sqlite", sidecar / "knowledge.json"]
                if name == "knowledge" else [sidecar / f"{name}.json"])
            recovered_candidates = (
                [recovered / "rules.sqlite", recovered / "rules.json"]
                if name == "rules" else
                [recovered / "knowledge.sqlite", recovered / "knowledge.json"]
                if name == "knowledge" else [recovered / f"{name}.json"])
            sidecar_file = next((candidate for candidate in candidates
                                 if candidate.is_file()), None)
            recovered_file = next((candidate for candidate in recovered_candidates
                                   if candidate.is_file()), None)
            if sidecar_file is not None:
                chosen_memories[name] = sidecar_file
            elif recovered_file is not None:
                chosen_memories[name] = recovered_file
            elif name in {"knowledge", "rules"}:
                raise ValueError(f"model has no {name} memory to repack")

        research_index = sidecar / "research.sqlite"
        if not research_index.is_file():
            research_index = recovered / "research.sqlite"
        if not research_index.is_file():
            research_index = None

        return export_model_database(
            destination,
            knowledge=chosen_memories["knowledge"],
            rules=chosen_memories["rules"],
            math=chosen_memories.get("math"),
            translations=chosen_memories.get("translations"),
            research_index=research_index)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="create one SQLite learned model")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--knowledge", type=Path, required=True)
    export.add_argument("--rules", type=Path, required=True)
    export.add_argument("--math", type=Path)
    export.add_argument("--translations", type=Path)
    export.add_argument("--research-index", type=Path,
                        help="optionally embed extracted searchable source text")
    inspect = commands.add_parser("inspect", help="verify a SQLite model database")
    inspect.add_argument("database", type=Path)
    install = commands.add_parser("install", help="export memories for current CRMS CLI")
    install.add_argument("database", type=Path)
    install.add_argument("--destination", type=Path, required=True)
    repack = commands.add_parser(
        "repack", help="embed updated memories into a new portable model")
    repack.add_argument("database", type=Path,
                        help="portable model that the memory sidecar belongs to")
    repack.add_argument("--memory-dir", type=Path, required=True,
                        help="updated model sidecar directory")
    repack.add_argument("--output", type=Path, required=True,
                        help="new portable SQLite model to write")
    args = parser.parse_args()
    if args.command == "export":
        result = export_model_database(
            args.output, knowledge=args.knowledge, rules=args.rules,
            math=args.math, translations=args.translations,
            research_index=args.research_index)
        print(f"Created portable CRMS model database: {result}")
    elif args.command == "inspect":
        for name, details in sorted(inspect_model_database(args.database).items()):
            print(f"{name}: {details['bytes']} bytes ({details['top_level_type']})")
        corpus = model_database_research_stats(args.database, validate=False)
        if corpus is not None:
            print("research text: "
                  f"{corpus['documents']} documents, "
                  f"{corpus['utf8_bytes']} UTF-8 bytes, "
                  f"{corpus['word_units']} CRMS word units "
                  "(not model-token count)")
    elif args.command == "install":
        result = install_model_database(args.database, args.destination)
        print("Installed learned memories: " + ", ".join(
            f"{name}={path}" for name, path in sorted(result.items())))
    else:
        result = repack_model_database(
            args.database, args.memory_dir, args.output)
        print(f"Created repacked portable CRMS model database: {result}")


if __name__ == "__main__":
    main()
