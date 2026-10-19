"""Grounded fact storage and example-learned question frames for CRMS.

This module uses exact symbolic facts and question templates. It has no
pretrained language model, embedding, or built-in synonym inventory.
"""

from __future__ import annotations

import copy
from datetime import date
import hashlib
from itertools import combinations, islice
import io
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from crms_inference import (InferenceRule, InferenceResult,
                            _proof_support,
                            RuleAcceptanceResult, RuleDiscoveryResult,
                            RuleReview, RuleReviewResult, RuleValidation,
                            discover_rule_candidates, infer_relation,
                            reasoning_budget,
                            validate_rule_candidate)
from crms_rule_proof import verify_inference_proof
from crms_fact_store import SQLiteFactMap
from crms_research import (
    SearchHit, SummarySentence, _RESEARCH_STOPWORDS, _is_code_source, _sentence_context_kind,
    _sentence_spans,
)
from crms_text import (casefold_nfc, tokens as normalized_tokens,
                       word_matches)


_MAX_COORDINATED_WRITING_CLAIMS = 8
_STRUCTURED_PREDICATE_FIELDS = {
    # These are explicit normalized SimpleWiki field schemas, not an open
    # synonym list. They can supervise an alternate prose predicate only
    # when one exact sentence states the same endpoint pair.
    "capital": ("capital of", "object"),
}
_KNOWLEDGE_JSON_CHUNK = 64 * 1024
_FACT_DB_APPLICATION_ID = int.from_bytes(b"CRMF", "big")
_FACT_DB_VERSION = 1
_KNOWLEDGE_DB_APPLICATION_ID = int.from_bytes(b"CRMK", "big")
_KNOWLEDGE_DB_VERSION = 2
_KNOWLEDGE_DB_V1_TABLES = {
    "knowledge_metadata", "knowledge_payload", "inference_rules",
    "derived_cases", "positive_facts", "negative_facts",
}
_KNOWLEDGE_DB_TABLES = _KNOWLEDGE_DB_V1_TABLES | {"knowledge_records"}
_KNOWLEDGE_RECORD_SECTIONS = frozenset({
    "entity_aliases", "entity_alias_explicit_sources",
    "fact_pattern_alias_sources", "question_examples",
    "question_example_evidence",
    "subject_pattern_question_examples",
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


def _knowledge_record_bytes(record: Any) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _knowledge_record_anchor(section: str, record: Any) -> str:
    if isinstance(record, Mapping):
        for field in ("relation", "relations", "template", "qualifier_names",
                      "alias", "prefix", "start", "target"):
            if field in record:
                return json.dumps(record[field], ensure_ascii=False,
                                  sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(_knowledge_record_bytes(record)).hexdigest()


def _write_knowledge_database(path: Path, payload: dict[str, Any],
                              facts: Mapping[tuple[Any, ...], FactEvidence],
                              negative_facts: Mapping[tuple[Any, ...], FactEvidence],
                              *, existing_connection: sqlite3.Connection | None = None
                              ) -> sqlite3.Connection | None:
    """Persist canonical knowledge state as indexed, provenance-bearing rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = existing_connection or sqlite3.connect(
        path, isolation_level=None)
    owns_connection = existing_connection is None
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
        header_id = connection.execute("PRAGMA application_id").fetchone()[0]
        header_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if tables and not (
                header_id == _KNOWLEDGE_DB_APPLICATION_ID
                and ((tables == _KNOWLEDGE_DB_V1_TABLES and header_version == 1)
                     or (tables == _KNOWLEDGE_DB_TABLES
                         and header_version == _KNOWLEDGE_DB_VERSION))):
            raise ValueError("existing SQLite file is not a CRMS knowledge database")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("CREATE TABLE IF NOT EXISTS knowledge_metadata ("
                           "key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS knowledge_payload ("
                           "section TEXT PRIMARY KEY,payload_json TEXT NOT NULL) "
                           "WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS inference_rules ("
                           "rule_key TEXT PRIMARY KEY,payload_json TEXT NOT NULL) "
                           "WITHOUT ROWID")
        connection.execute("CREATE TABLE IF NOT EXISTS derived_cases ("
                           "case_key TEXT PRIMARY KEY,subject_key TEXT NOT NULL,"
                           "relation_key TEXT NOT NULL,object_key TEXT NOT NULL,"
                           "payload_json TEXT NOT NULL) WITHOUT ROWID")
        connection.execute("CREATE INDEX IF NOT EXISTS derived_cases_conclusion "
                           "ON derived_cases(relation_key,subject_key,object_key)")
        connection.execute("CREATE TABLE IF NOT EXISTS knowledge_records ("
                           "section TEXT NOT NULL,ordinal INTEGER NOT NULL,"
                           "anchor_key TEXT NOT NULL,record_key TEXT NOT NULL,"
                           "payload_json TEXT NOT NULL,PRIMARY KEY(section,ordinal)) "
                           "WITHOUT ROWID")
        connection.execute("CREATE INDEX IF NOT EXISTS knowledge_records_anchor "
                           "ON knowledge_records(section,anchor_key)")
        connection.execute("CREATE INDEX IF NOT EXISTS knowledge_records_digest "
                           "ON knowledge_records(section,record_key)")
        target_facts = SQLiteFactMap(connection, "positive_facts")
        target_negative = SQLiteFactMap(connection, "negative_facts")
        connection.execute(f"PRAGMA application_id={_KNOWLEDGE_DB_APPLICATION_ID}")
        connection.execute(f"PRAGMA user_version={_KNOWLEDGE_DB_VERSION}")
        connection.execute("DELETE FROM knowledge_metadata")
        connection.execute("DELETE FROM knowledge_payload")
        connection.execute("DELETE FROM knowledge_records")
        connection.execute("DELETE FROM inference_rules")
        connection.execute("DELETE FROM derived_cases")
        # SQLiteFactMap wrappers are newly constructed above. Detect the same
        # database by connection identity before replacing fact rows.
        same_fact_store = (existing_connection is not None
                           and isinstance(facts, SQLiteFactMap)
                           and facts.connection is connection)
        if not same_fact_store:
            target_facts.clear()
            target_negative.clear()
            for store, destination in ((facts, target_facts),
                                       (negative_facts, target_negative)):
                for key, fact in store.items():
                    destination[key] = fact
        connection.executemany("INSERT INTO knowledge_metadata VALUES (?,?)", [
            ("format", "crms-knowledge-database"),
            ("version", str(_KNOWLEDGE_DB_VERSION)),
        ])
        relational_sections = {"inference_rules", "derived_cases"}
        connection.executemany(
            "INSERT INTO knowledge_payload VALUES (?,?)",
            ((name, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
             for name, value in payload.items()
             if name not in relational_sections
             and name not in _KNOWLEDGE_RECORD_SECTIONS))
        for section in sorted(_KNOWLEDGE_RECORD_SECTIONS):
            records = payload.get(section, [])
            if not isinstance(records, list):
                raise ValueError(f"knowledge record section {section} is malformed")
            connection.executemany(
                "INSERT INTO knowledge_records VALUES (?,?,?,?,?)",
                ((section, ordinal,
                  _knowledge_record_anchor(section, record),
                  hashlib.sha256(_knowledge_record_bytes(record)).hexdigest(),
                  _knowledge_record_bytes(record).decode("utf-8"))
                 for ordinal, record in enumerate(records)))
        connection.executemany(
            "INSERT INTO inference_rules VALUES (?,?)",
            ((json.dumps(_tokens(item["rule_id"]), ensure_ascii=False,
                         separators=(",", ":")),
              json.dumps(item, ensure_ascii=False, separators=(",", ":")))
             for item in payload.get("inference_rules", [])))
        connection.executemany(
            "INSERT INTO derived_cases VALUES (?,?,?,?,?)",
            ((json.dumps(CRMSKnowledgeBase._fact_key(
                    item["conclusion"]["subject"],
                    item["conclusion"]["relation"],
                    item["conclusion"]["object"],
                    CRMSKnowledgeBase._normalize_qualifiers(
                        dict(item.get("qualifiers", [])))),
                    ensure_ascii=False, separators=(",", ":")),
              json.dumps(_tokens(item["conclusion"]["subject"]),
                         ensure_ascii=False, separators=(",", ":")),
              json.dumps(_tokens(item["conclusion"]["relation"]),
                         ensure_ascii=False, separators=(",", ":")),
              json.dumps(_tokens(item["conclusion"]["object"]),
                         ensure_ascii=False, separators=(",", ":")),
              json.dumps(item, ensure_ascii=False, separators=(",", ":")))
             for item in payload.get("derived_cases", [])))
        connection.commit()
        return None if owns_connection else connection
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        if owns_connection:
            connection.close()
        raise


def _read_knowledge_database(path: Path) -> tuple[sqlite3.Connection, dict[str, Any]]:
    """Open a validated writable knowledge database and load its typed payload."""
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite knowledge database failed its integrity check")
        database_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if (connection.execute("PRAGMA application_id").fetchone()[0]
                != _KNOWLEDGE_DB_APPLICATION_ID
                or database_version not in {1, _KNOWLEDGE_DB_VERSION}):
            raise ValueError("unsupported CRMS SQLite knowledge database header")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
        expected_tables = (_KNOWLEDGE_DB_V1_TABLES if database_version == 1
                           else _KNOWLEDGE_DB_TABLES)
        if tables != expected_tables:
            raise ValueError("SQLite file is not a CRMS knowledge database")
        metadata = dict(connection.execute(
            "SELECT key,value FROM knowledge_metadata"))
        if (metadata.get("format") != "crms-knowledge-database"
                or metadata.get("version") != str(database_version)):
            raise ValueError("SQLite knowledge database metadata is invalid")
        payload = {section: json.loads(value) for section, value in connection.execute(
            "SELECT section,payload_json FROM knowledge_payload")}
        if database_version >= 2:
            records: dict[str, list[tuple[int, Any]]] = {}
            for section, ordinal, anchor, digest, value in connection.execute(
                    "SELECT section,ordinal,anchor_key,record_key,payload_json "
                    "FROM knowledge_records ORDER BY section,ordinal"):
                if section not in _KNOWLEDGE_RECORD_SECTIONS:
                    raise ValueError("SQLite knowledge DB has an unknown record section")
                parsed = json.loads(value)
                if (hashlib.sha256(_knowledge_record_bytes(parsed)).hexdigest() != digest
                        or _knowledge_record_anchor(section, parsed) != anchor):
                    raise ValueError(
                        f"SQLite language-memory record failed integrity check: {section}")
                records.setdefault(section, []).append((ordinal, parsed))
            for section in _KNOWLEDGE_RECORD_SECTIONS:
                rows = records.get(section, [])
                if [ordinal for ordinal, _ in rows] != list(range(len(rows))):
                    raise ValueError(
                        f"SQLite language-memory record order is malformed: {section}")
                if section in payload:
                    raise ValueError(
                        f"SQLite language-memory section is stored twice: {section}")
                payload[section] = [record for _, record in rows]
        payload["inference_rules"] = [json.loads(value) for (value,) in connection.execute(
            "SELECT payload_json FROM inference_rules ORDER BY rule_key")]
        payload["derived_cases"] = [json.loads(value) for (value,) in connection.execute(
            "SELECT payload_json FROM derived_cases ORDER BY case_key")]
        for table in ("positive_facts", "negative_facts"):
            for key, fact in SQLiteFactMap(connection, table).items():
                expected_key = CRMSKnowledgeBase._fact_key(
                    fact.subject, fact.relation, fact.object,
                    CRMSKnowledgeBase._normalize_qualifiers(
                        dict(fact.qualifiers)))
                if key != expected_key or not fact.sources:
                    raise ValueError(
                        f"SQLite {table} row has invalid key or missing provenance")
        return connection, payload
    except Exception:
        connection.close()
        raise


def _knowledge_database_payload(path: Path) -> dict[str, Any]:
    """Return the JSON interchange view of a validated SQLite knowledge DB."""
    connection, payload = _read_knowledge_database(path)
    try:
        payload["facts"] = [asdict(fact) for fact in
                            SQLiteFactMap(connection, "positive_facts").values()]
        payload["negative_facts"] = [asdict(fact) for fact in
                                     SQLiteFactMap(connection, "negative_facts").values()]
        return payload
    finally:
        connection.close()


def _write_knowledge_database_payload(path: Path,
                                      payload: dict[str, Any]) -> None:
    """Install a complete JSON-compatible knowledge payload into SQLite."""
    knowledge = CRMSKnowledgeBase()
    stores = {}
    for name in ("facts", "negative_facts"):
        store: dict[tuple[Any, ...], FactEvidence] = {}
        for item in payload.get(name, []):
            if not isinstance(item, dict) or not item.get("sources"):
                raise ValueError(f"stored {name} record has no valid provenance")
            qualifiers = tuple(tuple(pair) for pair in item.get("qualifiers", []))
            fact = FactEvidence(item["subject"], item["relation"], item["object"],
                                tuple(item["sources"]), qualifiers)
            key = knowledge._fact_key(fact.subject, fact.relation, fact.object,
                                      knowledge._normalize_qualifiers(
                                          dict(fact.qualifiers)))
            store[key] = fact
        stores[name] = store
    sections = {name: value for name, value in payload.items()
                if name not in {"facts", "negative_facts"}}
    _write_knowledge_database(path, sections, stores["facts"],
                              stores["negative_facts"])
_IRREGULAR_VERB_PARADIGMS = {
    "be": ("be", "am", "is", "are", "was", "were", "been", "being"),
    "begin": ("begin", "begins", "began", "begun", "beginning"),
    "break": ("break", "breaks", "broke", "broken", "breaking"),
    "bring": ("bring", "brings", "brought", "bringing"),
    "build": ("build", "builds", "built", "building"),
    "buy": ("buy", "buys", "bought", "buying"),
    "choose": ("choose", "chooses", "chose", "chosen", "choosing"),
    "come": ("come", "comes", "came", "coming"),
    "do": ("do", "does", "did", "done", "doing"),
    "draw": ("draw", "draws", "drew", "drawn", "drawing"),
    "drink": ("drink", "drinks", "drank", "drunk", "drinking"),
    "drive": ("drive", "drives", "drove", "driven", "driving"),
    "eat": ("eat", "eats", "ate", "eaten", "eating"),
    "fall": ("fall", "falls", "fell", "fallen", "falling"),
    "feel": ("feel", "feels", "felt", "feeling"),
    "find": ("find", "finds", "found", "finding"),
    "fly": ("fly", "flies", "flew", "flown", "flying"),
    "get": ("get", "gets", "got", "gotten", "getting"),
    "give": ("give", "gives", "gave", "given", "giving"),
    "go": ("go", "goes", "went", "gone", "going"),
    "grow": ("grow", "grows", "grew", "grown", "growing"),
    "have": ("have", "has", "had", "having"),
    "hear": ("hear", "hears", "heard", "hearing"),
    "hold": ("hold", "holds", "held", "holding"),
    "keep": ("keep", "keeps", "kept", "keeping"),
    "know": ("know", "knows", "knew", "known", "knowing"),
    "lead": ("lead", "leads", "led", "leading"),
    "leave": ("leave", "leaves", "left", "leaving"),
    "lose": ("lose", "loses", "lost", "losing"),
    "make": ("make", "makes", "made", "making"),
    "meet": ("meet", "meets", "met", "meeting"),
    "pay": ("pay", "pays", "paid", "paying"),
    "put": ("put", "puts", "putting"),
    "read": ("read", "reads", "reading"),
    "ride": ("ride", "rides", "rode", "ridden", "riding"),
    "rise": ("rise", "rises", "rose", "risen", "rising"),
    "run": ("run", "runs", "ran", "running"),
    "say": ("say", "says", "said", "saying"),
    "see": ("see", "sees", "saw", "seen", "seeing"),
    "send": ("send", "sends", "sent", "sending"),
    "set": ("set", "sets", "setting"),
    "show": ("show", "shows", "showed", "shown", "showing"),
    "sit": ("sit", "sits", "sat", "sitting"),
    "speak": ("speak", "speaks", "spoke", "spoken", "speaking"),
    "stand": ("stand", "stands", "stood", "standing"),
    "take": ("take", "takes", "took", "taken", "taking"),
    "teach": ("teach", "teaches", "taught", "teaching"),
    "tell": ("tell", "tells", "told", "telling"),
    "think": ("think", "thinks", "thought", "thinking"),
    "throw": ("throw", "throws", "threw", "thrown", "throwing"),
    "understand": ("understand", "understands", "understood",
                   "understanding"),
    "wear": ("wear", "wears", "wore", "worn", "wearing"),
    "win": ("win", "wins", "won", "winning"),
    "write": ("write", "writes", "wrote", "written", "writing"),
}


class _JSONStreamReader:
    """Small buffered JSON reader that can stream large top-level arrays."""

    def __init__(self, stream: io.TextIOBase) -> None:
        self.stream = stream
        self.decoder = json.JSONDecoder()
        self.buffer = ""
        self.position = 0
        self.eof = False

    def _fill(self) -> bool:
        if self.eof:
            return False
        if self.position:
            self.buffer = self.buffer[self.position:]
            self.position = 0
        chunk = self.stream.read(_KNOWLEDGE_JSON_CHUNK)
        if not chunk:
            self.eof = True
            return False
        self.buffer += chunk
        return True

    def skip_space(self) -> None:
        while True:
            while (self.position < len(self.buffer)
                   and self.buffer[self.position].isspace()):
                self.position += 1
            if self.position < len(self.buffer) or not self._fill():
                return

    def expect(self, character: str) -> None:
        self.skip_space()
        if (self.position >= len(self.buffer)
                or self.buffer[self.position] != character):
            raise ValueError(f"invalid knowledge JSON: expected {character!r}")
        self.position += 1

    def value(self) -> Any:
        while True:
            self.skip_space()
            try:
                result, end = self.decoder.raw_decode(self.buffer, self.position)
                self.position = end
                return result
            except json.JSONDecodeError:
                if not self._fill():
                    raise ValueError("invalid or truncated knowledge JSON")

    def array(self):
        self.expect("[")
        self.skip_space()
        if self.position < len(self.buffer) and self.buffer[self.position] == "]":
            self.position += 1
            return
        while True:
            yield self.value()
            self.skip_space()
            if self.position >= len(self.buffer):
                if not self._fill():
                    raise ValueError("invalid or truncated knowledge JSON array")
                self.skip_space()
            if self.buffer[self.position] == ",":
                self.position += 1
                continue
            if self.buffer[self.position] == "]":
                self.position += 1
                return
            raise ValueError("invalid knowledge JSON array separator")


def _iter_knowledge_json(stream: io.TextIOBase):
    """Yield object members, streaming each facts array one record at a time."""
    reader = _JSONStreamReader(stream)
    reader.expect("{")
    reader.skip_space()
    seen: set[str] = set()
    if reader.position < len(reader.buffer) and reader.buffer[reader.position] == "}":
        reader.position += 1
        return
    while True:
        name = reader.value()
        if not isinstance(name, str) or name in seen:
            raise ValueError("knowledge JSON member names must be unique strings")
        seen.add(name)
        reader.expect(":")
        if name in {"facts", "negative_facts"}:
            value = reader.array()
        else:
            value = reader.value()
        yield name, value
        reader.skip_space()
        if reader.position >= len(reader.buffer):
            if not reader._fill():
                raise ValueError("invalid or truncated knowledge JSON object")
            reader.skip_space()
        if reader.buffer[reader.position] == ",":
            reader.position += 1
            continue
        if reader.buffer[reader.position] == "}":
            reader.position += 1
            reader.skip_space()
            if reader.position < len(reader.buffer) or reader._fill():
                reader.skip_space()
                if reader.position < len(reader.buffer):
                    raise ValueError("unexpected data after knowledge JSON object")
            return
        raise ValueError("invalid knowledge JSON object separator")


def _tokens(text: str) -> tuple[str, ...]:
    return normalized_tokens(text)


def _path_question_tokens(text: str) -> tuple[str, ...]:
    """Normalize English singular possessives for learned path frames."""
    return _tokens(re.sub(r"(?<=\w)[’']s\b", "", text,
                          flags=re.IGNORECASE))


def _indefinite_article_for(noun_phrase: str) -> str | None:
    """Choose a/an with a small, inspectable English onset rule."""
    match = re.search(r"[A-Za-z]+", noun_phrase.strip())
    if match is None:
        return None
    word = match.group().casefold()
    if word.startswith(("heir", "honest", "honor", "hour")):
        return "an"
    if word.startswith(("eul", "eup", "euro", "one", "once", "uni",
                        "use", "user", "usual", "utility", "utensil", "ufo")):
        return "a"
    return "an" if word[0] in "aeiou" else "a"


def _proof_leaf_sources(proof: Mapping[str, Any]) -> set[str]:
    if proof.get("kind") == "fact":
        fact = proof.get("fact", {})
        return set(fact.get("sources", []))
    sources = set().union(*(_proof_leaf_sources(item)
                            for item in proof.get("premises", [])))
    kind_fact = proof.get("middle_kind_fact")
    if isinstance(kind_fact, Mapping):
        sources.update(kind_fact.get("sources", []))
    for fact in proof.get("middle_kind_facts", []):
        if isinstance(fact, Mapping):
            sources.update(fact.get("sources", []))
    relation_type_fact = proof.get("relation_type_fact")
    if isinstance(relation_type_fact, Mapping):
        sources.update(relation_type_fact.get("sources", []))
    return sources


def _proof_rule_ids(proof: Mapping[str, Any]) -> set[str]:
    if proof.get("kind") == "fact":
        return set()
    if proof.get("kind") == "schema":
        schema = proof.get("schema", {})
        return ({str(schema.get("schema_id", ""))}
                | set().union(*(_proof_rule_ids(item)
                                for item in proof.get("premises", []))))
    rule = proof.get("rule", {})
    return ({str(rule["rule_id"])}
            | set().union(*(_proof_rule_ids(item)
                            for item in proof.get("premises", []))))


def _proof_key(proof: Mapping[str, Any]) -> str:
    return json.dumps(proof, sort_keys=True, ensure_ascii=False)


def _is_derived_proof(proof: Mapping[str, Any]) -> bool:
    return proof.get("kind") in {"rule", "schema"}


def _inference_state_fingerprint(facts: Iterable[Mapping[str, Any]],
                                negative_facts: Iterable[Mapping[str, Any]],
                                rules: Iterable[Mapping[str, Any]]) -> str:
    """Fingerprint the complete inference state for safe derived-case reuse."""
    snapshot = {
        "facts": sorted((dict(row) for row in facts),
                        key=lambda row: json.dumps(row, sort_keys=True,
                                                   ensure_ascii=False)),
        "negative_facts": sorted((dict(row) for row in negative_facts),
                                 key=lambda row: json.dumps(row, sort_keys=True,
                                                            ensure_ascii=False)),
        "rules": sorted((dict(row) for row in rules),
                        key=lambda row: json.dumps(row, sort_keys=True,
                                                   ensure_ascii=False)),
    }
    serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _predicate_spelling_class(base: str) -> tuple[str, str]:
    """Return a deliberately small orthographic class for verb endings."""
    if base.endswith(("s", "x", "ch", "sh")):
        return "sibilant", ""
    if len(base) >= 2 and base.endswith("z") and base[-2] in "aeiou":
        return "single-z-after-vowel", "z"
    if (len(base) >= 2 and base.endswith("y") and base[-2].isalpha()
            and base[-2] not in "aeiou"):
        return "consonant-y", "y"
    if base.endswith("e"):
        return "final-e", "e"
    if base.endswith("c"):
        return "final-c", "c"
    if base.endswith("o"):
        return "final-o", "o"
    if (3 <= len(base) <= 4 and len(re.findall(r"[aeiou]+", base)) == 1
            and base[-3] not in "aeiou" and base[-2] in "aeiou"
            and base[-1].isalpha() and base[-1] not in "aeiouwxy"):
        return "cvc-double", "final-consonant"
    return "other-ending", ""


def _analyze_predicate_spelling(base: str, surface: str
                                ) -> tuple[str, str, str] | None:
    """Recognize one exact, bounded spelling change between aligned words."""
    if surface == base:
        return None
    base_context, _base_removed = _predicate_spelling_class(base)
    context, removed, stem = "other-ending", "", base
    if base_context == "sibilant":
        if surface == base + "es":
            context, ending = "sibilant-es", "es"
        elif surface.startswith(base) and len(surface) > len(base):
            # Sibilant-final verbs still take ordinary endings such as -ed
            # and -ing without a spelling change.
            ending = surface[len(base):]
        else:
            return None
    elif base_context == "final-o":
        if surface == base + "es":
            context, ending = "final-o-es", "es"
        elif surface.startswith(base) and len(surface) > len(base):
            # Other regular endings can still append directly (echoed,
            # echoing); third-person -s requires separately learned -es.
            ending = surface[len(base):]
        else:
            return None
    elif base_context == "single-z-after-vowel":
        stem = base[:-1]
        doubled = stem + "zz"
        if surface.startswith(doubled) and len(surface) > len(doubled):
            context, removed = "single-z-double", "z"
            ending = surface[len(doubled):]
        else:
            return None
    elif base_context == "consonant-y":
        stem = base[:-1]
        if surface.startswith(stem + "i"):
            context, removed = "consonant-y", "y"
            ending = surface[len(stem):]
        elif surface.startswith(base) and len(surface) > len(base):
            ending = surface[len(base):]
        else:
            return None
    elif base_context == "final-e":
        stem = base[:-1]
        if base.endswith("ie") and surface == base[:-2] + "ying":
            context, removed = "final-ie-y", "ie"
            stem = base[:-2] + "y"
            ending = "ing"
        elif surface == base + "d":
            context, removed = "final-e", "e"
            ending = "ed"
        elif surface.startswith(stem) and not surface.startswith(base):
            context, removed = "final-e", "e"
            ending = surface[len(stem):]
        elif surface.startswith(base) and len(surface) > len(base):
            stem = base
            ending = surface[len(base):]
        else:
            return None
    elif base_context == "final-c":
        if (surface.startswith(base + "k")
                and surface[len(base + "k"):] in {"ed", "ing"}):
            context = "final-c-k"
            stem = base + "k"
            ending = surface[len(base + "k"):]
        elif surface.startswith(base) and len(surface) > len(base):
            # Keep ordinary endings as a distinct observation. Their existence
            # does not license inserting k before -ed or -ing.
            ending = surface[len(base):]
        else:
            return None
    elif base_context == "cvc-double":
        stem = base[:-1]
        doubled = stem + base[-1] * 2
        if surface.startswith(doubled):
            context, removed = "cvc-double", "final-consonant"
            ending = surface[len(doubled):]
        elif surface.startswith(base) and len(surface) > len(base):
            stem = base
            ending = surface[len(base):]
        else:
            return None
    elif surface.startswith(base) and len(surface) > len(base):
        ending = surface[len(base):]
    else:
        return None
    if not ending:
        return None
    expected = (stem + base[-1] * 2 + ending
                if context in {"cvc-double", "single-z-double"}
                else stem + ending)
    if surface != expected:
        return None
    return context, removed, ending


def _past_participle_for_surface(surface: tuple[str, ...]
                                 ) -> tuple[str, ...] | None:
    """Form a past participle from a bounded active past-tense form."""
    if len(surface) != 1:
        return None
    word = surface[0]
    if word.endswith("ed"):
        return surface
    for lemma, forms in _IRREGULAR_VERB_PARADIGMS.items():
        if lemma == "be":
            continue
        past = forms[2] if len(forms) > 2 else None
        if past is not None and past.endswith("ing"):
            past = None
        participle = (forms[3] if len(forms) > 3
                      and not forms[3].endswith("ing") else past)
        if word == past and participle:
            return (participle,)
    return None


def _is_past_participle(surface: tuple[str, ...]) -> bool:
    """Check that a passive pattern contains a listed participle form."""
    if len(surface) != 1:
        return False
    word = surface[0]
    if word.endswith("ed"):
        return True
    for lemma, forms in _IRREGULAR_VERB_PARADIGMS.items():
        if lemma == "be":
            continue
        past = forms[2] if len(forms) > 2 else None
        if past is not None and past.endswith("ing"):
            past = None
        participle = (forms[3] if len(forms) > 3
                      and not forms[3].endswith("ing") else past)
        if word == participle:
            return True
    return False


def _base_verb_for_surface(surface: tuple[str, ...]
                           ) -> tuple[str, ...] | None:
    """Recover a single-word base from a listed or bounded regular form."""
    if len(surface) != 1:
        return None
    word = surface[0]
    lemma = next((candidate for candidate, forms in
                  _IRREGULAR_VERB_PARADIGMS.items()
                  if word in forms and candidate != word and candidate != "be"
                  and not word.endswith("ing")), None)
    if lemma is not None:
        return (lemma,)
    possible_bases = {word[:-1], word[:-2],
                      word[:-3] + "y" if word.endswith("ied") else word[:-3]}
    return next(((base,) for base in sorted(possible_bases)
                 if base and _analyze_predicate_spelling(base, word) is not None),
                None)


def _past_tense_for_participle(surface: tuple[str, ...]
                               ) -> tuple[str, ...] | None:
    """Map a bounded participle to its active simple-past form."""
    if len(surface) != 1:
        return None
    word = surface[0]
    if word.endswith("ed"):
        return surface
    for lemma, forms in _IRREGULAR_VERB_PARADIGMS.items():
        if lemma == "be" or len(forms) < 3:
            continue
        past = forms[2]
        if past.endswith("ing"):
            continue
        participle = (forms[3] if len(forms) > 3
                      and not forms[3].endswith("ing") else past)
        if word == participle:
            return (past,)
    return None


_COUNTERFACTUAL_SLOTS = {
    "\x00start": "start",
    "\x00target": "target",
    "\x00source": "source",
}


def _match_counterfactual_template(
        template: tuple[str, ...], words: tuple[str, ...],
        limit: int = 3) -> list[tuple[tuple[str, ...], ...]]:
    """Match a template with three named, non-empty variable spans.

    Stop after three parses: callers only need to know whether there is zero,
    one, or ambiguous segmentation.
    """
    @lru_cache(maxsize=None)
    def visit(template_index: int, word_index: int
              ) -> tuple[tuple[tuple[str, ...], ...], ...]:
        if template_index == len(template):
            return ((),) if word_index == len(words) else ()
        token = template[template_index]
        if token in _COUNTERFACTUAL_SLOTS:
            matches = []
            for end in range(word_index + 1, len(words) + 1):
                for suffix in visit(template_index + 1, end):
                    matches.append((words[word_index:end],) + suffix)
                    if len(matches) >= limit:
                        return tuple(matches)
            return tuple(matches)
        if word_index >= len(words) or words[word_index] != token:
            return ()
        return visit(template_index + 1, word_index + 1)

    return list(visit(0, 0))


def _display(text: str, label: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return " ".join(text.strip().split())


@dataclass(frozen=True)
class FactEvidence:
    subject: str
    relation: str
    object: str
    sources: tuple[str, ...]
    qualifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FactCandidate:
    subject: str
    relation: str
    object: str
    source: str
    template: str
    sentence: str
    polarity: bool = True
    language_evidence: tuple[dict[str, Any], ...] = ()
    qualifiers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class AbductionHypothesis:
    """A citation-backed candidate set that proves a goal in a temporary view."""

    candidates: tuple[FactCandidate, ...]
    result: InferenceResult
    minimal: bool


@dataclass(frozen=True)
class AbductionResult:
    status: str
    hypotheses: tuple[AbductionHypothesis, ...] = ()
    complete: bool = True
    subsets_checked: int = 0
    expansions: int = 0
    request: str | None = None


@dataclass
class ResearchResult:
    status: str
    response: QuestionResult | None = None
    passages: list[dict[str, Any]] | None = None
    candidates: list[FactCandidate] | None = None
    request: str | None = None
    derived_context: list[dict[str, Any]] | None = None
    query_expansions: list[dict[str, Any]] | None = None
    source_sentences: list[dict[str, Any]] | None = None
    realized_answer: dict[str, Any] | None = None
    query: str | None = None


@dataclass
class WritingResult:
    status: str
    subject: str
    statements: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    omitted: list[dict[str, Any]]
    text: str


@dataclass
class QuestionResult:
    status: str
    answer: str | None = None
    candidates: list[str] | None = None
    evidence: list[dict[str, Any]] | None = None
    matched_templates: list[str] | None = None
    request: str | None = None
    proofs: list[list[dict[str, Any]]] | None = None
    truth: bool | None = None
    inference_proofs: list[dict[str, Any]] | None = None
    language_evidence: list[dict[str, Any]] | None = None
    complete: bool | None = None
    reason_code: str | None = None
    expansions: int | None = None
    missing_premises: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class CounterfactualResult:
    """Read-only result of excluding one fact from a path query."""

    status: str
    supported: bool | None
    baseline: QuestionResult
    counterfactual: QuestionResult | None
    excluded_fact: dict[str, Any] | None
    excluded_source: str | None = None


class CRMSKnowledgeBase:
    """A small, auditable triple store with grounded question-frame learning.

    A question frame is licensed after two distinct bound entities occur in
    questions with the same literal prefix and suffix for the same relation
    and answer direction. Only that contiguous entity span varies. This learns
    an explicit frame such as ``Who designed {object}?``; it does not infer
    synonyms or meanings for unseen words.
    """

    FORMAT_VERSION = 1

    def __init__(self, *, max_derived_cases: int = 1_000) -> None:
        if (not isinstance(max_derived_cases, int)
                or isinstance(max_derived_cases, bool)
                or max_derived_cases < 0):
            raise ValueError("max_derived_cases must be a non-negative integer")
        self.max_derived_cases = max_derived_cases
        self._knowledge_db_path: Path | None = None
        self._next_derived_case_order = 0
        self._facts: dict[tuple[Any, ...], FactEvidence] = {}
        self._negative_facts: dict[tuple[Any, ...], FactEvidence] = {}
        self._facts_by_relation_subject: dict[
            tuple[tuple[str, ...], tuple[str, ...]], set[tuple[Any, ...]]
        ] = {}
        self._facts_by_relation_object: dict[
            tuple[tuple[str, ...], tuple[str, ...]], set[tuple[Any, ...]]
        ] = {}
        self._facts_by_object: dict[
            tuple[str, ...], set[tuple[Any, ...]]
        ] = {}
        self._inference_rules: dict[tuple[str, ...], InferenceRule] = {}
        self._inference_rule_validation: dict[tuple[str, ...], dict[str, Any]] = {}
        # Derived cases are a proof-backed cache, never fact-store entries.
        self._derived_cases: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._entity_aliases: dict[tuple[str, ...], tuple[str, set[str]]] = {}
        self._entity_alias_explicit_sources: dict[tuple[str, ...], set[str]] = {}
        self._fact_pattern_alias_sources: set[
            tuple[tuple[str, ...], str, tuple[str, ...],
                  tuple[str, ...], tuple[str, ...], str, bool]
        ] = set()
        self._question_examples: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], set[str]],
        ] = {}
        self._question_example_evidence: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], list[dict[str, Any]]],
        ] = {}
        # A reviewed question slot may correspond to a subspan of a fact
        # endpoint, e.g. place in "What research happened at {place}?" maps to
        # the subject pattern "Researchers at {place}". Keep this separate
        # from ordinary endpoint-bound frames.
        self._subject_pattern_question_examples: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...], str,
                  tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], set[str]],
        ] = {}
        # Mechanically validated analogical frames remain separate from
        # teacher-provided examples and are activated only while their cited
        # source, predicate, training, and holdout evidence is still present.
        self._induced_question_frames: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]], dict[str, Any]
        ] = {}
        self._induced_qualified_question_frames: dict[
            tuple[tuple[str, ...], str, tuple[str, ...], bool,
                  tuple[str, ...], tuple[str, ...], tuple[str, ...]],
            dict[str, Any]
        ] = {}
        self._induced_multi_qualified_question_frames: dict[
            tuple[tuple[str, ...], str, tuple[tuple[str, ...], ...],
                  tuple[str, ...]], dict[str, Any]
        ] = {}
        self._qualified_question_examples: dict[
            tuple[tuple[str, ...], str, tuple[str, ...], bool,
                  tuple[str, ...], tuple[str, ...], tuple[str, ...]],
            dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]],
        ] = {}
        # Multi-context frames are kept separate so older serialized single-slot
        # frames retain their original format and matching behavior.
        self._multi_qualified_question_examples: dict[
            tuple[tuple[str, ...], str, tuple[tuple[str, ...], ...],
                  tuple[str, ...]],
            dict[tuple[tuple[str, ...], tuple[tuple[str, ...], ...]], set[str]],
        ] = {}
        self._polar_question_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            dict[tuple[tuple[str, ...], tuple[str, ...]], bool],
        ] = {}
        self._qualified_polar_question_examples: dict[
            tuple[tuple[str, ...], tuple[tuple[str, ...], ...], tuple[str, ...]],
            dict[tuple[tuple[str, ...], tuple[str, ...],
                      tuple[tuple[str, ...], ...]], bool],
        ] = {}
        self._path_question_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
            set[tuple[str, ...]],
        ] = {}
        self._counterfactual_source_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...],
                  tuple[tuple[str, ...], ...],
                  tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
                  tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], str],
        ] = {}
        self._counterfactual_path_examples: dict[
            tuple[tuple[str, ...], tuple[tuple[str, ...], ...],
                  tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]],
            dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
                 tuple[str, str, str]],
        ] = {}
        self._about_question_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], str],
        ] = {}

        self._fact_pattern_examples: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]],
        ] = {}
        self._fact_pattern_surfaces: dict[
            tuple[tuple[str, ...], tuple[str, ...]], set[str]
        ] = {}
        self._fact_pattern_predicates: dict[
            tuple[tuple[str, ...], tuple[str, ...]], set[tuple[str, ...]]
        ] = {}
        self._fact_pattern_predicate_sources: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            dict[tuple[str, ...], dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]]]
        ] = {}
        self._fact_pattern_surface_sources: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            dict[str, dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]]]
        ] = {}
        self._fact_pattern_polarities: dict[
            tuple[tuple[str, ...], tuple[str, ...]], bool
        ] = {}
        self._context_fact_patterns: dict[
            tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool],
            dict[tuple[tuple[str, ...], tuple[str, ...],
                       tuple[tuple[str, ...], ...], tuple[str, ...]], set[str]],
        ] = {}

    def _enforce_derived_case_limit(self) -> None:
        """Evict least-reused derived proofs, breaking ties oldest first."""
        while len(self._derived_cases) > self.max_derived_cases:
            victim = min(
                self._derived_cases,
                key=lambda key: (
                    self._derived_cases[key].get("reuse_count", 0),
                    self._derived_cases[key].get("practice_order", 0),
                    key,
                ),
            )
            del self._derived_cases[victim]

    def close(self) -> None:
        """Close any optional disk-backed fact stores opened by this instance."""
        connections = {
            id(store.connection): store.connection
            for store in (self._facts, self._negative_facts)
            if isinstance(store, SQLiteFactMap)
        }
        for connection in connections.values():
            connection.close()

    def __deepcopy__(self, memo):
        """Clone knowledge into an isolated in-memory working snapshot."""
        clone = type(self).__new__(type(self))
        memo[id(self)] = clone
        for name, value in self.__dict__.items():
            setattr(clone, name, copy.deepcopy(value, memo))
        clone._rebuild_fact_indexes()
        return clone

    @staticmethod
    def _normalize_qualifiers(
            qualifiers: Mapping[str, str] | None
            ) -> tuple[tuple[str, str], ...]:
        if qualifiers is None:
            return ()
        if not isinstance(qualifiers, Mapping):
            raise TypeError("qualifiers must be a mapping of names to values")
        normalized = []
        for name, value in qualifiers.items():
            name = _display(name, "qualifier name")
            value = _display(value, f"qualifier {name}")
            normalized.append((name, value))
        if len({_tokens(name) for name, _ in normalized}) != len(normalized):
            raise ValueError("qualifier names must be unique ignoring case")
        return tuple(sorted(normalized, key=lambda pair: _tokens(pair[0])))

    @staticmethod
    def _fact_key(subject: str, relation: str, obj: str,
                  qualifiers: tuple[tuple[str, str], ...] = ()) -> tuple[Any, ...]:
        base = tuple(_tokens(value) for value in (subject, relation, obj))
        if not qualifiers:
            return base
        return base + (tuple((_tokens(name), _tokens(value))
                             for name, value in qualifiers),)

    def _index_fact(self, key: tuple[Any, ...], fact: FactEvidence) -> None:
        if isinstance(self._facts, SQLiteFactMap):
            return
        relation = _tokens(fact.relation)
        subject = _tokens(fact.subject)
        obj = _tokens(fact.object)
        self._facts_by_relation_subject.setdefault((relation, subject), set()).add(key)
        self._facts_by_relation_object.setdefault((relation, obj), set()).add(key)
        self._facts_by_object.setdefault(obj, set()).add(key)

    @staticmethod
    def _discard_index_key(
            index: dict[tuple[tuple[str, ...], tuple[str, ...]], set[tuple[Any, ...]]],
            index_key: tuple[tuple[str, ...], tuple[str, ...]],
            fact_key: tuple[Any, ...]) -> None:
        keys = index.get(index_key)
        if keys is None:
            return
        keys.discard(fact_key)
        if not keys:
            del index[index_key]

    def _rebuild_fact_indexes(self) -> None:
        # Replace the maps so shallow temporary knowledge views do not mutate
        # the source instance's shared index dictionaries during a rebuild.
        self._facts_by_relation_subject = {}
        self._facts_by_relation_object = {}
        self._facts_by_object = {}
        if isinstance(self._facts, SQLiteFactMap):
            return
        for key, fact in self._facts.items():
            self._index_fact(key, fact)

    def _proof_fact_is_present(self, candidate: Mapping[str, Any]) -> bool:
        """Check exact proof evidence through the keyed fact store."""
        if isinstance(self._facts, SQLiteFactMap):
            return self._facts.contains_evidence(candidate)
        candidate_qualifiers = self._normalize_qualifiers(
            dict(candidate.get("qualifiers", ())))
        key = self._fact_key(
            *(str(candidate.get(field, ""))
              for field in ("subject", "relation", "object")),
            candidate_qualifiers)
        if not all(key):
            return False
        stored = self._facts.get(key)
        if stored is None:
            return False
        return (
            tuple(sorted(stored.sources)) == tuple(sorted(
                str(source) for source in candidate.get("sources", ())))
            and self._qualifiers_equal(stored.qualifiers, candidate_qualifiers)
        )

    def _proof_fact_support_is_present(
            self, candidate: Mapping[str, Any]) -> bool:
        """Check that a saved proof's cited sources remain among fact support."""
        candidate_qualifiers = self._normalize_qualifiers(
            dict(candidate.get("qualifiers", ())))
        candidate_sources = {str(source) for source in candidate.get("sources", ())}
        if not candidate_sources:
            return False
        for fact in self._matching_fact_rows(
                self._facts, *(str(candidate.get(field, ""))
                               for field in ("subject", "relation", "object"))):
            if (self._qualifiers_equal(fact.qualifiers, candidate_qualifiers)
                    and candidate_sources <= set(fact.sources)):
                return True
        return False

    def _matching_fact_rows(
            self, store, subject: str, relation: str, obj: str
            ) -> list[FactEvidence]:
        """Fetch exact-triple evidence without decoding an entire SQL store."""
        subject_key, relation_key, object_key = (
            _tokens(subject), _tokens(relation), _tokens(obj))
        if isinstance(store, SQLiteFactMap):
            return list(store.lookup_triple(subject_key, relation_key, object_key))
        if store is self._facts:
            candidate_keys = self._facts_by_relation_subject.get(
                (relation_key, subject_key), ())
            return [store[key] for key in sorted(candidate_keys)
                    if len(key) >= 3 and key[2] == object_key]
        return [fact for fact in store.values()
                if (_tokens(fact.subject), _tokens(fact.relation),
                    _tokens(fact.object))
                == (subject_key, relation_key, object_key)]

    @staticmethod
    def _has_qualifiers(fact: FactEvidence,
                        requested: tuple[tuple[str, str], ...]) -> bool:
        available = {(_tokens(name), _tokens(value))
                     for name, value in fact.qualifiers}
        return all((_tokens(name), _tokens(value)) in available
                   for name, value in requested)

    @staticmethod
    def _qualifiers_equal(
            actual: tuple[tuple[str, str], ...],
            requested: tuple[tuple[str, str], ...]) -> bool:
        """Compare exact qualifier sets using the store's case-insensitive semantics."""
        def normalize(pairs: tuple[tuple[str, str], ...]
                      ) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
            return tuple(sorted((_tokens(name), _tokens(value))
                                for name, value in pairs))
        return normalize(actual) == normalize(requested)

    @staticmethod
    def _scope_is_within(
            fact_scope: tuple[tuple[str, str], ...],
            requested_scope: tuple[tuple[str, str], ...]) -> bool:
        """A fact scope applies when the query contains every required qualifier."""
        required = {(_tokens(name), _tokens(value))
                    for name, value in fact_scope}
        available = {(_tokens(name), _tokens(value))
                     for name, value in requested_scope}
        return required <= available

    def add_fact(self, subject: str, relation: str, obj: str,
                 source: str, *,
                 qualifiers: Mapping[str, str] | None = None) -> FactEvidence:
        subject = _display(subject, "subject")
        relation = _display(relation, "relation")
        obj = _display(obj, "object")
        subject = self._canonicalize_entity(subject)
        obj = self._canonicalize_entity(obj)
        source = _display(source, "source")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        key = self._fact_key(subject, relation, obj, normalized_qualifiers)
        old = self._facts.get(key)
        if old is None:
            fact = FactEvidence(subject, relation, obj, (source,), normalized_qualifiers)
            self._index_fact(key, fact)
        else:
            fact = FactEvidence(old.subject, old.relation, old.object,
                                tuple(sorted(set(old.sources) | {source})),
                                old.qualifiers)
        self._facts[key] = fact
        return fact

    def add_negative_fact(self, subject: str, relation: str, obj: str,
                          source: str, *,
                          qualifiers: Mapping[str, str] | None = None) -> FactEvidence:
        """Record explicit evidence that a relation does not hold."""
        subject = _display(subject, "subject")
        relation = _display(relation, "relation")
        obj = _display(obj, "object")
        subject = self._canonicalize_entity(subject)
        obj = self._canonicalize_entity(obj)
        source = _display(source, "source")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        key = self._fact_key(subject, relation, obj, normalized_qualifiers)
        old = self._negative_facts.get(key)
        fact = (FactEvidence(subject, relation, obj, (source,), normalized_qualifiers) if old is None
                else FactEvidence(old.subject, old.relation, old.object,
                                  tuple(sorted(set(old.sources) | {source})),
                                  old.qualifiers))
        self._negative_facts[key] = fact
        self._flag_validated_rules_against_counterexample(fact)
        return fact

    def _flag_validated_rules_against_counterexample(
            self, negative: FactEvidence) -> None:
        """Suspend a validated learned rule when it proves an explicit negative."""
        target_key = self._fact_key(
            negative.subject, negative.relation, negative.object,
            negative.qualifiers)
        for rule in self._inference_rules_for_use():
            rule_key = _tokens(rule.rule_id)
            validation = self._inference_rule_validation.get(rule_key)
            if (validation is None
                    or validation.get("status", "validated") != "validated"
                    or _tokens(rule.conclusion_relation)
                       != _tokens(negative.relation)):
                continue
            if isinstance(self._facts, SQLiteFactMap):
                fact_rows, _negative_rows, _rule_rows = (
                    self._sqlite_inference_snapshot(
                        negative.relation, negative.qualifiers, [rule]))
            else:
                fact_rows = [asdict(fact) for fact in self.facts()]
            # A directly taught positive conclusion does not establish that
            # this learned rule is the source of the conflict.
            premise_rows = [row for row in fact_rows if self._fact_key(
                str(row["subject"]), str(row["relation"]),
                str(row["object"]), self._normalize_qualifiers(
                    dict(row.get("qualifiers", ())))) != target_key]
            predicted = infer_relation(
                premise_rows, [rule], subject=negative.subject,
                relation=negative.relation, obj=negative.object,
                qualifiers=dict(negative.qualifiers), max_expansions=10_000,
                max_depth=40)
            supporting_proofs = [proof for proof in predicted.proofs
                                 if rule.rule_id in _proof_rule_ids(proof)]
            if (predicted.status != "answered" or not predicted.complete
                    or not supporting_proofs):
                continue
            record = copy.deepcopy(validation)
            counterexample = {
                "subject": negative.subject,
                "relation": negative.relation,
                "object": negative.object,
                "qualifiers": list(negative.qualifiers),
                "negative_sources": list(negative.sources),
                "supporting_proofs": supporting_proofs,
            }
            counterexamples = list(record.get("counterexamples", []))
            signature = json.dumps(counterexample, sort_keys=True,
                                   ensure_ascii=False)
            if signature not in {
                    json.dumps(item, sort_keys=True, ensure_ascii=False)
                    for item in counterexamples}:
                counterexamples.append(counterexample)
            record["status"] = "needs_review"
            record["counterexamples"] = counterexamples
            self._inference_rule_validation[rule_key] = record

    def _inference_rules_for_use(self) -> list[InferenceRule]:
        """Return rules not suspended by counterexamples pending review."""
        return [rule for key, rule in self._inference_rules.items()
                if self._inference_rule_validation.get(key, {}).get(
                    "status", "validated") != "needs_review"]

    def flag_inference_rule_from_feedback(
            self, rule_id: str, feedback: Mapping[str, Any]) -> bool:
        """Suspend a validated learned rule after explicit answer rejection.

        User feedback is a review signal, not a proof that the rule is false.
        Teacher-supplied rules and rules already awaiting review are left alone.
        A fresh held-out validation and acceptance replaces this validation
        record and can restore the learned rule.
        """
        key = _tokens(_display(rule_id, "rule id"))
        if key not in self._inference_rules:
            return False
        current = self._inference_rule_validation.get(key)
        if not isinstance(current, dict) or current.get("status") != "validated":
            return False
        answer_id = feedback.get("answer_id")
        question = feedback.get("question")
        answer = feedback.get("answer")
        if not all(isinstance(value, str) and value.strip()
                   for value in (answer_id, question, answer)):
            raise ValueError("feedback must identify its answer and question")
        reports = list(current.get("feedback_reports", []))
        if any(isinstance(item, Mapping)
               and item.get("answer_id") == answer_id for item in reports):
            return False
        reports.append({"answer_id": answer_id.strip(),
                        "question": question.strip(),
                        "answer": answer.strip()})
        updated = copy.deepcopy(current)
        updated["status"] = "needs_review"
        updated["suspension_reason"] = "user_feedback"
        updated["feedback_reports"] = reports
        self._inference_rule_validation[key] = updated
        return True

    def list_inference_rules(self) -> list[dict[str, Any]]:
        """List rules with their validation status and counterexample records."""
        rows = []
        for key, rule in sorted(self._inference_rules.items()):
            validation = self._inference_rule_validation.get(key)
            rows.append({
                "rule": asdict(rule),
                "status": (validation.get("status", "validated")
                           if validation is not None else "teacher_supplied"),
                "validation": copy.deepcopy(validation),
            })
        return rows

    def remove_fact(self, subject: str, relation: str, obj: str, source: str, *,
                    qualifiers: Mapping[str, str] | None = None) -> bool:
        """Retract one source's support for a positive fact.

        Facts supported by other sources remain present. Derived artifacts are
        not edited here: their saved proofs are revalidated against the changed
        evidence snapshot when retrieved.
        """
        return self._remove_fact_evidence(
            self._facts, subject, relation, obj, source, qualifiers=qualifiers)

    def remove_negative_fact(
            self, subject: str, relation: str, obj: str, source: str, *,
            qualifiers: Mapping[str, str] | None = None) -> bool:
        """Retract one source's support for an explicitly negative fact."""
        return self._remove_fact_evidence(
            self._negative_facts, subject, relation, obj, source,
            qualifiers=qualifiers)

    def _remove_fact_evidence(
            self, store: dict[tuple[Any, ...], FactEvidence],
            subject: str, relation: str, obj: str, source: str, *,
            qualifiers: Mapping[str, str] | None = None) -> bool:
        subject = self._canonicalize_entity(_display(subject, "subject"))
        relation = _display(relation, "relation")
        obj = self._canonicalize_entity(_display(obj, "object"))
        source = _display(source, "source")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        key = self._fact_key(subject, relation, obj, normalized_qualifiers)
        old = store.get(key)
        if old is None or source not in old.sources:
            return False
        if store is self._facts:
            self._retract_question_example_evidence(key, source)
        if not normalized_qualifiers:
            self._retract_fact_pattern_support(
                _tokens(subject), _tokens(relation), _tokens(obj), source,
                positive=(store is self._facts))
        self._retract_context_fact_pattern_support(
            _tokens(subject), _tokens(relation), _tokens(obj),
            normalized_qualifiers, source, positive=(store is self._facts))
        remaining = tuple(item for item in old.sources if item != source)
        if remaining:
            store[key] = FactEvidence(
                old.subject, old.relation, old.object, remaining, old.qualifiers)
        else:
            del store[key]
            if store is self._facts and not isinstance(self._facts, SQLiteFactMap):
                self._discard_index_key(
                    self._facts_by_relation_subject,
                    (_tokens(old.relation), _tokens(old.subject)), key)
                self._discard_index_key(
                    self._facts_by_relation_object,
                    (_tokens(old.relation), _tokens(old.object)), key)
                self._discard_index_key(
                    self._facts_by_object, _tokens(old.object), key)
        return True

    def _retract_question_example_evidence(
            self, fact_key: tuple[Any, ...], source: str) -> None:
        """Remove only frame examples whose exact fact/proof support was retracted."""
        for frame_key, by_entity in list(self._question_example_evidence.items()):
            for entity_key, records in list(by_entity.items()):
                retained = []
                for original in records:
                    record = copy.deepcopy(original)
                    direct_facts = []
                    for fact in record.get("direct_facts", ()):
                        fact_record_key = self._fact_key(
                            fact["subject"], fact["relation"], fact["object"],
                            self._normalize_qualifiers(
                                dict(fact.get("qualifiers", ()))))
                        if (fact_record_key != fact_key
                                or source not in fact.get("sources", ())):
                            direct_facts.append(fact)
                            continue
                        remaining = [item for item in fact.get("sources", ())
                                     if item != source]
                        if remaining:
                            fact["sources"] = remaining
                            direct_facts.append(fact)
                    record["direct_facts"] = direct_facts
                    proofs = []
                    for proof in record.get("proofs", ()):
                        updated = self._without_retracted_proof_fact(
                            proof, fact_key, source)
                        if updated is not None:
                            proofs.append(updated)
                    record["proofs"] = proofs
                    if direct_facts or proofs:
                        retained.append(record)
                if retained:
                    by_entity[entity_key] = retained
                else:
                    del by_entity[entity_key]
                    # Old persisted frames have no evidence record; do not
                    # silently reinterpret their legacy examples as retracted.
                    if entity_key in self._question_examples.get(frame_key, {}) \
                            and frame_key in self._question_example_evidence:
                        self._question_examples[frame_key].pop(entity_key, None)
            if not by_entity:
                del self._question_example_evidence[frame_key]

    @classmethod
    def _without_retracted_proof_fact(
            cls, proof: Any, fact_key: tuple[Any, ...], source: str
            ) -> dict[str, Any] | None:
        """Return a proof with one remaining source removed, or None if broken."""
        if not isinstance(proof, Mapping):
            return None
        updated = copy.deepcopy(dict(proof))
        if updated.get("kind") == "fact":
            fact = updated.get("fact")
            key = (cls._fact_key(
                fact["subject"], fact["relation"], fact["object"],
                cls._normalize_qualifiers(dict(fact.get("qualifiers", ()))))
                   if isinstance(fact, Mapping) else None)
            if isinstance(fact, Mapping) and key == fact_key:
                remaining = [item for item in fact.get("sources", ())
                             if item != source]
                if not remaining:
                    return None
                updated_fact = dict(fact)
                updated_fact["sources"] = remaining
                updated["fact"] = updated_fact
            return updated
        premises = updated.get("premises")
        if isinstance(premises, list):
            revised = [cls._without_retracted_proof_fact(
                premise, fact_key, source) for premise in premises]
            if any(item is None for item in revised):
                return None
            updated["premises"] = revised
        for field in ("middle_kind_fact", "relation_type_fact"):
            fact = updated.get(field)
            key = (cls._fact_key(
                fact["subject"], fact["relation"], fact["object"],
                cls._normalize_qualifiers(dict(fact.get("qualifiers", ()))))
                   if isinstance(fact, Mapping) else None)
            if isinstance(fact, Mapping) and key == fact_key:
                remaining = [item for item in fact.get("sources", ())
                             if item != source]
                if not remaining:
                    return None
                updated_fact = dict(fact)
                updated_fact["sources"] = remaining
                updated[field] = updated_fact
        kind_facts = updated.get("middle_kind_facts")
        if isinstance(kind_facts, list):
            revised_kind_facts = []
            for fact in kind_facts:
                key = (cls._fact_key(
                    fact["subject"], fact["relation"], fact["object"],
                    cls._normalize_qualifiers(dict(fact.get("qualifiers", ()))))
                       if isinstance(fact, Mapping) else None)
                if isinstance(fact, Mapping) and key == fact_key:
                    remaining = [item for item in fact.get("sources", ())
                                 if item != source]
                    if not remaining:
                        return None
                    fact = dict(fact)
                    fact["sources"] = remaining
                revised_kind_facts.append(fact)
            updated["middle_kind_facts"] = revised_kind_facts
        return updated

    def _retract_context_fact_pattern_support(
            self, subject: tuple[str, ...], relation: tuple[str, ...],
            obj: tuple[str, ...], qualifiers: tuple[tuple[str, str], ...],
            source: str, *, positive: bool) -> None:
        qualifier_values = tuple(_tokens(value) for _name, value in qualifiers)
        for key, examples in list(self._context_fact_patterns.items()):
            if key[1] != relation or key[3] != positive:
                continue
            for example in list(examples):
                if (example[0] != subject or example[1] != obj
                        or example[2] != qualifier_values
                        or source not in examples[example]):
                    continue
                examples[example].discard(source)
                if not examples[example]:
                    del examples[example]
            if not examples:
                del self._context_fact_patterns[key]

    def _retract_fact_pattern_support(
            self, subject: tuple[str, ...], relation: tuple[str, ...],
            obj: tuple[str, ...], source: str, *, positive: bool) -> None:
        """Remove language examples whose exact fact citation was retracted."""
        pair = (subject, obj)
        removed_alias_supports = {
            item for item in self._fact_pattern_alias_sources
            if item[2] == relation and (item[3], item[4]) == pair
            and item[5] == source and item[6] == positive
        }
        if removed_alias_supports:
            self._fact_pattern_alias_sources.difference_update(removed_alias_supports)
            for alias in {item[0] for item in removed_alias_supports}:
                self._refresh_entity_alias(alias)
        for key, examples in list(self._fact_pattern_examples.items()):
            if (key[1] != relation
                    or self._fact_pattern_polarities.get(key, True) != positive):
                continue
            sources = examples.get(pair)
            if sources is None or source not in sources:
                continue
            sources.discard(source)
            if not sources:
                del examples[pair]
            for phrase, by_pair in self._fact_pattern_predicate_sources.get(
                    key, {}).items():
                phrase_sources = by_pair.get(pair)
                if phrase_sources is not None:
                    phrase_sources.discard(source)
                    if not phrase_sources:
                        del by_pair[pair]
            for surface, by_pair in self._fact_pattern_surface_sources.get(
                    key, {}).items():
                surface_sources = by_pair.get(pair)
                if surface_sources is not None:
                    surface_sources.discard(source)
                    if not surface_sources:
                        del by_pair[pair]
            predicate_sources = self._fact_pattern_predicate_sources.get(key, {})
            for phrase in list(predicate_sources):
                if not predicate_sources[phrase]:
                    del predicate_sources[phrase]
            self._fact_pattern_predicates[key] = set(predicate_sources)
            surface_sources = self._fact_pattern_surface_sources.get(key, {})
            for surface in list(surface_sources):
                if not surface_sources[surface]:
                    del surface_sources[surface]
            self._fact_pattern_surfaces[key] = set(surface_sources)
            if not examples:
                for store_map in (self._fact_pattern_examples,
                                  self._fact_pattern_predicates,
                                  self._fact_pattern_predicate_sources,
                                  self._fact_pattern_surfaces,
                                  self._fact_pattern_surface_sources,
                                  self._fact_pattern_polarities):
                    store_map.pop(key, None)

    def add_inference_rule(self, rule_id: str, first_relation: str,
                           second_relation: str,
                           conclusion_relation: str, *,
                           middle_kind: str | None = None,
                           third_relation: str | None = None,
                           second_middle_kind: str | None = None) -> InferenceRule:
        """Store a two- or three-premise explicit relation-chain rule."""
        rule = InferenceRule(
            _display(rule_id, "rule id"),
            _display(first_relation, "first relation"),
            _display(second_relation, "second relation"),
            _display(conclusion_relation, "conclusion relation"),
            third_relation=(None if third_relation is None else
                            _display(third_relation, "third relation")),
            middle_kind=(None if middle_kind is None else
                         _display(middle_kind, "middle kind")),
            second_middle_kind=(None if second_middle_kind is None else
                                _display(second_middle_kind, "second middle kind")))
        if rule.third_relation is not None and (
                rule.middle_kind is None or rule.second_middle_kind is None):
            raise ValueError("three-premise rules require both middle kinds")
        if rule.third_relation is None and rule.second_middle_kind is not None:
            raise ValueError("second middle kind requires a third relation")
        key = _tokens(rule.rule_id)
        previous = self._inference_rules.get(key)
        if previous is not None and previous != rule:
            raise ValueError("rule id already names a different inference rule")
        self._inference_rules[key] = rule
        return rule

    def add_relation_type(self, relation: str, relation_type: str,
                          source: str, *,
                          qualifiers: Mapping[str, str] | None = None
                          ) -> FactEvidence:
        """Explicitly annotate a relation with a supported symbolic schema type."""
        relation = _display(relation, "relation")
        relation_type = _display(relation_type, "relation type")
        if _tokens(relation_type) not in {
                ("transitive",), ("symmetric",),
                ("irreflexive",), ("asymmetric",), ("functional",),
                ("closed", "world")}:
            raise ValueError(
                "supported relation types are transitive, symmetric, "
                "irreflexive, asymmetric, functional, and closed-world")
        return self.add_fact(relation, "has relation type", relation_type, source,
                             qualifiers=qualifiers)

    def _sqlite_inference_snapshot(
            self, relation: str,
            qualifiers: tuple[tuple[str, str], ...],
            rules: list[InferenceRule]
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                       list[dict[str, Any]]]:
        """Fetch only facts reachable from one query through declared rules."""
        if not isinstance(self._facts, SQLiteFactMap):
            return ([asdict(fact) for fact in self.facts()],
                    [asdict(fact) for fact in self.negative_facts()],
                    [asdict(rule) for rule in rules])
        active_relations = {_tokens(relation)}
        selected_rules: list[InferenceRule] = []
        changed = True
        while changed:
            changed = False
            for rule in rules:
                conclusion = _tokens(rule.conclusion_relation)
                if conclusion not in active_relations:
                    continue
                if rule not in selected_rules:
                    selected_rules.append(rule)
                premises = [_tokens(rule.first_relation),
                            _tokens(rule.second_relation)]
                if rule.third_relation is not None:
                    premises.append(_tokens(rule.third_relation))
                for premise in premises:
                    if premise not in active_relations:
                        active_relations.add(premise)
                        changed = True

        scope = qualifiers

        def exact_scope(fact: FactEvidence) -> bool:
            return self._scope_is_within(fact.qualifiers, scope)

        positive_rows = [fact for fact in
                         self._facts.select_relations(active_relations)
                         if exact_scope(fact)]
        negative_rows = [fact for fact in
                         self._negative_facts.select_relations(active_relations)
                         if exact_scope(fact)]
        active_subjects = active_relations
        positive_rows.extend(
            fact for fact in self._facts.select_relation_subjects(
                _tokens("has relation type"), active_subjects)
            if exact_scope(fact))
        negative_rows.extend(
            fact for fact in self._negative_facts.select_relation_subjects(
                _tokens("has relation type"), active_subjects)
            if exact_scope(fact))

        typed_entities: set[tuple[str, ...]] = set()
        for rule in selected_rules:
            if rule.middle_kind is None:
                continue
            first_relation = _tokens(rule.first_relation)
            second_relation = _tokens(rule.second_relation)
            for fact in positive_rows:
                fact_relation = _tokens(fact.relation)
                if fact_relation == first_relation:
                    typed_entities.add(_tokens(fact.object))
                if fact_relation == second_relation:
                    typed_entities.add(_tokens(fact.object))
        if typed_entities:
            positive_rows.extend(
                fact for fact in self._facts.select_relation_subjects(
                    _tokens("is-a"), typed_entities)
                if exact_scope(fact))
            negative_rows.extend(
                fact for fact in self._negative_facts.select_relation_subjects(
                    _tokens("is-a"), typed_entities)
                if exact_scope(fact))

        def unique(rows: list[FactEvidence]) -> list[dict[str, Any]]:
            keyed = {self._fact_key(
                fact.subject, fact.relation, fact.object,
                self._normalize_qualifiers(dict(fact.qualifiers))): fact
                for fact in rows}
            return [asdict(keyed[key]) for key in sorted(keyed)]

        return (unique(positive_rows), unique(negative_rows),
                [asdict(rule) for rule in selected_rules])

    def _inference_snapshot_fingerprint(
            self, relation: str,
            qualifiers: tuple[tuple[str, str], ...]
            ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]],
                       list[dict[str, Any]]]:
        """Fingerprint the facts and rules that can affect one relation query."""
        fact_rows, negative_rows, rule_rows = self._sqlite_inference_snapshot(
            relation, qualifiers, self._inference_rules_for_use())
        return (_inference_state_fingerprint(fact_rows, negative_rows, rule_rows),
                fact_rows, negative_rows, rule_rows)

    def infer_relation(self, subject: str, relation: str, obj: str, *,
                       qualifiers: Mapping[str, str] | None = None,
                       max_expansions: int | None = None,
                       max_depth: int | None = None,
                       effort: str = "standard") -> InferenceResult:
        """Check a derived triple using explicit rules without storing it."""
        budget = reasoning_budget(effort)
        max_expansions = (budget.max_expansions if max_expansions is None else
                          min(max_expansions, budget.max_expansions))
        max_depth = (budget.max_depth if max_depth is None else
                     min(max_depth, budget.max_depth))
        subject_query = _display(subject, "subject")
        object_query = _display(obj, "object")
        alias_records = self._entity_alias_records()
        evidence_by_key = {}
        for surface in (subject_query, object_query):
            record = alias_records.get(_tokens(surface))
            if record is not None:
                item = dict(record) | {"alias": surface}
                evidence_by_key[json.dumps(
                    item, sort_keys=True, ensure_ascii=False)] = item
        language_evidence = tuple(
            evidence_by_key[key] for key in sorted(evidence_by_key))
        subject = self._canonicalize_query_entity(subject_query)
        obj = self._canonicalize_query_entity(object_query)
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        if (not isinstance(max_expansions, int) or isinstance(max_expansions, bool)
                or max_expansions < 1 or not isinstance(max_depth, int)
                or isinstance(max_depth, bool) or max_depth < 1):
            raise ValueError("inference bounds must be positive integers")
        query_key = self._fact_key(
            subject, relation, obj, normalized_qualifiers)
        for rule_key, rule in self._inference_rules.items():
            validation = self._inference_rule_validation.get(rule_key, {})
            if (validation.get("status") != "needs_review"
                    or _tokens(rule.conclusion_relation) != _tokens(relation)):
                continue
            for counterexample in validation.get("counterexamples", []):
                counterexample_key = self._fact_key(
                    str(counterexample.get("subject", "")),
                    str(counterexample.get("relation", "")),
                    str(counterexample.get("object", "")),
                    self._normalize_qualifiers(dict(
                        counterexample.get("qualifiers", ()))))
                if counterexample_key != query_key:
                    continue
                if isinstance(self._facts, SQLiteFactMap):
                    positive_rows, negative_rows, _rule_rows = (
                        self._sqlite_inference_snapshot(
                            relation, normalized_qualifiers, [rule]))
                else:
                    positive_rows = [asdict(fact) for fact in self.facts()]
                    negative_rows = [asdict(fact)
                                     for fact in self.negative_facts()]
                reviewed = infer_relation(
                    positive_rows, [rule], subject=subject,
                    relation=relation, obj=obj, negative_facts=negative_rows,
                    qualifiers=normalized_qualifiers,
                    max_expansions=max_expansions, max_depth=max_depth,
                    max_candidates=budget.max_candidates,
                    max_proofs=budget.max_proofs)
                if (reviewed.status != "ambiguous" or not reviewed.complete
                        or not any(rule.rule_id in _proof_rule_ids(proof)
                                   for proof in reviewed.proofs)):
                    continue
                if not all(verify_inference_proof(
                        proof, positive_rows, [asdict(rule)],
                        expected_conclusion=reviewed.conclusion,
                        expected_qualifiers=normalized_qualifiers,
                        fact_lookup=self._proof_fact_is_present,
                        max_depth=budget.max_depth,
                        max_nodes=budget.max_verifier_nodes).valid
                           for proof in reviewed.proofs):
                    continue
                return replace(reviewed,
                               language_evidence=language_evidence,
                               effort_level=budget.level)
        if isinstance(self._facts, SQLiteFactMap):
            type_facts = self._facts.lookup(
                _tokens("has relation type"), _tokens(relation), "subject")
        else:
            type_facts = self.facts()
        constrained_types = {
            _tokens(fact.object) for fact in type_facts
            if _tokens(fact.subject) == _tokens(relation)
            and _tokens(fact.relation) == _tokens("has relation type")
            and self._scope_is_within(fact.qualifiers, normalized_qualifiers)
        }
        integrity_constrained = bool(constrained_types.intersection(
            {("irreflexive",), ("asymmetric",)}))
        disk_backed = isinstance(self._facts, SQLiteFactMap)
        cached = (None if integrity_constrained or budget.level == "thorough" else
                  self._reuse_derived_case_for_query(
                      subject, relation, obj,
                      max_expansions=max_expansions, max_depth=max_depth,
                      qualifiers=normalized_qualifiers))
        if cached is not None:
            return replace(cached, language_evidence=language_evidence,
                           effort_level=budget.level)
        rules = self._inference_rules_for_use()
        if disk_backed:
            fact_rows, negative_rows, rule_rows = self._sqlite_inference_snapshot(
                relation, normalized_qualifiers, rules)
            verified_derived_proofs = self._verified_derived_proof_cache(
                max_expansions=max_expansions, max_depth=max_depth,
                qualifiers=normalized_qualifiers)
        else:
            fact_rows = [asdict(fact) for fact in self.facts()]
            negative_rows = [asdict(fact) for fact in self.negative_facts()]
            rule_rows = [asdict(rule) for rule in rules]
            verified_derived_proofs = self._verified_derived_proof_cache(
                max_expansions=max_expansions, max_depth=max_depth,
                qualifiers=normalized_qualifiers)
        result = infer_relation(
            fact_rows, rules, subject=subject,
            relation=relation, obj=obj,
            negative_facts=negative_rows,
            qualifiers=normalized_qualifiers,
            verified_derived_proofs=verified_derived_proofs,
            max_expansions=max_expansions, max_depth=max_depth,
            max_candidates=budget.max_candidates,
            max_proofs=budget.max_proofs, effort_level=budget.level)
        verified_proof_count = 0
        if result.proofs:
            facts = fact_rows

            for proof in result.proofs:
                check = verify_inference_proof(
                    proof, facts, rule_rows, expected_conclusion=result.conclusion,
                    expected_qualifiers=normalized_qualifiers,
                    fact_lookup=self._proof_fact_is_present,
                    max_depth=budget.max_depth,
                    max_nodes=budget.max_verifier_nodes)
                if not check.valid:
                    checks = (("Independent proof verification: rejected "
                               f"the proof ({check.reason})."),) if (
                                   budget.level == "thorough") else ()
                    return InferenceResult(
                        "unknown", request=("The independent proof checker rejected "
                                             f"the inference: {check.reason}"),
                        complete=False, reason_code="proof_rejected",
                        failure_kind="proof_rejected",
                        effort_level=budget.level,
                        effort_checks=checks,
                        language_evidence=language_evidence)
                verified_proof_count += 1
        effort_checks = ()
        if budget.level == "thorough":
            independent_origins = {
                source.split("#", 1)[0]
                for source in result.source_documents if source
            }
            if result.proofs:
                corroboration = (
                    f"Corroboration: {len(independent_origins)} distinct source "
                    f"origin(s) support the verified proof set.")
                proof_check = (
                    f"Independent proof verification: "
                    f"{verified_proof_count}/{len(result.proofs)} proof tree(s) verified.")
            else:
                corroboration = (
                    "Corroboration: no completed proof was available to corroborate.")
                proof_check = (
                    "Independent proof verification: no proof tree was produced.")
            if result.status == "ambiguous":
                conflict_check = "Conflict scan: conflicting or invalid support was found."
            elif result.status == "answered" and result.complete:
                conflict_check = (
                    "Conflict scan: no contradiction or integrity violation was found "
                    "in the checked scope.")
            elif result.proofs:
                conflict_check = (
                    "Conflict scan: no conflict was found before search ended; "
                    "the scan is incomplete.")
            else:
                conflict_check = (
                    "Conflict scan: no proved conclusion was available to check.")
            if result.missing_premises:
                missing_check = (
                    f"Missing-premise follow-through: "
                    f"{len(result.missing_premises)} supported rule gap(s) identified.")
            elif result.failure_kind == "no_applicable_rule":
                missing_check = (
                    "Missing-premise follow-through: no applicable rule to continue.")
            else:
                missing_check = (
                    "Missing-premise follow-through: no specific missing premise found.")
            effort_checks = (corroboration, conflict_check, proof_check,
                             missing_check)
        suspended_rules = [
            rule for key, rule in self._inference_rules.items()
            if (_tokens(rule.conclusion_relation) == _tokens(relation)
                and self._inference_rule_validation.get(key, {}).get(
                    "status") == "needs_review")
        ]
        active_same_relation = any(
            _tokens(rule.conclusion_relation) == _tokens(relation)
            for rule in rules)
        if (result.status == "unknown" and suspended_rules
                and not active_same_relation):
            sources = sorted({
                str(source)
                for rule in suspended_rules
                for counterexample in self._inference_rule_validation[
                    _tokens(rule.rule_id)].get("counterexamples", [])
                for source in counterexample.get("negative_sources", [])
            })
            reports = sorted({
                (str(report.get("answer_id", "")),
                 str(report.get("question", "")))
                for rule in suspended_rules
                for report in self._inference_rule_validation[
                    _tokens(rule.rule_id)].get("feedback_reports", [])
                if isinstance(report, Mapping)
            })
            reasons = []
            if reports:
                reasons.append("a user marked an answer using it wrong")
            if sources:
                reasons.append("contradictory source-backed evidence")
            if not reasons:
                reasons.append("an earlier review flag")
            detail_lines = []
            if sources:
                detail_lines.append("Counterexample source(s): "
                                    + ", ".join(sources) + ".")
            if reports:
                detail_lines.extend(
                    "Feedback " + (answer_id or "unknown")
                    + (f" on {question}" if question else "") + "."
                    for answer_id, question in reports)
            result = replace(
                result,
                request=("A previously validated rule for this relation is "
                         "suspended for review after " + " and ".join(reasons)
                         + ". Review the report and revalidate the rule before "
                         "using it."
                         + (("\n" + "\n".join(detail_lines))
                            if detail_lines else "")),
                reason_code="rule_needs_review",
                failure_kind="rule_needs_review")
        return replace(result, language_evidence=language_evidence,
                       effort_level=budget.level, effort_checks=effort_checks)

    def abduce_relation(self, subject: str, relation: str, obj: str, *,
                        candidates: Iterable[FactCandidate],
                        research_index: Any,
                        qualifiers: Mapping[str, str] | None = None,
                        max_hypothesis_size: int = 2,
                        max_candidates: int = 20,
                        max_subsets: int = 500,
                        max_search_expansions: int = 10_000,
                        max_depth: int = 40) -> AbductionResult:
        """Find minimal, citation-backed pending-fact sets that prove a goal.

        Candidate sentences and citations are revalidated against the supplied
        research index. Search uses a temporary fact snapshot; no candidate is
        accepted, stored, or added to the derived-case cache. The hypothesis
        space is exactly the supplied pending candidates.
        """
        for name, value, minimum in (
                ("max_hypothesis_size", max_hypothesis_size, 1),
                ("max_candidates", max_candidates, 1),
                ("max_subsets", max_subsets, 1),
                ("max_search_expansions", max_search_expansions, 1),
                ("max_depth", max_depth, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be a positive integer")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        pending = list(islice(iter(candidates), max_candidates + 1))
        if any(not isinstance(candidate, FactCandidate) for candidate in pending):
            raise TypeError("candidates must contain FactCandidate records")
        candidate_truncated = len(pending) > max_candidates
        pending = pending[:max_candidates]

        validated: list[FactCandidate] = []
        for candidate in pending:
            if type(candidate.polarity) is not bool:
                raise ValueError("candidate polarity must be boolean")
            excerpt = research_index.resolve_citation(candidate.source)
            if candidate.sentence not in excerpt:
                raise ValueError("candidate sentence does not match its source citation")
            licensed = self.propose_facts(candidate.sentence,
                                          source=candidate.source)
            if not any(
                    (proposed.subject, proposed.relation, proposed.object,
                     proposed.polarity, proposed.qualifiers)
                    == (candidate.subject, candidate.relation, candidate.object,
                        candidate.polarity, candidate.qualifiers)
                    for proposed in licensed):
                raise ValueError(
                    "candidate is not licensed by a learned fact pattern")
            # Validate every proposed triple and qualifier using the same
            # normalization rules as accepted facts.
            _display(candidate.subject, "candidate subject")
            _display(candidate.relation, "candidate relation")
            _display(candidate.object, "candidate object")
            self._normalize_qualifiers(dict(candidate.qualifiers))
            validated.append(candidate)

        if not validated:
            return AbductionResult(
                "incomplete" if candidate_truncated else "no_hypothesis",
                complete=not candidate_truncated,
                request=("Candidate limit truncated the pending hypothesis space."
                         if candidate_truncated else None))

        base_result = self.infer_relation(
            subject, relation, obj, qualifiers=qualifiers,
            max_expansions=max_search_expansions, max_depth=max_depth)
        if base_result.status == "answered":
            return AbductionResult("already_provable", complete=True,
                                   request="The accepted knowledge base already proves this goal.")
        if base_result.status == "ambiguous":
            return AbductionResult("contested", complete=True,
                                   request="The accepted knowledge base already has conflicting support.")
        if not base_result.complete:
            return AbductionResult("incomplete", complete=False,
                                   expansions=base_result.expansions,
                                   request="The accepted-knowledge proof search was incomplete.")

        base_facts = [asdict(fact) for fact in self.facts()]
        base_negative_facts = [asdict(fact) for fact in self.negative_facts()]
        rules = self._inference_rules_for_use()
        found: list[AbductionHypothesis] = []
        used_subsets: list[frozenset[int]] = []
        subsets_checked = 0
        expansions = base_result.expansions
        complete = not candidate_truncated
        request: str | None = (
            "Candidate limit truncated the pending hypothesis space."
            if candidate_truncated else None)

        for size in range(1, min(max_hypothesis_size, len(validated)) + 1):
            for indexes in combinations(range(len(validated)), size):
                if any(existing.issubset(indexes) for existing in used_subsets):
                    continue
                if subsets_checked >= max_subsets:
                    complete = False
                    request = "Subset limit stopped the abduction search."
                    break
                remaining_expansions = max_search_expansions - expansions
                if remaining_expansions < 1:
                    complete = False
                    request = "Expansion limit stopped the abduction search."
                    break
                selected = tuple(validated[index] for index in indexes)
                hypothetical_facts = list(base_facts)
                hypothetical_negatives = list(base_negative_facts)
                for candidate in selected:
                    row = asdict(FactEvidence(
                        candidate.subject, candidate.relation, candidate.object,
                        (candidate.source,), candidate.qualifiers))
                    (hypothetical_facts if candidate.polarity
                     else hypothetical_negatives).append(row)
                trial = infer_relation(
                    hypothetical_facts, rules, subject=subject,
                    relation=relation, obj=obj,
                    negative_facts=hypothetical_negatives,
                    qualifiers=normalized_qualifiers,
                    max_expansions=remaining_expansions, max_depth=max_depth)
                subsets_checked += 1
                expansions += trial.expansions
                if not trial.complete:
                    complete = False
                    request = "A candidate subset exhausted the proof-search bound."
                    break
                if trial.status != "answered" or not trial.proofs:
                    continue
                rules_snapshot = [asdict(rule) for rule in rules]
                verified = all(verify_inference_proof(
                    proof, hypothetical_facts, rules_snapshot,
                    expected_conclusion=trial.conclusion,
                    expected_qualifiers=normalized_qualifiers).valid
                    for proof in trial.proofs)
                if not verified:
                    complete = False
                    request = "The independent verifier rejected a hypothetical proof."
                    break
                used_subsets.append(frozenset(indexes))
                found.append(AbductionHypothesis(
                    selected, trial, minimal=True))
            if not complete:
                break

        if not complete:
            found = [replace(item, minimal=False) for item in found]
        status = "incomplete" if not complete else (
            "hypotheses" if found else "no_hypothesis")
        return AbductionResult(status, tuple(found), complete,
                               subsets_checked, expansions, request)

    def _reuse_derived_case_for_query(
            self, subject: str, relation: str, obj: str, *,
            max_expansions: int, max_depth: int,
            qualifiers: tuple[tuple[str, str], ...] = ()) -> InferenceResult | None:
        """Reuse a complete practiced query only for a covered unchanged state."""
        key = self._fact_key(subject, relation, obj, qualifiers)
        case = self._derived_cases.get(key)
        if case is None:
            return None
        bounds = case.get("validation_bounds", [])
        if not any(isinstance(pair, list) and len(pair) == 2
                   and all(isinstance(value, int) and not isinstance(value, bool)
                           for value in pair)
                   and pair[0] >= max_expansions and pair[1] >= max_depth
                   for pair in bounds):
            return None
        fingerprint, facts, negatives, rules = (
            self._inference_snapshot_fingerprint(relation, qualifiers))
        if case.get("validation_fingerprint") != fingerprint:
            return None
        verified = []
        for proof in case["proofs"]:
            check = verify_inference_proof(
                proof, facts, rules, expected_conclusion=case["conclusion"],
                expected_qualifiers=qualifiers,
                fact_lookup=self._proof_fact_is_present,
                max_depth=max_depth)
            if check.valid:
                verified.append(copy.deepcopy(proof))
        if not verified:
            return None
        support = _proof_support(verified)
        return InferenceResult(
            "answered", copy.deepcopy(case["conclusion"]), tuple(verified),
            expansions=0, support_class=support[0],
            lineage_count=support[1], source_count=support[2],
            source_documents=support[3])

    def _verified_derived_proof_cache(
            self, *, max_expansions: int, max_depth: int,
            qualifiers: tuple[tuple[str, str], ...] = ()
            ) -> dict[tuple[tuple[str, ...], ...], tuple[dict[str, Any], ...]]:
        """Return complete proof trees reusable as bounded inference subgoals."""
        reusable = {}
        for key, case in self._derived_cases.items():
            case_qualifiers = self._normalize_qualifiers(
                dict(case.get("qualifiers", ())))
            if len(key) < 3 or case_qualifiers != qualifiers:
                continue
            fingerprint, facts, negatives, rules = (
                self._inference_snapshot_fingerprint(
                    case["conclusion"]["relation"], case_qualifiers))
            if case.get("validation_fingerprint") != fingerprint:
                continue
            if not any(isinstance(pair, list) and len(pair) == 2
                       and all(isinstance(value, int) and not isinstance(value, bool)
                               for value in pair)
                       and pair[0] >= max_expansions
                       and pair[1] >= max_depth
                       for pair in case.get("validation_bounds", [])):
                continue
            proofs = case.get("proofs", [])
            checked = [proof for proof in proofs
                       if verify_inference_proof(
                           proof, facts, rules,
                           expected_conclusion=case["conclusion"],
                           expected_qualifiers=qualifiers,
                           fact_lookup=self._proof_fact_is_present,
                           max_depth=max_depth).valid]
            # A partial/corrupt set cannot stand in for a complete subsearch.
            if proofs and len(checked) == len(proofs):
                reusable[key[:3]] = tuple(copy.deepcopy(checked))
        return reusable

    def practice_relation(self, subject: str, relation: str, obj: str, *,
                          qualifiers: Mapping[str, str] | None = None,
                          max_expansions: int = 10_000,
                          max_depth: int = 40) -> InferenceResult:
        """Derive and persist an independently verified result as a separate case.

        This is an explicit practice operation: only complete, unambiguous
        inference results are recorded. Derived cases never enter ``facts``
        and therefore cannot become proof leaves. If storage capacity prevents
        retaining the requested case, the inference result is still returned;
        callers should verify retention with ``retrieve_derived_case`` before
        reporting that write-back occurred.
        """
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        result = self.infer_relation(
            subject, relation, obj, qualifiers=dict(normalized_qualifiers),
            max_expansions=max_expansions,
            max_depth=max_depth)
        if (result.status != "answered" or not result.complete or not result.proofs
                or not any(_is_derived_proof(proof)
                           for proof in result.proofs)):
            return result
        assert result.conclusion is not None
        conclusion = result.conclusion
        key = self._fact_key(conclusion["subject"], conclusion["relation"],
                             conclusion["object"], normalized_qualifiers)
        fingerprint, _facts, _negatives, _rules = (
            self._inference_snapshot_fingerprint(
                relation, normalized_qualifiers))
        proofs = [copy.deepcopy(proof) for proof in result.proofs]
        lineage = {"sources": sorted({
            source
            for proof in proofs
            for source in _proof_leaf_sources(proof)
        }), "rule_ids": sorted({
            rule_id
            for proof in proofs
            for rule_id in _proof_rule_ids(proof)
        })}
        existing = self._derived_cases.get(key)
        if existing is None and self.max_derived_cases > 0:
            self._derived_cases[key] = {
                "conclusion": dict(conclusion), "proofs": proofs,
                "lineage": lineage, "practice_count": 1,
                "retrieval_count": 0, "reuse_count": 0,
                "practice_order": self._next_derived_case_order,
                "qualifiers": list(normalized_qualifiers),
                "validation_fingerprint": fingerprint,
                "validation_bounds": [[max_expansions, max_depth]],
            }
            self._next_derived_case_order += 1
        elif existing is not None:
            same_snapshot = existing.get("validation_fingerprint") == fingerprint
            # Dedupe by proof structure while retaining new valid derivations.
            known = {_proof_key(proof) for proof in existing["proofs"]}
            existing["proofs"].extend(
                proof for proof in proofs if _proof_key(proof) not in known)
            existing["lineage"] = {
                "sources": sorted(set(existing["lineage"]["sources"])
                                   | set(lineage["sources"])),
                "rule_ids": sorted(set(existing["lineage"]["rule_ids"])
                                   | set(lineage["rule_ids"])),
            }
            existing["practice_count"] += 1
            existing["qualifiers"] = list(normalized_qualifiers)
            existing["validation_fingerprint"] = fingerprint
            prior_bounds = (existing.get("validation_bounds", [])
                            if same_snapshot else [])
            pair = [max_expansions, max_depth]
            existing["validation_bounds"] = sorted(
                {tuple(item) for item in prior_bounds
                 if isinstance(item, list) and len(item) == 2
                 and all(isinstance(value, int) and not isinstance(value, bool)
                         for value in item)} | {tuple(pair)})
            existing["validation_bounds"] = [list(item) for item in
                                             existing["validation_bounds"]]
        self._enforce_derived_case_limit()
        return result

    def practice_question(
            self, question: str, *,
            qualifiers: Mapping[str, str] | None = None,
            max_inference_expansions: int = 10_000,
            max_depth: int = 40) -> tuple[QuestionResult, bool]:
        """Answer a question and explicitly retain one verified inference.

        Ordinary ``ask()`` remains read-only. This opt-in operation practices
        only a unique answer whose complete result carries inference proofs for
        one exact conclusion and qualifier scope. Direct facts, ambiguity,
        incomplete searches, unsupported frames, and composed questions with
        multiple conclusions are returned without derived-case write-back.
        The normal practice path independently reruns and verifies the proof.
        The returned boolean is true only when the verified case is actually
        retained and can be retrieved under the configured storage cap.
        """
        result = self.ask(
            question, qualifiers=qualifiers,
            max_inference_expansions=max_inference_expansions)
        if result.status != "answered" or not result.inference_proofs:
            return result, False

        conclusions = {
            json.dumps(proof.get("conclusion"), sort_keys=True,
                       ensure_ascii=False)
            for proof in result.inference_proofs
            if isinstance(proof, Mapping)
        }
        if len(conclusions) != 1:
            return result, False
        conclusion = json.loads(next(iter(conclusions)))
        if (not isinstance(conclusion, dict)
                or set(conclusion) != {"subject", "relation", "object"}
                or not all(isinstance(value, str) and value
                           for value in conclusion.values())):
            return result, False

        evidence_rows: list[Mapping[str, Any]] = []

        def collect_leaves(proof: Mapping[str, Any]) -> None:
            if proof.get("kind") == "fact":
                fact = proof.get("fact")
                if isinstance(fact, Mapping):
                    evidence_rows.append(fact)
                return
            for field in ("relation_type_fact", "middle_kind_fact"):
                item = proof.get(field)
                if isinstance(item, Mapping):
                    evidence_rows.append(item)
            for item in proof.get("middle_kind_facts", []):
                if isinstance(item, Mapping):
                    evidence_rows.append(item)
            for premise in proof.get("premises", []):
                if isinstance(premise, Mapping):
                    collect_leaves(premise)

        for proof in result.inference_proofs:
            if isinstance(proof, Mapping):
                collect_leaves(proof)
        if not evidence_rows:
            return result, False
        scopes = {
            self._normalize_qualifiers(dict(row.get("qualifiers", ())))
            for row in evidence_rows
        }
        if len(scopes) != 1:
            return result, False
        practiced = self.practice_relation(
            conclusion["subject"], conclusion["relation"],
            conclusion["object"], qualifiers=dict(next(iter(scopes))),
            max_expansions=max_inference_expansions, max_depth=max_depth)
        retained_case = self.retrieve_derived_case(
            conclusion["subject"], conclusion["relation"],
            conclusion["object"], qualifiers=dict(next(iter(scopes))),
            max_expansions=max_inference_expansions, max_depth=max_depth,
            record_use=False)
        retained = (practiced.status == "answered" and practiced.complete
                    and any(_is_derived_proof(proof)
                            for proof in practiced.proofs)
                    and retained_case is not None
                    and retained_case.get("status") == "verified")
        return result, retained

    def retrieve_derived_case(self, subject: str, relation: str,
                              obj: str, *,
                              qualifiers: Mapping[str, str] | None = None,
                              max_expansions: int = 10_000,
                              max_depth: int = 40,
                              record_use: bool = True) -> dict[str, Any] | None:
        """Return a stored derived case only while its proof is currently valid."""
        if type(record_use) is not bool:
            raise ValueError("record_use must be a bool")
        subject = self._canonicalize_query_entity(_display(subject, "subject"))
        relation = _display(relation, "relation")
        obj = self._canonicalize_query_entity(_display(obj, "object"))
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        key = self._fact_key(subject, relation, obj, normalized_qualifiers)
        case = self._derived_cases.get(key)
        if case is None:
            return None
        fingerprint, facts, negatives, rules = (
            self._inference_snapshot_fingerprint(
                relation, normalized_qualifiers))
        bounds_cover_query = any(
            isinstance(pair, list) and len(pair) == 2
            and all(isinstance(value, int) and not isinstance(value, bool)
                    for value in pair)
            and pair[0] >= max_expansions and pair[1] >= max_depth
            for pair in case.get("validation_bounds", []))
        unchanged = (case.get("validation_fingerprint") == fingerprint
                     and bounds_cover_query)
        current = None
        if not unchanged:
            current = self.infer_relation(
                subject, relation, obj, max_expansions=max_expansions,
                max_depth=max_depth, qualifiers=dict(normalized_qualifiers))
            if current.status != "answered" or not current.complete:
                return None
            # Refresh the cached proof leaves and lineage from the current
            # complete result. This removes retracted citations while keeping
            # derived memory limited to independently checked rule proofs.
            valid = []
            for proof in current.proofs:
                if not _is_derived_proof(proof):
                    continue
                check = verify_inference_proof(
                    proof, facts, rules,
                    expected_conclusion=current.conclusion,
                    expected_qualifiers=normalized_qualifiers,
                    fact_lookup=self._proof_fact_is_present,
                    max_depth=max_depth)
                if check.valid:
                    valid.append(copy.deepcopy(proof))
            if not valid:
                return None
            case["proofs"] = valid
            case["lineage"] = {
                "sources": sorted({
                    source for proof in valid for source in _proof_leaf_sources(proof)
                }),
                "rule_ids": sorted({
                    rule_id for proof in valid for rule_id in _proof_rule_ids(proof)
                }),
            }
            case["validation_fingerprint"] = fingerprint
            case["validation_bounds"] = [[max_expansions, max_depth]]
        else:
            valid = []
            for proof in case["proofs"]:
                check = verify_inference_proof(
                    proof, facts, rules,
                    expected_conclusion=case["conclusion"],
                    expected_qualifiers=normalized_qualifiers,
                    fact_lookup=self._proof_fact_is_present,
                    max_depth=max_depth)
                if check.valid:
                    valid.append(proof)
        if not valid:
            return None
        if record_use:
            case["retrieval_count"] += 1
            if unchanged:
                case["reuse_count"] = case.get("reuse_count", 0) + 1
        return {**copy.deepcopy(case), "proofs": copy.deepcopy(valid),
                "status": "verified"}

    def derived_cases(self) -> list[dict[str, Any]]:
        """List derived artifacts with current validity, without promoting them."""
        results = []
        for case in self._derived_cases.values():
            current = self.retrieve_derived_case(
                case["conclusion"]["subject"],
                case["conclusion"]["relation"],
                case["conclusion"]["object"],
                qualifiers=dict(case.get("qualifiers", ())),
                record_use=False)
            results.append(current or {
                **copy.deepcopy(case), "status": "stale_or_conflicted"})
        return results

    def discover_inference_rules(self, *, min_support: int = 2,
                                 max_expansions: int = 100_000,
                                 max_arity: int = 2,
                                 research_index: Any | None = None,
                                 origin_map: Mapping[str, str] | None = None
                                 ) -> RuleDiscoveryResult:
        """Propose chain rules from labeled facts without installing them."""
        def rows(store, *, discovery_positive: bool = False):
            if isinstance(store, SQLiteFactMap):
                if discovery_positive:
                    # Rule candidates require connected premise edges. Use
                    # endpoint indexes to skip isolated positive facts before
                    # decoding; keep all negative rows for counterexamples.
                    values = store.rule_discovery_values()
                else:
                    values = store.values()
            else:
                values = (store[key] for key in sorted(store))
            return ({"subject": fact.subject, "relation": fact.relation,
                     "object": fact.object, "sources": fact.sources,
                     "qualifiers": fact.qualifiers}
                    for fact in values)

        return discover_rule_candidates(
            rows(self._facts, discovery_positive=True),
            negative_facts=rows(self._negative_facts),
            min_support=min_support, max_expansions=max_expansions,
            max_arity=max_arity, research_index=research_index,
            origin_map=origin_map)

    def review_inference_rules(self, validation_source_prefix: str, *,
                               min_support: int = 2,
                               min_validation_support: int = 2,
                               max_expansions: int = 100_000,
                               max_arity: int = 2,
                               research_index: Any | None = None,
                               origin_map: Mapping[str, str] | None = None
                               ) -> RuleReviewResult:
        """Discover on non-holdout facts and evaluate on a source-heldout split."""
        prefix = _display(validation_source_prefix, "validation source prefix")

        def partition(rows: list[FactEvidence]
                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
            training, validation = [], []
            for fact in rows:
                row = asdict(fact)
                heldout = any(source.startswith(prefix) for source in fact.sources)
                (validation if heldout else training).append(row)
            return training, validation

        training_positive, validation_positive = partition(self.facts())
        training_negative, validation_negative = partition(self.negative_facts())
        discovery = discover_rule_candidates(
            training_positive, negative_facts=training_negative,
            min_support=min_support, max_expansions=max_expansions,
            max_arity=max_arity, research_index=research_index,
            origin_map=origin_map)
        reviews = []
        remaining = max_expansions - discovery.expansions
        total_expansions = discovery.expansions
        complete = discovery.complete
        for candidate in discovery.candidates:
            if remaining < 1:
                validation = RuleValidation("incomplete", (), (), 0, False, 0)
            else:
                validation = validate_rule_candidate(
                    candidate, training_facts=training_positive,
                    training_negative_facts=training_negative,
                    validation_facts=validation_positive,
                    validation_negative_facts=validation_negative,
                    min_positive_examples=min_validation_support,
                    max_expansions=remaining, research_index=research_index,
                    origin_map=origin_map)
                remaining -= validation.expansions
                total_expansions += validation.expansions
            complete = complete and validation.complete
            reviews.append(RuleReview(candidate, validation))
        return RuleReviewResult(complete, tuple(reviews), total_expansions)

    def accept_inference_rule_candidate(
            self, candidate_number: int, rule_id: str,
            validation_source_prefix: str, *, min_support: int = 2,
            min_validation_support: int = 2,
            max_expansions: int = 100_000,
            max_arity: int = 2, research_index: Any | None = None,
            origin_map: Mapping[str, str] | None = None) -> RuleAcceptanceResult:
        """Install only a complete, uncontradicted candidate passing holdout."""
        if (not isinstance(candidate_number, int) or isinstance(candidate_number, bool)
                or candidate_number < 1):
            raise ValueError("candidate number must be a positive integer")
        review_result = self.review_inference_rules(
            validation_source_prefix, min_support=min_support,
            min_validation_support=min_validation_support,
            max_expansions=max_expansions, max_arity=max_arity,
            research_index=research_index, origin_map=origin_map)
        if not review_result.complete:
            return RuleAcceptanceResult(
                False, None, None, "Training candidate search was incomplete.")
        if candidate_number > len(review_result.reviews):
            return RuleAcceptanceResult(
                False, None, None, "No candidate has that number in the current review.")
        review = review_result.reviews[candidate_number - 1]
        if review.validation is None or review.validation.status != "validated":
            status = review.validation.status if review.validation else "unvalidated"
            return RuleAcceptanceResult(
                False, review, None, f"Candidate did not pass holdout validation ({status}).")
        candidate = review.candidate
        rule = self.add_inference_rule(
            rule_id, candidate.first_relation, candidate.second_relation,
            candidate.conclusion_relation,
            middle_kind=candidate.middle_kind,
            third_relation=candidate.third_relation,
            second_middle_kind=candidate.second_middle_kind)
        self._inference_rule_validation[_tokens(rule.rule_id)] = {
            "status": "validated",
            "counterexamples": [],
            "validation_source_prefix": _display(
                validation_source_prefix, "validation source prefix"),
            "training_positive_examples": [dict(example)
                                           for example in candidate.positive_examples],
            "training_negative_examples": [dict(example)
                                           for example in candidate.negative_examples],
            "min_validation_support": min_validation_support,
            "positive_examples": [dict(example)
                                  for example in review.validation.positive_examples],
            "negative_examples": [dict(example)
                                  for example in review.validation.negative_examples],
            "unknown_endpoint_pairs": review.validation.unknown_endpoint_pairs,
            "independent_validation_sources": list(
                review.validation.independent_sources),
            "validation_source_basis": review.validation.source_basis,
            "expansions": review.validation.expansions,
        }
        return RuleAcceptanceResult(True, review, rule)

    @staticmethod
    def _render_rule_example_scope(fact: Mapping[str, Any]) -> str:
        qualifiers = fact.get("qualifiers", ())
        if not qualifiers:
            return ""
        return "context: " + ", ".join(
            f"{name}={value}" for name, value in qualifiers)

    @staticmethod
    def _rule_candidate_chain(candidate: RuleCandidate) -> str:
        relations = [candidate.first_relation, candidate.second_relation]
        if candidate.third_relation is not None:
            relations.append(candidate.third_relation)
        typed = ""
        if candidate.third_relation is not None:
            typed = (f" (middle kinds: {candidate.middle_kind}, "
                     f"{candidate.second_middle_kind})")
        return f"{' then '.join(relations)} entails {candidate.conclusion_relation}{typed}"

    @staticmethod
    def _render_rule_example(example: Mapping[str, Any]) -> str:
        fields = ["first", "second"]
        if "third" in example:
            fields.append("third")
        fields.extend(field for field in ("first_kind", "second_kind")
                      if field in example)
        fields.append("conclusion")
        facts = [example[field] for field in fields]
        return "; ".join(
            f"{fact['subject']} — {fact['relation']} → {fact['object']} "
            f"[{', '.join(fact.get('sources', []))}]"
            for fact in facts)

    @staticmethod
    def render_rule_discovery(result: RuleDiscoveryResult) -> str:
        """Show rule candidates and the fact examples that support or oppose them."""
        completeness = ("complete" if result.complete
                        else "incomplete: expansion limit reached")
        if not result.candidates:
            return (f"Rule discovery {completeness} after {result.expansions} "
                    "candidate expansions; no candidates met the support threshold.")
        lines = [f"Rule discovery {completeness} after {result.expansions} candidate expansions."]
        for candidate in result.candidates:
            coverage = (
                f"coverage={len(candidate.positive_examples)}/"
                f"{candidate.possible_examples} "
                f"({candidate.support_coverage:.1%})"
                if candidate.support_coverage is not None
                else "coverage=unavailable")
            lines.append(
                f"Candidate [{candidate.status}]: {CRMSKnowledgeBase._rule_candidate_chain(candidate)}; "
                f"support={len(candidate.positive_examples)}, "
                f"{coverage}, "
                f"counterexamples={len(candidate.negative_examples)}, "
                f"{candidate.source_basis.replace(' ', '-')}="
                f"{len(candidate.independent_sources)}.")
            for label, examples in (("support", candidate.positive_examples),
                                    ("counterexample", candidate.negative_examples)):
                for example in examples:
                    first = example["first"]
                    scope = CRMSKnowledgeBase._render_rule_example_scope(first)
                    label_text = f"{label} ({scope})" if scope else label
                    lines.append(f"  {label_text}: "
                                 + CRMSKnowledgeBase._render_rule_example(example))
        return "\n".join(lines)

    @staticmethod
    def render_rule_reviews(result: RuleReviewResult) -> str:
        completeness = ("complete" if result.complete
                        else "incomplete: training search limit reached")
        lines = [f"Rule review {completeness}; {result.expansions} training expansions."]
        if not result.reviews:
            lines.append("No candidates met the training support threshold.")
        for number, review in enumerate(result.reviews, 1):
            candidate = review.candidate
            validation = review.validation
            heldout_status = validation.status if validation else "unvalidated"
            heldout_positive = len(validation.positive_examples) if validation else 0
            heldout_negative = len(validation.negative_examples) if validation else 0
            unknown = validation.unknown_endpoint_pairs if validation else 0
            source_count = len(validation.independent_sources) if validation else 0
            training_coverage = (
                f"{len(candidate.positive_examples)}/"
                f"{candidate.possible_examples} "
                f"({candidate.support_coverage:.1%})"
                if candidate.support_coverage is not None
                else "unavailable")
            heldout_total = heldout_positive + heldout_negative + unknown
            heldout_coverage = (
                f"{heldout_positive}/{heldout_total} "
                f"({heldout_positive / heldout_total:.1%})"
                if heldout_total else "unavailable")
            lines.append(
                f"Candidate {number} [{candidate.status}; holdout={heldout_status}]: "
                f"{CRMSKnowledgeBase._rule_candidate_chain(candidate)}; "
                f"train-positive={len(candidate.positive_examples)}, "
                f"train-coverage={training_coverage}, "
                f"train-negative={len(candidate.negative_examples)}, "
                f"holdout-positive={heldout_positive}, "
                f"holdout-coverage={heldout_coverage}, "
                f"holdout-negative={heldout_negative}, holdout-unlabeled={unknown}, "
                f"{(validation.source_basis if validation else candidate.source_basis).replace(' ', '-')}="
                f"{source_count}.")
            for label, examples in (
                    ("holdout-positive", validation.positive_examples if validation else ()),
                    ("holdout-negative", validation.negative_examples if validation else ())):
                for example in examples:
                    first = example["first"]
                    scope = CRMSKnowledgeBase._render_rule_example_scope(first)
                    label_text = f"{label} ({scope})" if scope else label
                    lines.append(f"  {label_text}: "
                                 + CRMSKnowledgeBase._render_rule_example(example))
        return "\n".join(lines)

    @staticmethod
    def render_inference(result: InferenceResult) -> str:
        """Render an inferred result together with explicit supporting facts."""
        completion = "complete" if result.complete else "incomplete"
        status_line = (f"Reasoning effort: {result.effort_level}; "
                       f"search {completion} after {result.expansions} expansions.")
        if result.status == "unknown":
            if result.failure_kind == "no_applicable_rule":
                text = "No inference rule or derivation schema applies to this query."
            elif result.failure_kind == "missing_premise":
                lines = [
                    "A rule applies, but no complete premise chain supports "
                    "this conclusion."]
                for item in result.missing_premises:
                    missing = item.get("missing_premise", {})
                    lines.append(
                        f"  Rule {item.get('rule_id', '?')} is missing premise "
                        f"{item.get('premise_index', '?')}: "
                        f"{missing.get('subject', '?')} — "
                        f"{missing.get('relation', '?')} → "
                        f"{missing.get('object', '?')}.")
                text = "\n".join(lines)
            else:
                text = result.request or "No explicit rule proof supports this conclusion."
        elif result.status == "ambiguous":
            text = result.request or "The inference is ambiguous."
        else:
            assert result.conclusion is not None
            text = ("Derived: {subject} — {relation} → {object}.".format(
                **result.conclusion))
            if result.request:
                text += "\n" + result.request

        for item in result.language_evidence:
            if item.get("kind") == "entity_alias":
                text += (f"\nEntity alias: {item['alias']} → {item['entity']} "
                         f"(sources: {', '.join(item.get('sources', []))}).")
            elif item.get("kind") == "induced_entity_plural":
                support = "; ".join(
                    f"{entry['entity']} → {', '.join(entry['surface_forms'])} "
                    f"[sources: {', '.join(entry['sources'])}]"
                    for entry in item.get("support", []))
                roles = ", ".join(
                    f"{role['relation']} {role['role']}"
                    for role in item.get("shared_roles", []))
                role_sources = ", ".join(item.get("target_role_sources", []))
                text += (f"\nPlural form: {item['alias']} → {item['entity']} "
                         f"(context {item['context']}; role {roles} "
                         f"[target evidence: {role_sources}]; "
                         f"supported by {support}).")

        for number, proof in enumerate(result.proofs, 1):
            text += f"\nProof {number}: {CRMSKnowledgeBase._render_inference_step(proof)}."
        if result.effort_level == "thorough":
            for check in result.effort_checks:
                text += "\n" + check
        return text + "\n" + status_line

    @staticmethod
    def _render_inference_step(proof: Mapping[str, Any]) -> str:
        if proof.get("kind") == "fact":
            fact = proof["fact"]
            return (f"{fact['subject']} — {fact['relation']} → {fact['object']} "
                    f"[sources: {', '.join(fact.get('sources', []))}]")
        rendered = ("; then ".join(
            CRMSKnowledgeBase._render_inference_step(premise)
            for premise in proof["premises"]))
        if proof.get("kind") == "schema":
            schema = proof["schema"]
            type_fact = proof["relation_type_fact"]
            rendered += (f" under schema {schema['schema_id']} "
                         f"instantiated for {schema['relation']} "
                         f"(type source: {', '.join(type_fact.get('sources', []))})")
        else:
            rendered += f" under rule {proof['rule']['rule_id']}"
        kind_fact = proof.get("middle_kind_fact")
        if isinstance(kind_fact, Mapping):
            rendered += (f" (middle kind: {kind_fact['subject']} is-a "
                         f"{kind_fact['object']} [sources: "
                         f"{', '.join(kind_fact.get('sources', []))}])")
        for kind_fact in proof.get("middle_kind_facts", []):
            if isinstance(kind_fact, Mapping):
                rendered += (f" (middle kind: {kind_fact['subject']} is-a "
                             f"{kind_fact['object']} [sources: "
                             f"{', '.join(kind_fact.get('sources', []))}])")
        return rendered

    @staticmethod
    def _inference_fact_leaves(proof: Mapping[str, Any]) -> list[dict[str, Any]]:
        if proof.get("kind") == "fact":
            return [proof["fact"]]
        leaves = [fact for premise in proof.get("premises", [])
                  for fact in CRMSKnowledgeBase._inference_fact_leaves(premise)]
        kind_fact = proof.get("middle_kind_fact")
        if isinstance(kind_fact, Mapping):
            leaves.append(dict(kind_fact))
        leaves.extend(dict(fact) for fact in proof.get("middle_kind_facts", [])
                       if isinstance(fact, Mapping))
        relation_type_fact = proof.get("relation_type_fact")
        if isinstance(relation_type_fact, Mapping):
            leaves.append(dict(relation_type_fact))
        return leaves

    @staticmethod
    def _inference_rule_steps(proof: Mapping[str, Any]) -> list[dict[str, Any]]:
        if proof.get("kind") == "fact":
            return []
        if proof.get("kind") == "schema":
            schema = proof["schema"]
            own_step = {"rule_id": schema["schema_id"],
                        "schema_type": schema["schema_type"],
                        "relation": schema["relation"]}
        else:
            own_step = proof["rule"]
        return ([own_step]
                + [rule for premise in proof.get("premises", [])
                   for rule in CRMSKnowledgeBase._inference_rule_steps(premise)])

    def _canonicalize_entity(self, entity: str) -> str:
        entity = _display(entity, "entity")
        alias = self._entity_aliases.get(_tokens(entity))
        return alias[0] if alias else entity

    def _canonicalize_query_entity(self, entity: str) -> str:
        """Resolve explicit aliases and currently licensed forms in queries."""
        entity = _display(entity, "entity")
        record = self._entity_alias_records().get(_tokens(entity))
        return record["entity"] if record else entity

    def _entity_alias_records(self) -> dict[tuple[str, ...], dict[str, Any]]:
        """Return explicit aliases plus narrowly licensed head-noun plurals."""
        records = {
            alias: {"entity": entity, "sources": sorted(sources),
                    "kind": "entity_alias"}
            for alias, (entity, sources) in self._entity_aliases.items()
        }
        if not self._entity_aliases:
            return records
        fact_rows = self.facts() + self.negative_facts()
        canonical_entities = {
            _tokens(value): value
            for fact in fact_rows
            for value in (fact.subject, fact.object)
        }
        roles: dict[tuple[str, ...], set[tuple[tuple[str, ...], str]]] = {}
        role_sources: dict[
            tuple[str, ...], dict[tuple[tuple[str, ...], str], set[str]]
        ] = {}
        for fact in fact_rows:
            subject_key, object_key = _tokens(fact.subject), _tokens(fact.object)
            subject_role = (_tokens(fact.relation), "subject")
            object_role = (_tokens(fact.relation), "object")
            roles.setdefault(subject_key, set()).add(subject_role)
            roles.setdefault(object_key, set()).add(object_role)
            role_sources.setdefault(subject_key, {}).setdefault(
                subject_role, set()).update(fact.sources)
            role_sources.setdefault(object_key, {}).setdefault(
                object_role, set()).update(fact.sources)
        support: dict[str, dict[str, dict[str, set[str]]]] = {}
        for alias, (entity, sources) in self._entity_aliases.items():
            base_tokens = _tokens(entity)
            if (len(alias) < 1 or len(alias) != len(base_tokens)
                    or alias[:-1] != base_tokens[:-1]):
                continue
            base, surface = base_tokens[-1], alias[-1]
            context = None
            if (base.endswith(("s", "x", "ch", "sh"))
                    and surface == base + "es"):
                context = "sibilant-es"
            elif (len(base) > 1 and base.endswith("y")
                  and base[-2] not in "aeiou" and surface == base[:-1] + "ies"):
                context = "consonant-y-ies"
            elif (not base.endswith(("s", "x", "ch", "sh", "y", "o"))
                  and surface == base + "s"):
                context = "regular-s"
            if context is None:
                continue
            row = support.setdefault(context, {}).setdefault(entity, {})
            row.setdefault(surface, set()).update(sources)

        generated: dict[tuple[str, ...], list[dict[str, Any]]] = {}
        for context, donors in support.items():
            all_roles = set().union(*(roles.get(_tokens(donor), set())
                                      for donor in donors))
            for shared_role in sorted(all_roles):
                scoped_donors = {
                    donor: forms for donor, forms in donors.items()
                    if shared_role in roles.get(_tokens(donor), set())
                }
                documents = {source.split("#", 1)[0]
                             for forms in scoped_donors.values()
                             for values in forms.values() for source in values}
                if len(scoped_donors) < 2 or len(documents) < 2:
                    continue
                for target_tokens, entity in canonical_entities.items():
                    if not target_tokens or shared_role not in roles.get(target_tokens, set()):
                        continue
                    base = target_tokens[-1]
                    if context == "sibilant-es" and base.endswith(("s", "x", "ch", "sh")):
                        surface = base + "es"
                    elif (context == "consonant-y-ies" and len(base) > 1
                          and base.endswith("y") and base[-2] not in "aeiou"):
                        surface = base[:-1] + "ies"
                    elif (context == "regular-s"
                          and not base.endswith(("s", "x", "ch", "sh", "y", "o"))):
                        surface = base + "s"
                    else:
                        continue
                    alias = target_tokens[:-1] + (surface,)
                    if alias in records:
                        continue
                    existing = canonical_entities.get(alias)
                    if existing is not None and _tokens(existing) != target_tokens:
                        continue
                    generated.setdefault(alias, []).append({
                        "entity": entity, "kind": "induced_entity_plural",
                        "context": context,
                        "shared_roles": [{
                            "relation": " ".join(shared_role[0]),
                            "role": shared_role[1]}],
                        "target_role_sources": sorted(
                            role_sources.get(target_tokens, {}).get(shared_role, set())),
                        "sources": sorted({source for forms in scoped_donors.values()
                                            for values in forms.values()
                                            for source in values}),
                        "support": [
                            {"entity": donor,
                             "surface_forms": sorted(forms),
                             "sources": sorted({source for values in forms.values()
                                                for source in values})}
                            for donor, forms in sorted(scoped_donors.items())
                        ],
                    })
        for alias, candidates in generated.items():
            entities = {_tokens(item["entity"]) for item in candidates}
            if len(entities) == 1 and alias not in records:
                merged = dict(candidates[0])
                merged["shared_roles"] = sorted({
                    tuple((role["relation"], role["role"])
                          for role in item["shared_roles"])
                    for item in candidates})
                merged["shared_roles"] = [
                    {"relation": relation, "role": role}
                    for scope in merged["shared_roles"]
                    for relation, role in scope]
                merged["target_role_sources"] = sorted({
                    source for item in candidates
                    for source in item["target_role_sources"]})
                merged["sources"] = sorted({
                    source for item in candidates for source in item["sources"]})
                support_by_entity: dict[str, dict[str, set[str]]] = {}
                for item in candidates:
                    for donor in item["support"]:
                        current = support_by_entity.setdefault(
                            donor["entity"], {})
                        current.setdefault("surface_forms", set()).update(
                            donor["surface_forms"])
                        current.setdefault("sources", set()).update(donor["sources"])
                merged["support"] = [
                    {"entity": donor, "surface_forms": sorted(values["surface_forms"]),
                     "sources": sorted(values["sources"])}
                    for donor, values in sorted(support_by_entity.items())]
                records[alias] = merged
        return records

    def entity_plural_rules(self) -> list[dict[str, Any]]:
        """List active plural rules, evidence, and current query-time forms."""
        grouped: dict[str, dict[str, Any]] = {}
        for alias, record in self._entity_alias_records().items():
            if record.get("kind") != "induced_entity_plural":
                continue
            signature = json.dumps(
                {"context": record["context"],
                 "shared_roles": record.get("shared_roles", []),
                 "support": record.get("support", [])},
                sort_keys=True, ensure_ascii=False)
            rule = grouped.setdefault(signature, {
                "context": record["context"],
                "shared_roles": copy.deepcopy(record.get("shared_roles", [])),
                "sources": list(record.get("sources", [])),
                "support": copy.deepcopy(record.get("support", [])),
                "forms": [],
            })
            rule["forms"].append({"entity": record["entity"],
                                  "plural": " ".join(alias),
                                  "role_sources": list(record.get(
                                      "target_role_sources", []))})
        return sorted(
            (rule | {"forms": sorted(rule["forms"],
                                      key=lambda item: (item["entity"],
                                                        item["plural"]))}
             for rule in grouped.values()),
            key=lambda rule: (rule["context"],
                              tuple((item["relation"], item["role"])
                                    for item in rule["shared_roles"]),
                              tuple(item["plural"] for item in rule["forms"])))

    def _canonical_subject_display(self, subject: str) -> str:
        subject = self._canonicalize_entity(subject)
        subject_key = _tokens(subject)
        displays = {fact.subject
                    for fact in self.facts() + self.negative_facts()
                    if _tokens(fact.subject) == subject_key}
        return next(iter(displays)) if len(displays) == 1 else subject

    def teach_entity_alias(self, alias: str, entity: str, *, source: str) -> None:
        """Ground one unambiguous entity alias to an existing fact entity."""
        alias = _display(alias, "alias")
        entity = self._canonical_subject_display(_display(entity, "entity"))
        source = _display(source, "source")
        alias_key = _tokens(alias)
        entity_key = _tokens(entity)
        known = any(entity_key in (key[0], key[2])
                    for key in (*self._facts.keys(), *self._negative_facts.keys()))
        if not alias_key or not known:
            raise ValueError("alias target must be an entity in stored fact evidence")
        if alias_key == entity_key:
            return
        if any(alias_key in (key[0], key[2]) and alias_key != entity_key
               for key in (*self._facts.keys(), *self._negative_facts.keys())):
            raise ValueError("alias text already names a different stored entity")
        old = self._entity_aliases.get(alias_key)
        if old is not None and _tokens(old[0]) != entity_key:
            raise ValueError("alias already maps to a different entity")
        sources = old[1] if old else set()
        sources.add(source)
        self._entity_aliases[alias_key] = (entity, sources)
        self._entity_alias_explicit_sources.setdefault(alias_key, set()).add(source)

    def _refresh_entity_alias(self, alias_key: tuple[str, ...]) -> None:
        """Rebuild visible alias provenance from independent support routes."""
        links = [item for item in self._fact_pattern_alias_sources
                 if item[0] == alias_key]
        entities = {_tokens(item[1]) for item in links}
        prior = self._entity_aliases.get(alias_key)
        if prior is not None:
            entities.add(_tokens(prior[0]))
        if len(entities) > 1:
            raise ValueError("stored alias supports disagree on their entity")
        if not entities:
            self._entity_aliases.pop(alias_key, None)
            self._entity_alias_explicit_sources.pop(alias_key, None)
            return
        entity_tokens = next(iter(entities))
        entity = (prior[0] if prior is not None
                  and _tokens(prior[0]) == entity_tokens
                  else next((item[1] for item in links
                             if _tokens(item[1]) == entity_tokens),
                            " ".join(entity_tokens)))
        sources = set(self._entity_alias_explicit_sources.get(alias_key, set()))
        sources.update(item[5] for item in links)
        if sources:
            self._entity_aliases[alias_key] = (entity, sources)
        else:
            self._entity_aliases.pop(alias_key, None)

    def teach_entity_alias_from_hit(self, alias: str, entity: str, *,
                                    research_index: Any, hit: Any) -> None:
        """Teach an alias only when both its surface and target occur in a hit."""
        citation = research_index.citation(hit)
        excerpt = research_index.resolve_citation(citation)
        excerpt_words = _tokens(excerpt)

        def occurs(value: str) -> bool:
            phrase = _tokens(value)
            return bool(phrase) and any(
                excerpt_words[i:i + len(phrase)] == phrase
                for i in range(len(excerpt_words) - len(phrase) + 1))

        if not occurs(alias) or not occurs(entity):
            raise ValueError("alias and canonical entity must both occur in the cited passage")
        self.teach_entity_alias(alias, entity, source=citation)

    def entity_aliases(self) -> list[dict[str, Any]]:
        return [
            {"alias": " ".join(alias), "entity": entity, "sources": sorted(sources)}
            for alias, (entity, sources) in sorted(self._entity_aliases.items())
        ]

    def forget_entity_alias(self, alias: str) -> bool:
        """Remove one learned alias so an explicit correction can be taught."""
        alias = _display(alias, "alias")
        key = _tokens(alias)
        existed = self._entity_aliases.pop(key, None) is not None
        self._entity_alias_explicit_sources.pop(key, None)
        self._fact_pattern_alias_sources = {
            item for item in self._fact_pattern_alias_sources if item[0] != key}
        return existed

    def remove_entity_alias_source(self, alias: str, source: str) -> bool:
        """Retract one cited alias example while preserving its other sources."""
        alias = _display(alias, "alias")
        source = _display(source, "source")
        key = _tokens(alias)
        current = self._entity_aliases.get(key)
        if current is None or source not in current[1]:
            return False
        self._entity_alias_explicit_sources.get(key, set()).discard(source)
        self._fact_pattern_alias_sources = {
            item for item in self._fact_pattern_alias_sources
            if not (item[0] == key and item[5] == source)}
        self._refresh_entity_alias(key)
        return True

    def add_fact_from_hit(self, subject: str, relation: str, obj: str,
                          research_index: Any, hit: Any, *,
                          qualifiers: Mapping[str, str] | None = None
                          ) -> FactEvidence:
        """Attach a fact to a verified exact passage in a research index.

        This preserves provenance but does not automatically establish that
        the passage entails the asserted relation; fact extraction remains an
        explicit, inspectable step.
        """
        citation = research_index.citation(hit)
        return self.add_fact(subject, relation, obj, citation,
                             qualifiers=qualifiers)

    def add_negative_fact_from_hit(self, subject: str, relation: str, obj: str,
                                   research_index: Any, hit: Any, *,
                                   qualifiers: Mapping[str, str] | None = None
                                   ) -> FactEvidence:
        """Attach an explicit negative assertion to a verified source hit."""
        citation = research_index.citation(hit)
        return self.add_negative_fact(subject, relation, obj, citation,
                                      qualifiers=qualifiers)

    def teach_context_fact_pattern(
            self, sentence: str, *, subject: str, relation: str, obj: str,
            source: str, qualifiers: Mapping[str, str],
            predicate_phrase: str | None = None,
            qualifier_phrases: Mapping[str, str] | None = None,
            polarity: bool = True) -> bool:
        """Teach a sourced sentence frame with explicit qualifier slots.

        Every slot is labeled against an already stored fact. At least two
        varied examples, including multiple values for each qualifier, are
        required before extraction transfers to new entities or contexts.
        """
        sentence = _display(sentence, "sentence")
        subject = _display(subject, "subject")
        relation = _display(relation, "relation")
        obj = _display(obj, "object")
        source = _display(source, "source")
        predicate_phrase = _display(predicate_phrase or relation,
                                    "predicate_phrase")
        if type(polarity) is not bool:
            raise ValueError("polarity must be a bool")
        normalized = self._normalize_qualifiers(qualifiers)
        if not normalized:
            raise ValueError("context fact frames require at least one qualifier")
        if len(normalized) > 3:
            raise ValueError("context fact frames support at most three qualifiers")
        fact_key = self._fact_key(
            self._canonicalize_entity(subject), relation,
            self._canonicalize_entity(obj), normalized)
        fact_store = self._facts if polarity else self._negative_facts
        supporting_fact = fact_store.get(fact_key)
        if supporting_fact is None:
            raise ValueError("context frame example must reference matching qualified fact evidence")
        if source not in supporting_fact.sources:
            raise ValueError("context frame source must support the qualified fact")

        values = dict(normalized)
        phrases = dict(qualifier_phrases or {})
        if set(map(_tokens, phrases)) - set(map(_tokens, values)):
            raise ValueError("qualifier phrases must name a stored qualifier")
        phrase_by_name = {
            name: _display(next((phrase for key, phrase in phrases.items()
                                 if _tokens(key) == _tokens(name)), value),
                           f"qualifier phrase {name}")
            for name, value in normalized
        }
        matches = word_matches(sentence)
        words = tuple(match.group() for match in matches)
        if len(words) > 256:
            raise ValueError("context fact examples are limited to 256 tokens")

        def spans_for(value: str) -> list[tuple[int, int]]:
            phrase = _tokens(value)
            return [(index, index + len(phrase))
                    for index in range(len(words) - len(phrase) + 1)
                    if phrase and words[index:index + len(phrase)] == phrase]

        subject_spans = spans_for(subject)
        object_spans = spans_for(obj)
        predicate_spans = spans_for(predicate_phrase)
        qualifier_spans = {name: spans_for(phrase)
                           for name, phrase in phrase_by_name.items()}
        if (len(subject_spans) != 1 or len(object_spans) != 1
                or len(predicate_spans) != 1
                or any(len(spans) != 1 for spans in qualifier_spans.values())):
            raise ValueError("each context frame slot must occur exactly once")
        replacements = [
            (*subject_spans[0], "<subject>"),
            (*object_spans[0], "<object>"),
            (*predicate_spans[0], "<predicate>"),
        ]
        qualifier_slot_names = tuple(name for name, _value in normalized)
        for index, name in enumerate(qualifier_slot_names):
            replacements.append((*qualifier_spans[name][0],
                                 f"<context:{index}>"))
        spans = [(start, end) for start, end, _marker in replacements]
        if any(left[0] < right[1] and left[1] > right[0]
               for index, left in enumerate(spans)
               for right in spans[index + 1:]):
            raise ValueError("context frame slots may not overlap")

        template: list[str] = []
        cursor = 0
        for start, end, marker in sorted(replacements):
            template.extend(words[cursor:start])
            template.append(marker)
            cursor = end
        template.extend(words[cursor:])
        key = (tuple(template), _tokens(relation), qualifier_slot_names, polarity)
        example_key = (
            _tokens(subject), _tokens(obj),
            tuple(_tokens(values[name]) for name in qualifier_slot_names),
            _tokens(predicate_phrase))
        examples = self._context_fact_patterns.setdefault(key, {})
        examples.setdefault(example_key, set()).add(source)
        return self._context_fact_pattern_is_licensed(key, examples)

    @staticmethod
    def _context_fact_pattern_is_licensed(
            key: tuple[Any, ...], examples: Mapping[tuple[Any, ...], set[str]]) -> bool:
        if len(examples) < 2:
            return False
        subjects = {example[0] for example in examples}
        objects = {example[1] for example in examples}
        qualifier_names = key[2]
        qualifier_values = [
            {example[2][index] for example in examples}
            for index in range(len(qualifier_names))]
        sources = {source.split("#", 1)[0]
                   for values in examples.values() for source in values}
        return (len(subjects) >= 2 and len(objects) >= 2
                and all(len(values) >= 2 for values in qualifier_values)
                and len(sources) >= 2)

    @staticmethod
    def _match_context_fact_template(
            template: tuple[str, ...], words: tuple[str, ...]
            ) -> tuple[list[dict[str, tuple[int, int]]], bool]:
        """Find unique bounded spans for subject, object, and context slots."""
        captures: list[dict[str, tuple[int, int]]] = []
        budget = 50_000
        steps = 0
        slots = {"<subject>", "<object>"}

        def is_slot(token: str) -> bool:
            return token in slots or (token.startswith("<context:")
                                      and token.endswith(">"))

        def visit(template_index: int, word_index: int,
                  bound: dict[str, tuple[int, int]]) -> None:
            nonlocal steps
            steps += 1
            if steps > budget or len(captures) > 1:
                return
            if template_index == len(template):
                if word_index == len(words):
                    captures.append(dict(bound))
                return
            token = template[template_index]
            if is_slot(token):
                maximum = min(len(words), word_index + 24)
                for end in range(word_index + 1, maximum + 1):
                    bound[token] = (word_index, end)
                    visit(template_index + 1, end, bound)
                    bound.pop(token, None)
                    if steps > budget or len(captures) > 1:
                        return
            elif word_index < len(words) and words[word_index] == token:
                visit(template_index + 1, word_index + 1, bound)

        visit(0, 0, {})
        return captures, steps <= budget

    def _propose_context_fact_patterns(
            self, sentence: str, source: str,
            token_matches: list[re.Match[str]], words: tuple[str, ...]
            ) -> tuple[list[FactCandidate], bool]:
        candidates: dict[tuple[Any, ...], FactCandidate] = {}
        recognized = False
        for key, examples in self._context_fact_patterns.items():
            template, relation_tokens, qualifier_names, polarity = key
            predicate_forms = {example[3] for example in examples}
            for predicate in predicate_forms:
                compiled: list[str] = []
                for token in template:
                    if token == "<predicate>":
                        compiled.extend(predicate)
                    else:
                        compiled.append(token)
                matches, complete = self._match_context_fact_template(
                    tuple(compiled), words)
                if not complete:
                    return [], True
                if not matches:
                    continue
                recognized = True
                if (len(matches) != 1
                        or not self._context_fact_pattern_is_licensed(key, examples)):
                    continue
                spans = matches[0]

                def surface(slot: str) -> str:
                    start, end = spans[slot]
                    return sentence[token_matches[start].start():
                                    token_matches[end - 1].end()]

                subject_surface = surface("<subject>")
                object_surface = surface("<object>")
                qualifier_values = {
                    name: surface(f"<context:{index}>")
                    for index, name in enumerate(qualifier_names)
                }
                qualifiers = self._normalize_qualifiers(qualifier_values)
                support = [{
                    "subject": " ".join(example[0]),
                    "object": " ".join(example[1]),
                    "qualifiers": {
                        name: " ".join(example[2][index])
                        for index, name in enumerate(qualifier_names)},
                    "predicate": " ".join(example[3]),
                    "sources": sorted(sources),
                } for example, sources in sorted(examples.items())]
                evidence = ({
                    "kind": "context_fact_frame",
                    "template": " ".join(template),
                    "relation": " ".join(relation_tokens),
                    "qualifier_names": list(qualifier_names),
                    "support": support,
                },)
                candidate = FactCandidate(
                    self._canonicalize_entity(subject_surface),
                    " ".join(relation_tokens),
                    self._canonicalize_entity(object_surface), source,
                    " ".join(template), sentence, polarity, evidence,
                    qualifiers)
                signature = (
                    _tokens(candidate.subject), candidate.relation,
                    _tokens(candidate.object),
                    tuple((_tokens(name), _tokens(value))
                          for name, value in qualifiers), polarity)
                candidates[signature] = candidate
        if recognized and len(candidates) > 1:
            return [], True
        return list(candidates.values()), recognized

    def teach_context_fact_pattern_from_hit(
            self, sentence: str, *, subject: str, relation: str, obj: str,
            qualifiers: Mapping[str, str], research_index: Any, hit: Any,
            predicate_phrase: str | None = None,
            qualifier_phrases: Mapping[str, str] | None = None,
            polarity: bool = True) -> bool:
        """Teach a qualified frame only from a sentence in the cited passage."""
        citation = research_index.citation(hit)
        excerpt = research_index.resolve_citation(citation)
        if sentence not in excerpt:
            raise ValueError("training sentence is not contained in the cited passage")
        return self.teach_context_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=citation, qualifiers=qualifiers,
            predicate_phrase=predicate_phrase,
            qualifier_phrases=qualifier_phrases, polarity=polarity)

    def teach_fact_pattern(self, sentence: str, *, subject: str,
                           relation: str, obj: str, source: str,
                           predicate_phrase: str | None = None,
                           polarity: bool = True,
                           subject_phrase: str | None = None,
                           object_phrase: str | None = None,
                           learn_surface_entity_aliases: bool = True,
                           ordered_class_membership_spans: bool = False) -> bool:
        """Ground a sentence frame and predicate phrase after varied support.

        The asserted fact must already exist with provenance. The sentence
        must contain one unambiguous span for each entity and predicate phrase.
        The canonical ``relation`` may differ from the observed phrase only
        because the teacher explicitly grounded that phrase to this fact.
        At least two distinct subjects and objects are required for proposals.
        """
        sentence = _display(sentence, "sentence")
        subject = _display(subject, "subject")
        subject_phrase = _display(subject_phrase or subject, "subject_phrase")
        relation = _display(relation, "relation")
        predicate_phrase = _display(predicate_phrase or relation, "predicate_phrase")
        obj = _display(obj, "object")
        object_phrase = _display(object_phrase or obj, "object_phrase")
        source = _display(source, "source")
        if type(polarity) is not bool:
            raise ValueError("polarity must be a bool")
        if type(learn_surface_entity_aliases) is not bool:
            raise ValueError("learn_surface_entity_aliases must be a bool")
        if type(ordered_class_membership_spans) is not bool:
            raise ValueError("ordered_class_membership_spans must be a bool")
        canonical_subject = self._canonicalize_entity(subject)
        canonical_obj = self._canonicalize_entity(obj)
        fact_key = self._fact_key(canonical_subject, relation, canonical_obj)
        supporting_fact = (self._facts if polarity else self._negative_facts).get(fact_key)
        if supporting_fact is None:
            raise ValueError("fact-pattern example must reference matching truth evidence")
        if source not in supporting_fact.sources:
            raise ValueError("fact-pattern source must be attached to the supporting fact")

        matches = word_matches(sentence)
        words = tuple(match.group() for match in matches)
        if len(words) > 256:
            raise ValueError("fact-pattern examples are limited to 256 tokens")
        if (not _tokens(subject) or not _tokens(obj) or not _tokens(relation)
                or not _tokens(predicate_phrase)):
            raise ValueError("subject, relation, and object must contain searchable words")

        def spans_for(value: str) -> list[tuple[int, int]]:
            value_words = _tokens(value)
            return [(i, i + len(value_words))
                    for i in range(len(words) - len(value_words) + 1)
                    if words[i:i + len(value_words)] == value_words]

        subject_spans = spans_for(subject_phrase)
        object_spans = spans_for(object_phrase)
        predicate_words = _tokens(predicate_phrase)
        predicate_spans = [(i, i + len(predicate_words))
                            for i in range(len(words) - len(predicate_words) + 1)
                            if words[i:i + len(predicate_words)] == predicate_words]
        if ordered_class_membership_spans:
            # A class noun can occur both inside a named entity and again in
            # the predicate complement ("The Serein River is a river"). For
            # this explicitly parsed copular class frame, use the syntactic
            # order to select a unique non-overlapping subject/copula/class
            # assignment; leave all other frame types on the stricter unique
            # surface-span rule below.
            assignments = [
                (subject_span, object_span, predicate_span)
                for subject_span in subject_spans
                for object_span in object_spans
                for predicate_span in predicate_spans
                if (subject_span[1] <= predicate_span[0]
                    and predicate_span[1] <= object_span[0])]
            if len(assignments) != 1:
                raise ValueError(
                    "class membership roles are not uniquely ordered")
            subject_span, object_span, predicate_span = assignments[0]
        else:
            if len(subject_spans) != 1 or len(object_spans) != 1:
                raise ValueError("subject and object must each occur exactly once")
            if len(predicate_spans) != 1:
                raise ValueError("predicate phrase must occur exactly once")
            subject_span, object_span, predicate_span = (
                subject_spans[0], object_spans[0], predicate_spans[0])
            grounded_spans = (subject_span, object_span, predicate_span)
            if any(a[0] < b[1] and a[1] > b[0]
                   for index, a in enumerate(grounded_spans)
                   for b in grounded_spans[index + 1:]):
                raise ValueError(
                    "subject, object, and predicate spans may not overlap")

        # Surface phrases are explicit teacher alignments to the already
        # supported canonical fact slots. Keep the source citation as alias
        # provenance so it can be retracted through remove_entity_alias_source.
        alias_pairs = []
        aligned_targets: dict[tuple[str, ...], tuple[str, ...]] = {}
        surface_alignments = ((subject_phrase, canonical_subject),
                              (object_phrase, canonical_obj))
        for phrase, canonical in (surface_alignments if
                                  learn_surface_entity_aliases else ()):
            if _tokens(phrase) == _tokens(canonical):
                continue
            alias_key = _tokens(phrase)
            existing = self._entity_aliases.get(alias_key)
            if existing is not None and _tokens(existing[0]) != _tokens(canonical):
                raise ValueError("surface phrase is already aligned to another entity")
            if (alias_key in aligned_targets
                    and aligned_targets[alias_key] != _tokens(canonical)):
                raise ValueError("surface phrase aligns to two different fact entities")
            if any(alias_key in (stored_key[0], stored_key[2])
                   and alias_key != _tokens(canonical)
                   for stored_key in (*self._facts.keys(), *self._negative_facts.keys())):
                raise ValueError("surface phrase already names a different stored entity")
            aligned_targets[alias_key] = _tokens(canonical)
            alias_pairs.append((phrase, canonical))
        replacements = [(subject_span[0], subject_span[1], "<subject>"),
                        (object_span[0], object_span[1], "<object>"),
                        (predicate_span[0], predicate_span[1], "<predicate>")]
        template: list[str] = []
        cursor = 0
        for start, end, marker in sorted(replacements):
            template.extend(words[cursor:start])
            template.append(marker)
            cursor = end
        template.extend(words[cursor:])
        key = (tuple(template), _tokens(relation))
        previous_polarity = self._fact_pattern_polarities.get(key)
        if previous_polarity is not None and previous_polarity != polarity:
            raise ValueError("one sentence frame cannot be taught with conflicting polarity")
        alias_supports = []
        for phrase, canonical in alias_pairs:
            alias_key = _tokens(phrase)
            entity_key = _tokens(canonical)
            old = self._entity_aliases.get(alias_key)
            if old is not None and _tokens(old[0]) != entity_key:
                raise ValueError("alias already maps to a different entity")
            alias_support = (alias_key, canonical, _tokens(relation),
                             _tokens(canonical_subject), _tokens(canonical_obj),
                             source, polarity)
            alias_supports.append(alias_support)
        for alias_support in alias_supports:
            self._fact_pattern_alias_sources.add(alias_support)
            self._refresh_entity_alias(alias_support[0])
        self._fact_pattern_polarities[key] = polarity
        pair = (_tokens(canonical_subject), _tokens(canonical_obj))
        examples = self._fact_pattern_examples.setdefault(key, {})
        examples.setdefault(pair, set()).add(source)
        self._fact_pattern_predicates.setdefault(key, set()).add(predicate_words)
        self._fact_pattern_predicate_sources.setdefault(key, {}).setdefault(
            predicate_words, {}).setdefault(pair, set()).add(source)
        char_spans = [
            (matches[start].start(), matches[end - 1].end(), marker)
            for start, end, marker in replacements if marker != "<predicate>"
        ]
        surface_template: list[str] = []
        cursor = 0
        for start, end, marker in sorted(char_spans):
            surface_template.extend((sentence[cursor:start],
                                     "{{" + marker[1:-1] + "}}"))
            cursor = end
        surface_template.append(sentence[cursor:])
        surface = "".join(surface_template)
        self._fact_pattern_surfaces.setdefault(key, set()).add(surface)
        self._fact_pattern_surface_sources.setdefault(key, {}).setdefault(
            surface, {}).setdefault(pair, set()).add(source)
        return self._fact_pattern_is_licensed(key, examples)

    def _fact_pattern_is_licensed(
            self, key: tuple[tuple[str, ...], tuple[str, ...]],
            examples: Mapping[tuple[tuple[str, ...], tuple[str, ...]], Any]
            ) -> bool:
        """License varied exact frames or one grounded frame transfer.

        A new syntax can transfer after one source-backed, fact-aligned example
        only when the same canonical relation and polarity already have an
        independently varied frame. This is structural frame transfer, not
        automatic synonym or relation discovery.
        """
        subjects = {subject for subject, _ in examples}
        objects = {obj for _, obj in examples}
        if len(examples) >= 2 and len(subjects) >= 2 and len(objects) >= 2:
            return True
        if len(examples) != 1:
            return False
        relation = key[1]
        polarity = self._fact_pattern_polarities.get(key, True)
        for other_key, other_examples in self._fact_pattern_examples.items():
            if (other_key == key or other_key[1] != relation
                    or self._fact_pattern_polarities.get(other_key, True) != polarity
                    or len(other_examples) < 2):
                continue
            other_subjects = {subject for subject, _ in other_examples}
            other_objects = {obj for _, obj in other_examples}
            if len(other_subjects) >= 2 and len(other_objects) >= 2:
                return True
        return False

    def fact_pattern_diagnostics(
            self, sentence: str, *, subject: str, relation: str, obj: str,
            polarity: bool = True, predicate_phrase: str | None = None,
            subject_phrase: str | None = None,
            object_phrase: str | None = None) -> dict[str, Any]:
        """Explain the current varied-example gate for one taught sentence.

        The returned counts describe the exact learned frame that parses the
        supplied sentence and slots; they do not alter or license it.
        """
        sentence = _display(sentence, "sentence")
        subject = _display(subject, "subject")
        obj = _display(obj, "object")
        subject_phrase = _display(subject_phrase or subject, "subject_phrase")
        object_phrase = _display(object_phrase or obj, "object_phrase")
        predicate_phrase = _display(predicate_phrase or relation,
                                    "predicate_phrase")
        matches = word_matches(sentence)
        words = tuple(match.group() for match in matches)
        relation_key = _tokens(_display(relation, "relation"))
        def spans_for(value: str) -> list[tuple[int, int]]:
            phrase = _tokens(value)
            return [(index, index + len(phrase))
                    for index in range(len(words) - len(phrase) + 1)
                    if words[index:index + len(phrase)] == phrase]

        subject_spans = spans_for(subject_phrase)
        object_spans = spans_for(object_phrase)
        predicate_spans = spans_for(predicate_phrase)
        if not (len(subject_spans) == len(object_spans)
                == len(predicate_spans) == 1):
            return {
                "status": "unavailable",
                "reason": ("The subject, object, and predicate must each occur "
                           "exactly once in this sentence."),
            }
        replacements = [(subject_spans[0], "<subject>"),
                        (predicate_spans[0], "<predicate>"),
                        (object_spans[0], "<object>")]
        if any(a[0] < b[1] and a[1] > b[0]
               for index, (a, _marker) in enumerate(replacements)
               for b, _other in replacements[index + 1:]):
            return {"status": "unavailable",
                    "reason": "The labeled sentence spans overlap."}
        template: list[str] = []
        cursor = 0
        for (start, end), marker in sorted(replacements):
            template.extend(words[cursor:start])
            template.append(marker)
            cursor = end
        template.extend(words[cursor:])
        key = (tuple(template), relation_key)
        examples = self._fact_pattern_examples.get(key)
        if (examples is None
                or self._fact_pattern_polarities.get(key, True) != polarity):
            return {"status": "unavailable",
                    "reason": "No taught pattern matches this exact sentence frame."}
        subjects = {pair[0] for pair in examples}
        objects = {pair[1] for pair in examples}
        cited_sources = sorted({source for sources in examples.values()
                                for source in sources})
        licensed = self._fact_pattern_is_licensed(key, examples)
        reasons = []
        transfer = licensed and not (
            len(examples) >= 2 and len(subjects) >= 2 and len(objects) >= 2)
        if transfer:
            reasons.append("licensed by transfer from another varied frame")
        elif not licensed:
            if len(examples) < 2:
                reasons.append("needs at least 2 distinct subject/object pairs")
            if len(subjects) < 2:
                reasons.append("needs at least 2 distinct subjects")
            if len(objects) < 2:
                reasons.append("needs at least 2 distinct objects")
        return {
            "status": "licensed" if licensed else "unlicensed",
            "distinct_pairs": len(examples),
            "distinct_subjects": len(subjects),
            "distinct_objects": len(objects),
            "cited_sources": cited_sources,
            "independent_sources": len({source.split("#", 1)[0]
                                         for source in cited_sources}),
            "transfer": transfer,
            "reasons": reasons,
            "examples": [
                {"subject": " ".join(pair[0]),
                 "object": " ".join(pair[1]),
                 "sources": sorted(sources)}
                for pair, sources in sorted(examples.items())],
        }

    def _licensed_predicate_spelling_rules(
            self) -> dict[tuple[tuple[str, ...], int, str, str, str],
                         dict[tuple[str, ...], dict[str, tuple[str, ...]]]]:
        """Induce aligned predicate rules with cross-relation/source support."""
        support: dict[tuple[tuple[str, ...], int, str, str, str],
                      dict[tuple[str, ...], dict[str, set[str]]]] = {}
        for key, examples in self._fact_pattern_examples.items():
            if not self._fact_pattern_is_licensed(key, examples):
                continue
            relation = key[1]
            for predicate in self._fact_pattern_predicates.get(key, set()):
                if len(predicate) != len(relation):
                    continue
                changed = [index for index, (base_word, surface_word)
                           in enumerate(zip(relation, predicate))
                           if base_word != surface_word]
                if len(changed) != 1:
                    continue
                index = changed[0]
                alignment = _analyze_predicate_spelling(
                    relation[index], predicate[index])
                if alignment is None:
                    continue
                context, removed, ending = alignment
                frame = list(relation)
                frame[index] = "<predicate>"
                pattern = (tuple(frame), index, context, removed, ending)
                relation_support = support.setdefault(pattern, {}).setdefault(
                    relation, {})
                relation_support.setdefault(" ".join(predicate), set()).update(
                    source for sources in examples.values()
                    for source in sources)
        licensed = {}
        for pattern, relations in support.items():
            source_documents = {
                source.split("#", 1)[0]
                for forms in relations.values()
                for sources in forms.values()
                for source in sources
            }
            if len(relations) < 2 or len(source_documents) < 2:
                continue
            licensed[pattern] = {relation: {
                "surface_forms": tuple(sorted(forms)),
                "sources": tuple(sorted({source for sources in forms.values()
                                         for source in sources})),
            } for relation, forms in relations.items()}
        return licensed

    def _predicate_forms_for_relation(
            self, relation: tuple[str, ...],
            observed: Iterable[tuple[str, ...]]) -> tuple[
                set[tuple[str, ...]], dict[tuple[str, ...], dict[str, Any]]]:
        """Return observed forms plus spelling forms licensed by other relations."""
        forms = set(observed) | {relation}
        generated_evidence: dict[tuple[str, ...], dict[str, Any]] = {}

        def is_unaligned_lexeme_form(phrase: tuple[str, ...]) -> bool:
            if len(phrase) != len(relation):
                return False
            changed = [index for index, (base, surface)
                       in enumerate(zip(relation, phrase)) if base != surface]
            return (len(changed) == 1
                    and _analyze_predicate_spelling(
                        relation[changed[0]], phrase[changed[0]]) is None)

        has_unaligned_lexeme_form = any(
            is_unaligned_lexeme_form(phrase)
            for phrase in forms if phrase != relation)
        # Surface forms explicitly grounded to this exact relation are usable
        # for transfer, but retain their own source lineage. They are lexical
        # observations, not evidence for a productive spelling rule.
        for key, examples in self._fact_pattern_examples.items():
            if key[1] != relation or not self._fact_pattern_is_licensed(
                    key, examples):
                continue
            for phrase in self._fact_pattern_predicates.get(key, set()):
                if phrase == relation or phrase not in forms:
                    continue
                phrase_examples = self._fact_pattern_predicate_sources.get(
                    key, {}).get(phrase, {})
                sources = tuple(sorted({source for values
                                        in phrase_examples.values()
                                        for source in values}))
                if not sources:
                    continue
                generated_evidence.setdefault(phrase, {
                    "kind": "observed_predicate_form",
                    "canonical_form": " ".join(relation),
                    "surface_form": " ".join(phrase),
                    "support": [{
                        "relation": " ".join(relation),
                        "surface_forms": [" ".join(phrase)],
                        "sources": list(sources),
                    }],
                })
        rules = self._licensed_predicate_spelling_rules()
        for (frame, index, rule_context, rule_removed, ending), support in rules.items():
            if (has_unaligned_lexeme_form and rule_context == "other-ending"
                    and ending == "ed"):
                # A grounded lexeme-specific surface form blocks guessing a
                # generic regular past form for that same predicate. Other
                # independently licensed endings remain available.
                continue
            if (len(relation) != len(frame) or index >= len(relation)
                    or any(expected != "<predicate>" and expected != relation[i]
                           for i, expected in enumerate(frame))):
                continue
            base = relation[index]
            context, removed = _predicate_spelling_class(base)
            stem = (base[:-1] if context == "cvc-double"
                    else base[:-len(removed)] if removed else base)
            doubled_endings = {
                other_ending
                for (other_frame, other_index, other_context, _other_removed,
                     other_ending) in rules
                if (other_frame == frame and other_index == index
                    and other_context == "cvc-double")
            }
            if context == "cvc-double":
                if rule_context == "other-ending":
                    # Where evidence licenses doubling for this ending, prefer
                    # the more specific CVC transformation over plain append.
                    # Past and progressive endings require CVC evidence before
                    # applying this class; never guess the undoubled form.
                    if ending in doubled_endings or ending in {"ed", "ing"}:
                        continue
                elif (rule_context, rule_removed) != (
                        "cvc-double", "final-consonant"):
                    continue
            elif context == "final-e":
                if rule_context == "final-ie-y":
                    if not base.endswith("ie") or ending != "ing":
                        continue
                elif rule_context == "other-ending":
                    # These endings need the final-e spelling change; blindly
                    # appending them would create forms such as "bakeed" or
                    # "tieing" when the grounded class requires ie → y.
                    if ending in {"ed", "es", "ing"}:
                        continue
            elif context == "final-c":
                if ending in {"ed", "ing"}:
                    if (rule_context, rule_removed) != ("final-c-k", ""):
                        continue
                elif ending == "s":
                    if rule_context != "other-ending":
                        continue
                else:
                    continue
            elif context == "sibilant":
                if rule_context == "sibilant-es":
                    if ending != "es":
                        continue
                elif rule_context == "other-ending":
                    if ending == "es":
                        continue
                else:
                    continue
            elif context == "final-o":
                if rule_context == "final-o-es":
                    if ending != "es":
                        continue
                elif rule_context == "other-ending":
                    if ending in {"s", "es"}:
                        continue
                else:
                    continue
            elif context == "single-z-after-vowel":
                if rule_context != "single-z-double":
                    continue
            elif (context == "consonant-y"
                  and rule_context == "other-ending" and ending == "ing"):
                # English retains final y before -ing (copy -> copying), even
                # though other productive endings may change y to i (study ->
                # studied). Keep the two spelling behaviors distinct.
                pass
            elif (context, removed) != (rule_context, rule_removed):
                continue
            independent = {other_relation: values
                           for other_relation, values in support.items()
                           if other_relation != relation}
            if len(independent) < 2:
                continue
            if rule_context == "other-ending":
                generated_token = base + ending
            elif rule_context == "cvc-double":
                generated_token = stem + base[-1] * 2 + ending
            elif rule_context == "single-z-double":
                generated_token = stem + base[-1] * 2 + ending
            elif rule_context == "final-c-k":
                generated_token = base + "k" + ending
            elif rule_context == "final-o-es":
                generated_token = base + "es"
            elif rule_context == "final-ie-y":
                generated_token = base[:-2] + "ying"
            else:
                generated_token = stem + ending
            generated_words = list(relation)
            generated_words[index] = generated_token
            generated = tuple(generated_words)
            if generated in forms:
                continue
            forms.add(generated)
            generated_evidence[generated] = {
                "kind": "induced_suffix",
                "canonical_form": " ".join(relation),
                "surface_form": " ".join(generated),
                "suffix": ("d" if rule_context == "final-e"
                           and ending == "ed" else ending),
                "context": rule_context,
                "removed_ending": rule_removed,
                "support": [
                    {"relation": " ".join(other_relation),
                     "surface_forms": list(values["surface_forms"]),
                     "sources": list(values["sources"])}
                    for other_relation, values in sorted(independent.items())
                ],
            }
        return forms, generated_evidence

    def _observed_predicates_by_relation(
            self) -> dict[tuple[str, ...], set[tuple[str, ...]]]:
        observed: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        for key, examples in self._fact_pattern_examples.items():
            if self._fact_pattern_is_licensed(key, examples):
                observed.setdefault(key[1], set()).update(
                    self._fact_pattern_predicates.get(key, set()))
        return observed

    def _question_frame_variants(
            self, relation: tuple[str, ...], prefix: tuple[str, ...],
            suffix: tuple[str, ...],
            forms: set[tuple[str, ...]],
            morphology: Mapping[tuple[str, ...], Mapping[str, Any]] | None = None
            ) -> set[tuple[tuple[str, ...], tuple[str, ...]]]:
        """Generate frame variants from grounded forms and licensed syntax."""
        variants = {(prefix, suffix)}
        replacements = set(forms)
        # In do-support questions the predicate is in its infinitive form:
        # ``What did Y create?``. A source-backed irregular form such as
        # ``made`` is evidence for the same canonical relation, but does not
        # literally occur in that frame. Transfer it to ``make`` only when the
        # irregular form was explicitly learned for this relation and the
        # frame contains the regular infinitive corresponding to the canonical
        # past form (create -> created). This adds a traceable frame variant;
        # it does not add a fact or a free-standing synonym.
        if (isinstance(morphology, dict)
                and any(auxiliary in prefix for auxiliary in {"did", "do", "does"})
                and len(relation) == 1):
            canonical = relation[0]
            for observed, evidence in tuple(morphology.items()):
                if (len(observed) != 1
                        or evidence.get("kind") != "observed_predicate_form"):
                    continue
                observed_word = observed[0]
                lemma = next((lemma for lemma, forms_ in
                              _IRREGULAR_VERB_PARADIGMS.items()
                              if observed_word in forms_ and lemma != observed_word),
                             None)
                if lemma is None or lemma == canonical:
                    continue
                licensed_side = None
                for side_index, side in enumerate((prefix, suffix)):
                    for position, token in enumerate(side):
                        if (token == canonical
                                or _analyze_predicate_spelling(token, canonical)):
                            licensed_side = (side_index, side, position, token)
                            break
                    if licensed_side is not None:
                        break
                if licensed_side is None:
                    continue
                side_index, side, position, _licensed_form = licensed_side
                changed = side[:position] + (lemma,) + side[position + 1:]
                variant = ((changed, suffix) if side_index == 0
                           else (prefix, changed))
                variants.add(variant)
                support = [dict(item) for item in evidence.get("support", [])]
                morphology[(lemma,)] = {
                    "kind": "irregular_do_support_question_transfer",
                    "canonical_form": " ".join(relation),
                    "surface_form": lemma,
                    "observed_form": observed_word,
                    "licensed_frame": " ".join(
                        prefix + ("{bound_entity}",) + suffix),
                    "derived_frame": " ".join(
                        variant[0] + ("{bound_entity}",) + variant[1]),
                    "support": support,
                }
        # English progressive questions place "is" before a grounded -ing
        # predicate ("Who admired X?" -> "Who is admiring X?"). Only add
        # this structure when the predicate form itself came from an induced,
        # independently supported -ing spelling rule.
        for side_index, side in enumerate((prefix, suffix)):
            replacements = set(forms)
            if side_index == 0:
                # A singular WH subject can form a present-perfect question
                # with ``has + regular past participle``: ``Who discovered X?``
                # -> ``Who has discovered X?``. The predicate itself must be
                # the exact licensed single-token -ed form; this is a bounded
                # aspect transformation, not a new predicate alignment.
                if (prefix[:1] in {("who",), ("what",)}
                        and len(prefix) == 2 and prefix[1:] in forms):
                    replacements.update(
                        ("has",) + phrase for phrase in forms
                        if len(phrase) == 1 and phrase[0].endswith("ed"))
                # Reviewed nominal relation forms such as "creator of" can
                # replace a verb in a learned question frame only when the
                # auxiliary and article are restored: "Who created X?" ->
                # "Who is the creator of X?". The source-backed phrase is
                # still the evidence; this adds only its required question
                # structure, not a relation synonym.
                replacements.update(
                    ("is", "the") + phrase for phrase in forms
                    if phrase and phrase[-1] == "of")
                # Nominal-to-verb bridge for regular agent nouns. ``-er``
                # and ``-tor`` have transparent stems here: designer ->
                # designed, inventor -> invented, creator -> created. The
                # nominal frame itself must be licensed by accepted examples;
                # unrelated ``-or`` nouns such as author do not qualify.
                if (prefix[:3] == ("who", "is", "the")
                        and len(prefix) >= 5 and prefix[-1] == "of"):
                    nominal = prefix[-2]
                    if nominal.endswith("er") and len(nominal) > 2:
                        verb_stem = nominal[:-2]
                    elif nominal.endswith("tor") and len(nominal) > 3:
                        verb_stem = nominal[:-2]
                    else:
                        verb_stem = ""
                    if verb_stem:
                        variants.add((("who", verb_stem + "ed"), suffix))
                # Number and auxiliary agreement can vary while preserving
                # the same reviewed nominal relation: ``Who is the creator
                # of X?`` / ``Who are the creators of X?``. Generate only
                # regular plural spelling from the observed singular noun.
                if (prefix and prefix[0] in {"who", "what"}
                        and len(prefix) >= 5
                        and prefix[1:3] == ("is", "the")
                        and prefix[-1] == "of"):
                    head = list(prefix[3:-1])
                    noun = head[-1] if head else ""
                    if noun.endswith(("s", "x", "z", "ch", "sh")):
                        plural = noun + "es"
                    elif (len(noun) > 1 and noun.endswith("y")
                          and noun[-2] not in "aeiou"):
                        plural = noun[:-1] + "ies"
                    else:
                        plural = noun + "s"
                    if plural != noun:
                        plural_head = tuple(head[:-1] + [plural])
                        variants.add(((prefix[0], "are", "the")
                                      + plural_head + ("of",), suffix))
                for phrase, evidence in (morphology or {}).items():
                    if evidence.get("suffix") == "ing" and phrase in forms:
                        replacements.add(("is",) + phrase)
            for phrase in forms:
                positions = [i for i in range(len(side) - len(phrase) + 1)
                             if phrase and side[i:i + len(phrase)] == phrase]
                if len(positions) != 1:
                    continue
                start = positions[0]
                end = start + len(phrase)
                for replacement in replacements:
                    if (replacement[:2] == ("is", "the")
                            and side[max(0, start - 2):start] == ("is", "the")):
                        continue
                    changed = side[:start] + replacement + side[end:]
                    variants.add((changed, suffix) if side_index == 0
                                 else (prefix, changed))
        # Active/passive voice preserves the same agent/patient relation.
        # Derive a bounded passive "X was created by whom?" from an already
        # licensed active "Who created X?" frame only when the exact verb
        # form is a regular past/participle ending in -ed. This is a role
        # permutation of grounded wording, not a predicate synonym.
        if (not suffix and len(prefix) == 2 and prefix[0] == "who"):
            passive_verbs = {prefix[1]}
            passive_verbs.update(
                phrase[0] for phrase in forms
                if len(phrase) == 1 and phrase[0].endswith("ed"))
            for verb in passive_verbs:
                if len(verb) > 3 and verb.endswith("ed"):
                    variants.add(((), ("was", verb, "by", "whom")))
                    variants.add((("who", "was"), (verb, "by")))
        return variants

    def _is_grounded_progressive_question(
            self, words: tuple[str, ...],
            observed_predicates: Mapping[tuple[str, ...], set[tuple[str, ...]]]
            ) -> bool:
        """Identify a licensed question frame using an induced ``is + -ing`` form."""
        for (relation_repr, answer_field, prefix, suffix), entities in (
                self._question_examples.items()):
            key = (relation_repr, answer_field, prefix, suffix)
            if not self._question_frame_is_licensed(key, entities):
                continue
            relation = tuple(json.loads(relation_repr))
            forms, morphology = self._predicate_forms_for_relation(
                relation, observed_predicates.get(relation, set()))
            if not any(item.get("suffix") == "ing"
                       for item in morphology.values()):
                continue
            for frame_prefix, frame_suffix in self._question_frame_variants(
                    relation, prefix, suffix, forms, morphology):
                if not any(
                        item.get("suffix") == "ing"
                        and any(frame_prefix[index:index + len(phrase) + 1]
                                == ("is",) + phrase
                                for index in range(
                                    len(frame_prefix) - len(phrase)))
                        for phrase, item in morphology.items()):
                    continue
                if (len(words) > len(frame_prefix) + len(frame_suffix)
                        and words[:len(frame_prefix)] == frame_prefix
                        and (not frame_suffix
                             or words[-len(frame_suffix):] == frame_suffix)):
                    return True
        return False

    def teach_fact_pattern_from_hit(
        self, sentence: str, *, subject: str, relation: str, obj: str,
        research_index: Any, hit: Any,
        predicate_phrase: str | None = None,
        polarity: bool = True,
        subject_phrase: str | None = None,
        object_phrase: str | None = None,
    ) -> bool:
        """Train a pattern only from a sentence inside a verified source hit."""
        citation = research_index.citation(hit)
        excerpt = research_index.resolve_citation(citation)
        if sentence not in excerpt:
            raise ValueError("training sentence is not contained in the cited passage")
        return self.teach_fact_pattern(
            sentence, subject=subject, relation=relation, obj=obj,
            source=citation, predicate_phrase=predicate_phrase,
            polarity=polarity, subject_phrase=subject_phrase,
            object_phrase=object_phrase)

    @staticmethod
    def _match_fact_template(
        template: tuple[str, ...], words: tuple[str, ...],
    ) -> list[tuple[tuple[str, ...], tuple[str, ...], int, int, int, int]]:
        """Match literal tokens and two variable spans without guessing splits."""
        matches: set[tuple[tuple[str, ...], tuple[str, ...], int, int, int, int]] = set()

        def visit(pattern_index: int, word_index: int,
                  subject: tuple[tuple[str, ...], int, int] | None,
                  obj: tuple[tuple[str, ...], int, int] | None) -> None:
            if pattern_index == len(template):
                if word_index == len(words) and subject and obj:
                    matches.add((subject[0], obj[0], subject[1], subject[2],
                                 obj[1], obj[2]))
                return
            token = template[pattern_index]
            if token == "<subject>" or token == "<object>":
                for end in range(word_index + 1, len(words) + 1):
                    value = words[word_index:end]
                    visit(pattern_index + 1, end,
                          (value, word_index, end) if token == "<subject>" else subject,
                          (value, word_index, end) if token == "<object>" else obj)
            elif word_index < len(words) and words[word_index] == token:
                visit(pattern_index + 1, word_index + 1, subject, obj)

        visit(0, 0, None, None)
        return sorted(matches)

    def propose_facts(self, sentence: str, *, source: str) -> list[FactCandidate]:
        """Return uncommitted relation candidates from licensed sentence frames."""
        memo: dict[tuple[str, str], tuple[FactCandidate, ...]] = {}
        return self._propose_facts(sentence, source, memo)

    def _discover_surface_relation_candidates(
            self, sentence: str, *, source: str,
            research_index: Any | None = None,
            allow_uninflected: bool = False,
            morphology_rules: Mapping[Any, Any] | None = None,
            bare_predicate_support_cache: dict[str, list[dict[str, str]]]
                | None = None) -> list[FactCandidate]:
        """Suggest simple source claims without a taught relation frame.

        This deliberately narrow discovery pass uses capitalization boundaries
        as provisional entity spans and inflectional/copy forms as a predicate
        cue. Every result is explicitly marked heuristic and remains review
        only. It is a candidate generator, not a natural-language parser.
        """
        sentence = _display(sentence, "sentence")
        source = _display(source, "source")
        if re.match(r"\s*(?:#{1,6}\s+|title\s*:)" , sentence,
                    flags=re.IGNORECASE):
            return []
        words = word_matches(sentence)
        if len(words) > 128:
            return []
        # A narrow copular correction has a mechanically recoverable shape:
        # "Canberra is the capital of Australia, not Sydney." The correction
        # replaces the entity filling the subject slot, so retain the first
        # positive claim and produce a distinct negative claim for review.
        # Preserve common lowercase name particles inside a proper-name span
        # (for example, ``Guido van Rossum``). Without this, nominal predicate
        # frames silently fail on names that other active/passive parsers can
        # already recognize.
        entity = (r"[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
                  r"(?:[A-Z][\w’'-]*|\d{2,}))*")
        nominal = (r"[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,2}")
        nominal_head = (r"[A-Za-z][\w’'-]*(?:\s+[A-Za-z][\w’'-]*){0,2}")

        def parse_one_appositive_core(core: str, aside: str,
                                      position: str) -> list[FactCandidate] | None:
            parsed = self._discover_surface_relation_candidates(
                core, source=source, research_index=research_index,
                allow_uninflected=allow_uninflected,
                morphology_rules=morphology_rules,
                bare_predicate_support_cache=bare_predicate_support_cache)
            if len(parsed) != 1:
                return None
            candidate = parsed[0]
            evidence = tuple({
                **dict(item),
                "underlying_method": item.get("method"),
                "method": "single bounded nominal appositive with unique core parse",
                "removed_appositive": aside,
                "appositive_position": position,
                "parsed_core_sentence": core,
                "review_required": True,
            } for item in candidate.language_evidence)
            return [FactCandidate(
                candidate.subject, candidate.relation, candidate.object,
                source, candidate.template, sentence, candidate.polarity,
                evidence)]

        # A trailing nominal appositive states a relation directly:
        # "Mary Shelley, the author of Frankenstein." Keep it review-only.
        nominal_appositive = re.search(
            rf"(?P<subject>{entity})\s*,\s*(?!and\s|or\s)(?:the\s+)?"
            rf"(?P<head>{nominal_head})\s+of\s+"
            rf"(?P<object>{entity}|(?:(?:the|a|an)\s+"
            rf"[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){{0,3}}|"
            rf"[a-z][\w’'-]+\s+[a-z][\w’'-]*"
            rf"(?:\s+[a-z][\w’'-]*){{0,2}}))\b",
            sentence)
        if nominal_appositive:
            subject = nominal_appositive.group("subject").strip()
            head = " ".join(_tokens(nominal_appositive.group("head")))
            relation = head + " of"
            obj = nominal_appositive.group("object").strip()
            template = f"<subject> {relation} <object>"
            evidence = ({
                "kind": "surface_relation_discovery",
                "method": "bounded nominal appositive relation",
                "review_required": True,
                "template": template,
                "subject": subject,
                "object": obj,
                "predicate_phrase": relation,
                "sources": [source],
                "canonical_relation": relation,
                "warning": ("Subject, nominal relation, and object were read "
                            "from a trailing appositive; verify the complete "
                            "source sentence before accepting."),
            },)
            return [FactCandidate(
                self._canonicalize_entity(subject), relation,
                self._canonicalize_entity(obj), source, template, sentence,
                True, evidence)]

        contrast_patterns = (
            re.compile(
                rf"\s*(?P<subject>{entity})\s+(?:is|was)\s+"
                rf"(?:the\s+)?(?P<head>{nominal})\s+of\s+"
                rf"(?P<object>{entity})\s*,\s*not\s+"
                rf"(?P<alternative>{entity})\s*[.!?]*\s*"),
            re.compile(
                rf"\s*(?:the|a|an)\s+(?P<head>{nominal})\s+of\s+"
                rf"(?P<object>{entity})\s+(?:is|was)\s+"
                rf"(?P<subject>{entity})\s*,\s*not\s+"
                rf"(?P<alternative>{entity})\s*[.!?]*\s*",
                flags=re.IGNORECASE),
        )
        for pattern in contrast_patterns:
            match = pattern.fullmatch(sentence)
            if match is None:
                continue
            relation = " ".join(_tokens(match.group("head"))) + " of"
            subject = match.group("subject").strip()
            obj = match.group("object").strip()
            alternative = match.group("alternative").strip()
            template = f"<subject> {relation} <object>"
            candidates = []
            for candidate_subject, polarity, role in (
                    (subject, True, "asserted subject"),
                    (alternative, False, "corrected-away subject")):
                evidence = ({
                    "kind": "surface_relation_discovery",
                    "method": "copular nominal contrastive correction",
                    "review_required": True,
                    "template": template,
                    "subject": candidate_subject,
                    "object": obj,
                    "predicate_phrase": relation,
                    "sources": [source],
                    "polarity": "positive" if polarity else "negative",
                    "role_analysis": role,
                    "warning": ("The relation slots were parsed from a narrow "
                                "nominal correction pattern; confirm each claim "
                                "against the cited sentence before accepting."),
                },)
                candidates.append(FactCandidate(
                    self._canonicalize_entity(candidate_subject), relation,
                    self._canonicalize_entity(obj), source, template, sentence,
                    polarity, evidence))
            return candidates
        # Preserve the matrix claim around one bounded noun-phrase appositive:
        # "Python, a high-level language, was created by Guido" and
        # "Guido, a programmer, created Python." Only accept a unique parse
        # after removing the descriptive phrase; all facts still require
        # explicit review against the unchanged source sentence.
        middle_appositive = re.fullmatch(
            rf"\s*(?P<before>{entity})\s*,\s*(?:a|an|the)\s+"
            r"(?P<aside>[^,;.!?]{1,160})\s*,\s*"
            r"(?P<after>[^.!?]{1,512}[.!?]*)\s*",
            sentence, flags=re.IGNORECASE)
        if middle_appositive:
            core = (middle_appositive.group("before").strip() + " "
                    + middle_appositive.group("after").strip())
            result = parse_one_appositive_core(
                core, middle_appositive.group("aside").strip(), "between")
            if result is not None:
                return result
        trailing_appositive = re.fullmatch(
            r"\s*(?P<core>[^.!?]{1,512}?)\s*,\s*"
            r"(?:a|an|the)\s+(?P<aside>[^,;.!?]{1,160})[.!?]*\s*",
            sentence, flags=re.IGNORECASE)
        if trailing_appositive:
            core = trailing_appositive.group("core").strip() + "."
            result = parse_one_appositive_core(
                core, trailing_appositive.group("aside").strip(), "trailing")
            if result is not None:
                return result
        # A parenthetical source note can contain commas that are unrelated
        # to the clause structure, as in a corporate name followed by an
        # acronym and URL. Parse the surrounding clause with that aside
        # removed, but retain the exact original sentence for review and
        # citation validation. This only applies to one balanced, bounded
        # parenthetical whose contents include a comma.
        parenthetical = re.search(r"\((?P<aside>[^()]{1,160})\)", sentence)
        if (parenthetical is not None
                and "," in parenthetical.group("aside")):
            core = (sentence[:parenthetical.start()]
                    + sentence[parenthetical.end():])
            parsed = (self._discover_surface_relation_candidates(
                core, source=source, research_index=research_index,
                allow_uninflected=allow_uninflected,
                morphology_rules=morphology_rules,
                bare_predicate_support_cache=bare_predicate_support_cache)
                if core.strip() else [])
            if parsed:
                return [replace(
                    candidate, sentence=sentence,
                    language_evidence=tuple({
                        **dict(item),
                        "underlying_method": item.get("method"),
                        "method": "bounded clause with comma-bearing parenthetical aside",
                        "removed_parenthetical": parenthetical.group("aside"),
                        "review_required": True,
                    } for item in candidate.language_evidence))
                    for candidate in parsed]
        # Also handle a contrastive replacement in the object slot, but only
        # when the affirmative clause independently yields exactly one of the
        # existing bounded surface parses. This reuses its subject and
        # predicate analysis rather than guessing a relation from the suffix.
        object_correction = re.fullmatch(
            rf"\s*(?P<base>[^,;]+),\s*not\s+"
            rf"(?P<alternative>(?:the\s+)?{entity})\s*[.!?]*\s*",
            sentence, flags=re.IGNORECASE)
        if object_correction:
            base_sentence = object_correction.group("base").strip()
            alternative = object_correction.group("alternative").strip()
            affirmative = self._discover_surface_relation_candidates(
                base_sentence, source=source, research_index=research_index,
                allow_uninflected=allow_uninflected,
                morphology_rules=morphology_rules,
                bare_predicate_support_cache=bare_predicate_support_cache)
            if len(affirmative) == 1:
                original = affirmative[0]
                template = original.template
                method = "independently parsed object-slot correction"
                results = []
                for candidate_object, polarity, role in (
                        (original.object, True, "asserted object"),
                        (alternative, False, "corrected-away object")):
                    evidence = ({
                        "kind": "surface_relation_discovery",
                        "method": method,
                        "review_required": True,
                        "template": template,
                        "subject": original.subject,
                        "object": candidate_object,
                        "predicate_phrase": original.relation,
                        "sources": [source],
                        "polarity": "positive" if polarity else "negative",
                        "role_analysis": role,
                        "warning": ("The affirmative clause had one bounded "
                                    "surface parse; confirm that the correction "
                                    "replaces its object slot before accepting."),
                    },)
                    results.append(FactCandidate(
                        original.subject, original.relation,
                        self._canonicalize_entity(candidate_object), source,
                        template, sentence, polarity, evidence))
                return results
        # A comma that is not one of the bounded correction or appositive
        # patterns above may mark a relative clause, coordination, or another
        # attachment. Do not let the capitalized-span heuristic turn it into
        # a predicate or object boundary.
        if "," in sentence or ";" in sentence:
            return []
        negative_class = re.fullmatch(
            r"\s*(?P<subject>[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
            r"[A-Z][\w’'-]*)*)\s+(?i:is|was)\s+not\s+(?i:a|an)\s+"
            r"(?P<object>[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,5})\s*[.!?]*\s*",
            sentence)
        if (negative_class
                and _tokens(negative_class.group("subject"))[:1]
                not in {("it",), ("this",), ("that",), ("these",),
                        ("those",), ("there",), ("none",), ("we",),
                        ("they",), ("you",), ("i",)}):
            subject = negative_class.group("subject").strip()
            object_text = negative_class.group("object").strip()
            object_words = _tokens(object_text)
            forbidden = {"and", "or", "not", "at", "by", "for",
                         "from", "in", "into", "of", "on", "over",
                         "to", "under", "with"}
            if (object_words and not (set(object_words) & forbidden)):
                template = "<subject> is not a <object>"
                evidence = ({
                    "kind": "surface_relation_discovery",
                    "method": "negative copular class-membership pattern",
                    "review_required": True,
                    "template": template,
                    "subject": subject,
                    "object": object_text,
                    "predicate_phrase": "is not a",
                    "sources": [source],
                    "canonical_relation": "is-a",
                    "polarity": "negative",
                    "warning": ("The negative class claim follows an explicit "
                                "copular not-pattern; confirm its scope against "
                                "the cited sentence."),
                },)
                return [FactCandidate(
                    self._canonicalize_entity(subject), "is-a",
                    self._canonicalize_entity(object_text), source, template,
                    sentence, False, evidence)]
        passive_named_entity = (
            r"[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
            r"[A-Z][\w’'-]*)*")
        negative_passive = re.fullmatch(
            rf"\s*(?P<patient>{passive_named_entity})\s+"
            r"(?:(?:has|have|had)\s+been|is|are|was|were)\s+not\s+"
            r"(?P<predicate>[a-z][\w’'-]*(?:ed|en))\s+by\s+"
            rf"(?P<agent>{passive_named_entity})\s*[.!?]*\s*",
            sentence, flags=re.IGNORECASE)
        if negative_passive:
            # Reuse the ordinary bounded passive parser to establish roles and
            # any source-backed predicate alignment. Only polarity is supplied
            # by this exact explicit negation pattern.
            active_surface = (
                f"{negative_passive.group('agent')} "
                f"{negative_passive.group('predicate')} "
                f"{negative_passive.group('patient')}")
            affirmative = self._discover_surface_relation_candidates(
                active_surface, source=source, research_index=research_index,
                allow_uninflected=allow_uninflected,
                morphology_rules=morphology_rules,
                bare_predicate_support_cache=bare_predicate_support_cache)
            if len(affirmative) == 1:
                original = affirmative[0]
                evidence = tuple({
                    **item,
                    "method": "explicit-agent passive negation",
                    "polarity": "negative",
                    "role_analysis": (
                        "agent from by-phrase; patient from passive subject"),
                    "warning": ("The explicit by-phrase determines the agent; "
                                "the passive subject determines the patient. "
                                "Confirm the negative claim against the cited "
                                "sentence before accepting."),
                } for item in original.language_evidence)
                return [FactCandidate(
                    original.subject, original.relation, original.object,
                    source, original.template, sentence, False, evidence)]
        negative_active = re.fullmatch(
            r"\s*(?P<subject>[A-Z][\w’'-]*(?:\s+(?:(?:van|von|de|del|da|di|la|le)\s+)?"
            r"[A-Z][\w’'-]*)*)\s+(?:do|does|did)\s+not\s+"
            r"(?P<relation>[a-z][\w’'-]*)\s+(?P<object>[^.!?,;:]+?)"
            r"\s*[.!?]*\s*", sentence, flags=re.IGNORECASE)
        if negative_active:
            subject = negative_active.group("subject").strip()
            relation = " ".join(_tokens(negative_active.group("relation")))
            object_text = negative_active.group("object").strip()
            surface_object_words = re.findall(
                r"[A-Za-z][\w’'-]*|\d+", object_text)
            if (surface_object_words
                    and surface_object_words[0].casefold() in {"a", "an", "the"}):
                surface_object_words = surface_object_words[1:]
            object_words = _tokens(object_text)
            if object_words and object_words[0] in {"a", "an", "the"}:
                object_text = " ".join(object_words[1:])
                object_words = _tokens(object_text)
            # Without a parser, allow a single common noun or a bounded
            # capitalized name. Lowercase words after a named object often
            # start an adjunct or another clause (“Python yesterday”,
            # “Python because…”); do not absorb them into the fact object.
            name_particles = {"da", "de", "del", "di", "la", "le", "of",
                              "van", "von"}
            object_shape_is_bounded = (
                len(surface_object_words) == 1
                or (1 < len(surface_object_words) <= 6
                    and all(word[:1].isupper()
                            or word.casefold() in name_particles
                            or word.isdigit()
                            for word in surface_object_words)))
            forbidden = {"and", "or", "not", "at", "by", "for",
                         "from", "in", "into", "of", "on", "over",
                         "to", "under", "with"}
            if (relation and 1 <= len(object_words) <= 6
                    and object_shape_is_bounded
                    and not (set(object_words) & forbidden)):
                template = f"<subject> did not {relation} <object>"
                evidence = ({
                    "kind": "surface_relation_discovery",
                    "method": "explicit auxiliary negation pattern",
                    "review_required": True,
                    "template": template,
                    "subject": subject,
                    "object": object_text,
                    "predicate_phrase": relation,
                    "sources": [source],
                    "canonical_relation": relation,
                    "polarity": "negative",
                    "warning": ("The negative claim follows an explicit do/does/did "
                                "not construction; confirm its relation and scope "
                                "against the cited sentence."),
                },)
                return [FactCandidate(
                    self._canonicalize_entity(subject), relation,
                    self._canonicalize_entity(object_text), source, template,
                    sentence, False, evidence)]
        # This zero-frame heuristic has no licensed way to distinguish a
        # negation marker from predicate wording. Never turn an unsupported
        # negative clause into a positive relation such as "is not".
        if (re.search(r"\bnot\b", sentence, flags=re.IGNORECASE)
                or re.search(r",\s*not\s+\S", sentence, flags=re.IGNORECASE)
                or re.search(r"\bnot\s+\S.{0,100}?\bbut\b",
                             sentence, flags=re.IGNORECASE)
                or re.search(r"\b(?:or|whether)\b", sentence,
                             flags=re.IGNORECASE)):
            return []
        # Extract a named entity's explicit copular type even when the
        # sentence continues with a locative or relative clause, e.g. ``The
        # Ogun River is a waterway in Nigeria that ...``. Keep the adjunct
        # outside the type slot and require review because adjective and
        # boundary choices remain heuristic.
        named_type_with_adjunct = re.fullmatch(
            rf"\s*(?P<subject>{entity})\s+(?i:is|was)\s+(?i:a|an)\s+"
            r"(?P<type>[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,2}?)\s+"
            r"(?P<adjunct>(?i:in|at|near|of|on|with|that|which)\b"
            r"[^.!?]*?)\s*[.!?]+\s*",
            sentence)
        if (named_type_with_adjunct
                and not re.match(
                    r"\s*of\b",
                    named_type_with_adjunct.group("adjunct"),
                    flags=re.IGNORECASE)):
            subject_phrase = named_type_with_adjunct.group("subject").strip()
            subject = re.sub(r"^the\s+", "", subject_phrase,
                             flags=re.IGNORECASE)
            object_text = named_type_with_adjunct.group("type").strip()
            subject_tokens = _tokens(subject)
            if (subject_tokens[:1] in {
                    ("he",), ("she",), ("it",), ("they",),
                    ("this",), ("that",)}):
                return []
            template = "<subject> is-a <object>"
            evidence = ({
                "kind": "surface_relation_discovery",
                "method": "bounded named-entity copular type with adjunct",
                "review_required": True,
                "template": template,
                "subject": subject,
                "subject_phrase": subject_phrase,
                "object": object_text,
                "predicate_phrase": "is a",
                "adjunct": named_type_with_adjunct.group("adjunct").strip(),
                "sources": [source],
                "canonical_relation": "is-a",
                "warning": ("The explicit copula provides a reviewable class "
                            "claim; the type/adjective and following adjunct "
                            "boundary were parsed heuristically."),
            },)
            return [FactCandidate(
                self._canonicalize_entity(subject), "is-a",
                self._canonicalize_entity(object_text), source, template,
                sentence, True, evidence)]
        # Accept short common-noun subjects as well as capitalized names in a
        # complete copular classification. This recovers propositions such as
        # "The parser is a tokenizer" without granting general NP parsing:
        # the explicit is/are + a/an construction fixes both slot boundaries.
        common_noun_class = re.fullmatch(
            r"\s*(?P<subject>[A-Za-z][\w’'-]*(?:\s+[A-Za-z][\w’'-]*){0,4})\s+"
            r"(?P<copula>is|are|was|were)\s+(?:a|an)\s+"
            r"(?P<object>[A-Za-z][\w’'-]*(?:\s+[A-Za-z][\w’'-]*){0,4})"
            r"\s*[.!?]\s*", sentence, flags=re.IGNORECASE)
        if common_noun_class:
            subject = common_noun_class.group("subject").strip()
            obj = common_noun_class.group("object").strip()
            subject_words = _tokens(subject)
            object_words = _tokens(obj)
            weak_np_heads = {
                "a", "all", "an", "any", "each", "either", "every",
                "few", "he", "her", "hers", "him", "his", "i", "it",
                "its", "many", "me", "most", "neither", "none", "our",
                "ours", "she", "some", "that", "their", "theirs", "them",
                "these", "they", "this", "those", "there", "us", "we", "you",
                "your", "yours",
            }
            forbidden_np_words = {
                "and", "at", "because", "before", "by", "for", "from",
                "if", "in", "into", "not", "of", "on", "or", "over",
                "since", "through", "to", "toward", "towards", "under",
                "unless", "until", "when", "whereas", "while", "with",
                "without",
            }
            proper_article_subject = (
                len(subject.split()) > 1
                and subject.split()[1][:1].isupper())
            if (subject_words[:1] in {("the",), ("a",), ("an",)}
                    and not proper_article_subject):
                subject_words = subject_words[1:]
                subject = " ".join(subject.split()[1:])
            if (sentence[:1].isupper() and subject_words and object_words
                    and subject_words[0] not in weak_np_heads
                    and not (set(subject_words + object_words)
                             & forbidden_np_words)
                    and tuple(subject_words) != tuple(object_words)):
                template = "<subject> is-a <object>"
                evidence = ({
                    "kind": "surface_relation_discovery",
                    "method": "bounded common-noun copular classification",
                    "review_required": True,
                    "template": template,
                    "subject": subject,
                    "object": obj,
                    "predicate_phrase": common_noun_class.group("copula"),
                    "sources": [source],
                    "canonical_relation": "is-a",
                    "warning": ("Short noun phrases were aligned through an "
                                "explicit copular class clause; verify the "
                                "source supports the classification."),
                },)
                return [FactCandidate(
                    self._canonicalize_entity(subject), "is-a",
                    self._canonicalize_entity(obj), source, template, sentence,
                    True, evidence)]
        # Parse a direct nominal copula such as "Paris is the capital of
        # France." Keep the relation head and its preposition together so
        # reviewed polar questions can match the exact proposition.
        direct_copular_relation = re.fullmatch(
            rf"\s*(?P<subject>{entity})\s+(?i:is|was|are|were)\s+"
            r"(?:(?i:the|a|an)\s+)?"
            r"(?P<relation>[a-z][\w’'-]*(?:\s+[a-z][\w’'-]*){0,3})\s+"
            r"(?P<preposition>(?i:of|in|at|for|to))\s+"
            rf"(?P<object>{entity})\s*[.!?]*\s*",
            sentence)
        if direct_copular_relation:
            subject = direct_copular_relation.group("subject").strip()
            page_title_coreference = None
            if _tokens(subject) in {
                    ("he",), ("she",), ("it",), ("they",),
                    ("this",), ("that",)}:
                title = None
                if research_index is not None and "#" in source:
                    document_id = source.split("#", 1)[0]
                    try:
                        title = research_index.document(document_id).title.strip()
                    except (KeyError, OSError, ValueError):
                        title = None
                # A page title can resolve a sentence-initial demonstrative or
                # pronoun only when the title itself is one bounded named
                # entity. List and descriptive page titles are not antecedents.
                if (title and not title.casefold().startswith(("list of ", "the "))
                        and re.fullmatch(entity, title)):
                    page_title_coreference = {
                        "subject_phrase": subject,
                        "page_title_coreference": {
                            "pronoun": subject,
                            "antecedent": title,
                            "document_id": document_id,
                            "method": "sentence-initial pronoun resolved to exact page title",
                        },
                    }
                    subject = title
                else:
                    return []
            relation = (direct_copular_relation.group("relation").strip()
                        + " " + direct_copular_relation.group(
                            "preposition").casefold())
            obj = direct_copular_relation.group("object").strip()
            template = f"<subject> {relation} <object>"
            evidence = ({
                "kind": "surface_relation_discovery",
                "method": "direct copular nominal relation pattern",
                "review_required": True,
                "template": template,
                "subject": subject,
                "object": obj,
                "predicate_phrase": relation,
                "sources": [source],
                "canonical_relation": relation,
                "warning": ("The subject, relation, and object follow a bounded "
                            "nominal copula; confirm the full source sentence."),
                **(page_title_coreference or {}),
            },)
            return [FactCandidate(
                self._canonicalize_entity(subject), relation,
                self._canonicalize_entity(obj), source, template, sentence,
                True, evidence)]
        # A common relational copula puts the answer before the relation's
        # endpoint: "The capital of France is Paris." Preserve those roles
        # explicitly instead of treating France as the subject of "is".
        copular_relation = re.fullmatch(
            r"\s*(?i:the|a|an)\s+"
            r"(?P<relation>[a-z][\w’'-]*(?:\s+[\w’'-]+){0,3})\s+of\s+"
            rf"(?P<object>{entity})\s+"
            r"(?i:is|was|are|were)\s+"
            rf"(?P<subject>{entity})\s*[.!?]*\s*",
            sentence)
        if copular_relation:
            subject = copular_relation.group("subject").strip()
            relation = copular_relation.group("relation").strip() + " of"
            obj = copular_relation.group("object").strip()
            if subject and obj:
                relation_tokens = tuple(_tokens(relation))
                evidence = ({
                    "kind": "surface_relation_discovery",
                    "method": "copular nominal relation pattern",
                    "review_required": True,
                    "template": "<subject> " + " ".join(relation_tokens)
                                + " <object>",
                    "subject": subject,
                    "object": obj,
                    "predicate_phrase": relation,
                    "sources": [source],
                    "canonical_relation": " ".join(relation_tokens),
                    "warning": ("Role order was mechanically reversed from a "
                                "copular nominal phrase; confirm the cited "
                                "sentence before accepting."),
                },)
                candidate = FactCandidate(
                    self._canonicalize_entity(subject),
                    " ".join(relation_tokens), self._canonicalize_entity(obj),
                    source,
                    "<subject> " + " ".join(relation_tokens) + " <object>",
                    sentence, True, evidence)
                return [candidate]
        # A bounded locative construction such as "Alan Turing worked at
        # Bletchley Park" has explicit subject, predicate, and place slots.
        # Keep the preposition in the surface relation so the reviewed fact
        # does not erase the role it carries.
        locative = re.fullmatch(
            rf"\s*(?P<subject>{entity})\s+"
            r"(?P<predicate>[a-z][\w’'-]*(?:ed|en|s|ing))\s+"
            r"(?P<preposition>(?i:at|in|near))\s+"
            rf"(?P<object>{entity})\s*[.!?]*\s*",
            sentence)
        if locative:
            subject = locative.group("subject").strip()
            predicate = locative.group("predicate").strip()
            preposition = locative.group("preposition").casefold()
            obj = locative.group("object").strip()
            relation = " ".join(_tokens(predicate + " " + preposition))
            template = f"<subject> {relation} <object>"
            evidence = ({
                "kind": "surface_relation_discovery",
                "method": "named entities with finite verb and locative preposition",
                "review_required": True,
                "template": template,
                "subject": subject,
                "object": obj,
                "predicate_phrase": predicate + " " + preposition,
                "sources": [source],
                "canonical_relation": relation,
                "warning": ("The entity spans and locative relation are a narrow "
                            "surface parse; confirm that the place fills the "
                            "intended relation slot before accepting."),
            },)
            return [FactCandidate(
                self._canonicalize_entity(subject), relation,
                self._canonicalize_entity(obj), source, template,
                sentence, True, evidence)]
        spans = list(re.finditer(
            r"(?<![\w])(?:[A-Z][\w’'-]*)"
            r"(?:\s+(?:(?:(?:van|von|de|del|da|di|la|le)\s+)?"
            r"[A-Z][\w’'-]*|\d{2,}))*",
            sentence))
        if not spans:
            return []
        weak_initials = {
            "a", "all", "an", "another", "any", "because", "before",
            "both", "by", "during", "each", "few", "first", "given",
            "here", "if", "in", "it", "last", "lived", "many", "most",
            "neither", "next", "none", "other", "our", "second", "several",
            "since", "some", "sometimes", "such", "that", "the", "their",
            "then", "there", "these",
            "they", "third", "this", "though", "those", "through", "to",
            "unless", "until", "when", "whereas", "while", "with",
            "without", "we",
        }
        first_span_tokens = _tokens(spans[0].group())
        if (first_span_tokens[:1] in {
                (word,) for word in weak_initials}
                and not (first_span_tokens[:1] == ("the",)
                         and len(first_span_tokens) > 1)):
            return []
        if re.match(r"\s*[A-Z]\s+(?:is|are|was|were)\b", sentence):
            return []
        candidates: dict[tuple[str, str, str], FactCandidate] = {}
        copulas = {"am", "are", "be", "been", "being", "is", "was", "were"}
        if morphology_rules is None:
            morphology_rules = (self._licensed_predicate_spelling_rules()
                                if research_index is not None else {})
        if len(spans) == 1:
            # A common noun object is not capitalized, so it is absent from
            # the entity-span scan. Recover only the narrow form
            # "Named Subject inflected-verb object" and keep it review-only.
            name = spans[0]
            leading = len(sentence) - len(sentence.lstrip())
            subject = name.group().strip()
            tail = sentence[name.end():].strip()
            type_match = re.fullmatch(
                r"(?:is|was)\s+(?:a|an)\s+"
                r"(?P<object>[^.!?,;:]+?)\s*[.!?]*\s*", tail,
                flags=re.IGNORECASE)
            if (name.start() == leading
                    and _tokens(subject) not in {("the",), ("a",), ("an",)}
                    and type_match is not None):
                object_text = type_match.group("object").strip()
                object_words = _tokens(object_text)
                forbidden = {"and", "or", "not", "at", "by", "for",
                             "from", "in", "into", "of", "on", "over",
                             "to", "under", "with"}
                if (1 <= len(object_words) <= 6
                        and not (set(object_words) & forbidden)):
                    template = "<subject> is a <object>"
                    evidence = ({
                        "kind": "surface_relation_discovery",
                        "method": "copular class-membership pattern",
                        "review_required": True,
                        "template": template,
                        "subject": subject,
                        "object": object_text,
                        "predicate_phrase": "is a",
                        "sources": [source],
                        "canonical_relation": "is-a",
                        "warning": ("The subject/class roles follow a narrow "
                                    "copular pattern; confirm the classification "
                                    "against the cited sentence."),
                    },)
                    candidate = FactCandidate(
                        self._canonicalize_entity(subject), "is-a",
                        self._canonicalize_entity(object_text), source,
                        template, sentence, True, evidence)
                    return [candidate]
            match = re.fullmatch(
                r"(?P<predicate>[A-Za-z][\w’'-]*)\s+"
                r"(?P<object>[^.!?,;:]+?)\s*[.!?]*\s*", tail)
            if (name.start() == leading
                    and _tokens(subject) not in {("the",), ("a",), ("an",)}
                    and match is not None):
                predicate = match.group("predicate")
                predicate_key = _tokens(predicate)
                object_text = match.group("object").strip()
                object_words = _tokens(object_text)
                if object_words and object_words[0] in {"a", "an", "the"}:
                    object_text = " ".join(object_words[1:])
                    object_words = _tokens(object_text)
                forbidden = {"and", "or", "not", "at", "by", "for",
                             "from", "in", "into", "of", "on", "over",
                             "to", "under", "with"}
                if (len(predicate_key) == 1
                        and predicate_key[0] not in copulas
                        and predicate_key[0].endswith(("ed", "s"))
                        and 1 <= len(object_words) <= 6
                        and not (set(object_words) & forbidden)):
                    relation = " ".join(predicate_key)
                    template = f"<subject> {relation} <object>"
                    evidence = ({
                        "kind": "surface_relation_discovery",
                        "method": "named-subject and lowercase-object pattern",
                        "review_required": True,
                        "template": template,
                        "subject": subject,
                        "object": object_text,
                        "predicate_phrase": predicate,
                        "sources": [source],
                        "canonical_relation": relation,
                        "warning": ("The lowercase object boundary follows a "
                                    "single finite predicate; confirm the exact "
                                    "relation against the cited sentence."),
                    },)
                    candidate = FactCandidate(
                        self._canonicalize_entity(subject), relation,
                        self._canonicalize_entity(object_text), source,
                        template, sentence, True, evidence)
                    return [candidate]
            return []
        for left, right in zip(spans, spans[1:]):
            if (left is not spans[0]
                    and re.search(r"\b(?:a|an|the)\s+$",
                                  sentence[:left.start()],
                                  flags=re.IGNORECASE)):
                # A capitalized common noun following a determiner is usually
                # an object/complement ("an EP called ...", "for the TV
                # series ..."), not a new named subject.
                continue
            subject = left.group().strip()
            object_start = right.start()
            determiner = re.search(r"\b(?:a|an|the)\s+$",
                                   sentence[left.end():right.start()],
                                   flags=re.IGNORECASE)
            if determiner:
                object_start = left.end() + determiner.start()
            relation = sentence[left.end():object_start].strip(" ,;:-")
            passive = re.fullmatch(
                r"(?:(?:has|have|had)\s+been|is|are|was|were|be|being)\s+"
                r"(?P<predicate>[a-z][\w’'-]*(?:ed|en))"
                r"(?:\s+(?:at|in|on|during)\s+"
                r"(?P<adjunct>[^,;.!?]{1,60}?))?\s+by",
                relation, flags=re.IGNORECASE)
            if (passive is not None and passive.group("adjunct") is not None
                    and re.search(
                        r"\b(?:not|never|but|and|or|although|unless|instead|rather)\b",
                        passive.group("adjunct"), flags=re.IGNORECASE)):
                passive = None
            if passive is not None:
                # The explicit by-phrase identifies the agent. Reorder the
                # slots into the same subject-relation-object structure as
                # active clauses; do not invent a relation meaning.
                subject = right.group().strip()
                obj = left.group().strip()
                relation = passive.group("predicate")
            else:
                # The capitalization scan finds proper-name heads, not the
                # end of their noun phrase. Extend through lowercase head
                # words ("C language", "Turing machine"), but stop before a
                # prepositional attachment such as "at Bell Labs". These
                # proposals remain review-only.
                object_tail = sentence[object_start:].strip()
                boundary = re.search(
                    r"\b(?:at|by|for|from|in|into|of|on|over|to|under|with)\b",
                    object_tail, flags=re.IGNORECASE)
                if boundary:
                    object_tail = object_tail[:boundary.start()].rstrip()
                obj = object_tail.rstrip(".!? ")
            predicate_tokens = [match.group().casefold()
                                for match in word_matches(relation)]
            if not relation or not predicate_tokens:
                continue
            if predicate_tokens[-1] in {
                    "at", "by", "for", "from", "in", "into", "of",
                    "on", "over", "to", "under", "with"}:
                # A predicate span ending in a preposition commonly means
                # that a lowercase object or modifier was swallowed before
                # the next capitalized entity ("discovered radium in France").
                # The nominal "X of Y" order has its own explicit parser.
                continue
            # Without an explicit agent ("by X"), a passive clause does not
            # identify who performed the action. Do not turn an adjacent
            # capitalized location into a positive agent/object fact.
            if ("by" not in predicate_tokens
                    and re.search(
                        r"\b(?:is|are|was|were|been|being)\s+"
                        r"\w+(?:ed|en)\b", relation, re.IGNORECASE)):
                continue
            # Keep the hypothesis space focused on likely finite predicates;
            # do not turn location/preposition links into relation claims.
            if (passive is None
                    and not any(token in copulas
                                or token.endswith(("ed", "ing", "s"))
                                for token in predicate_tokens)
                    and (not allow_uninflected
                         or set(predicate_tokens) <= {
                             "a", "an", "and", "at", "by", "for", "from",
                             "in", "of", "on", "or", "the", "to", "with"})):
                continue
            if (not subject or not obj or len(_tokens(relation)) > 7
                    or subject.casefold() == obj.casefold()):
                continue
            surface_relation_text = relation.strip()
            surface_relation = tuple(_tokens(surface_relation_text))
            canonical_options: dict[tuple[str, ...], dict[str, Any]] = {}
            if research_index is not None:
                for ((rule_frame, index, rule_context, rule_removed, ending),
                     supported) in morphology_rules.items():
                    if (len(rule_frame) != len(surface_relation)
                            or index >= len(surface_relation)
                            or any(token != "<predicate>"
                                   and token != surface_relation[i]
                                   for i, token in enumerate(rule_frame))):
                        continue
                    surface_word = surface_relation[index]
                    # Invert only a spelling change already supported by
                    # varied, source-backed relation families. Enumerate
                    # bounded candidates, then use
                    # corpus contexts to resolve homographic stems.
                    candidate_bases = set()
                    for prefix_end in range(max(2, len(surface_word) - 5),
                                            len(surface_word)):
                        prefix = surface_word[:prefix_end]
                        for restoration in ("", "e", "y", "ie", "c"):
                            base_word = prefix + restoration
                            if len(base_word) < 2 or base_word == surface_word:
                                continue
                            if _analyze_predicate_spelling(
                                    base_word, surface_word) == (
                                        rule_context, rule_removed, ending):
                                candidate_bases.add(base_word)
                    for base_word in candidate_bases:
                        base_relation = list(surface_relation)
                        base_relation[index] = base_word
                        base_key = tuple(base_relation)
                        lexical_support = (
                            bare_predicate_support_cache.get(base_word)
                            if bare_predicate_support_cache is not None else None)
                        if lexical_support is None:
                            lexical_support = self._corpus_bare_predicate_support(
                                research_index, base_word)
                            if bare_predicate_support_cache is not None:
                                bare_predicate_support_cache[base_word] = lexical_support
                        if len({item["document_id"] for item in lexical_support}) < 2:
                            continue
                        rule_sources = set()
                        for support in supported.values():
                            rule_sources.update(support.get("sources", ()))
                        canonical_options[base_key] = {
                            "kind": "licensed_predicate_spelling",
                            "canonical_form": " ".join(base_key),
                            "surface_form": " ".join(surface_relation),
                            "rule": {"context": rule_context,
                                     "removed": rule_removed, "ending": ending,
                                     "relation_pattern": list(rule_frame)},
                            "rule_sources": sorted(rule_sources),
                            "lexical_support": lexical_support,
                        }
            canonical_relation = (next(iter(canonical_options))
                                  if len(canonical_options) == 1
                                  else surface_relation)
            spelling_evidence = (next(iter(canonical_options.values()))
                                 if len(canonical_options) == 1 else None)
            # Keep the exact predicate spelling for review and realization
            # unless an independently licensed morphology rule selected a
            # canonical relation. Token-level matching still treats hyphens
            # as boundaries, so "co-created" aligns with "co create".
            canonical_relation_text = (
                " ".join(canonical_relation) if spelling_evidence is not None
                else surface_relation_text)
            subject_is_article_led = bool(re.match(
                r"\s*(?:the|a|an)\s+", subject, flags=re.IGNORECASE))
            object_words = obj.split()
            object_is_name_shaped = (
                2 <= len(object_words) <= 4
                and object_words[0].casefold() not in {"the", "a", "an"}
                and all(word[:1].isupper() for word in object_words))
            possible_role_reversal = (
                passive is None and subject_is_article_led
                and object_is_name_shaped)
            evidence = ({
                "kind": "surface_relation_discovery",
                "method": ("passive by-phrase role normalization"
                           if passive is not None else
                           "capitalized-span plus predicate-morphology heuristic"),
                "review_required": True,
                "template": "<subject> " + surface_relation_text
                            + " <object>",
                "subject": subject,
                "object": obj,
                "predicate_phrase": relation,
                "sources": [source],
                "canonical_relation": canonical_relation_text,
                "morphology_support": spelling_evidence,
                **({"role_direction_suspicion":
                    "article-led subject with a multiword proper-name object",
                    "warning": ("This active clause has an article-led subject "
                                "and a multiword proper-name object; check whether "
                                "the roles are reversed before accepting.")}
                   if possible_role_reversal else
                   {"warning": ("Entity boundaries and predicate role are "
                                "heuristic; confirm the cited sentence before "
                                "accepting.")}),
            },)
            candidate = FactCandidate(
                self._canonicalize_entity(subject),
                canonical_relation_text,
                self._canonicalize_entity(obj), source,
                "<subject> " + canonical_relation_text + " <object>",
                sentence, True, evidence)
            candidates[(candidate.subject.casefold(), candidate.relation,
                        candidate.object.casefold())] = candidate
        return [candidates[key] for key in sorted(candidates)]

    @staticmethod
    def _corpus_bare_predicate_support(
            research_index: Any, base: str, *, limit: int = 40
            ) -> list[dict[str, str]]:
        """Find cited corpus uses of a base verb after a mechanical cue."""
        cues = {"can", "could", "did", "do", "does", "may", "might",
                "must", "should", "to", "will", "would"}
        try:
            hits = research_index.search(base, limit=limit)
        except (AttributeError, TypeError, ValueError):
            return []
        support: dict[str, dict[str, str]] = {}
        target = _tokens(base)
        for hit in hits:
            words = tuple(_tokens(hit.snippet))
            if len(target) != 1:
                continue
            if not any(words[index:index + len(target)] == target
                       and bool(set(words[max(0, index - 3):index]) & cues)
                       for index in range(len(words) - len(target) + 1)):
                continue
            support[hit.document_id] = {
                "document_id": hit.document_id,
                "citation": research_index.citation(hit),
            }
        return [support[key] for key in sorted(support)]

    def propose_corpus_relation_frames(
            self, research_index: Any, *, minimum_examples: int = 2,
            maximum_documents: int = 1000, maximum_sentences: int = 20_000,
            maximum_proposals: int = 100,
            document_offset: int = 0) -> list[dict[str, Any]]:
        """Find repeated source-grounded relation frames without prior teaching.

        Discovery is deliberately report-only. It groups narrow heuristic
        sentence parses only when they share a compatible predicate/argument
        template and have distinct subjects, objects, and source documents.
        Bounded lowercase-object parses and passive forms require additional
        guards below; these proposals are not proof that a source entails the
        claims, and acceptance remains explicit.
        """
        if (type(minimum_examples) is not int or not 2 <= minimum_examples <= 20
                or type(maximum_documents) is not int
                or not 1 <= maximum_documents <= 10_000
                or type(maximum_sentences) is not int
                or not 1 <= maximum_sentences <= 1_000_000
                or type(maximum_proposals) is not int
                or not 1 <= maximum_proposals <= 1000
                or type(document_offset) is not int
                or not 0 <= document_offset <= 1_000_000):
            raise ValueError("corpus frame discovery bounds are outside supported limits")
        source_rows = research_index.source_list(
            limit=maximum_documents, offset=document_offset)
        grouped: dict[tuple[Any, ...],
                      dict[tuple[Any, ...], list[dict[str, Any]]]] = {}
        morphology_rules = self._licensed_predicate_spelling_rules()
        bare_support_cache: dict[str, list[dict[str, str]]] = {}
        processed_sentences = 0
        for source_row in source_rows:
            document = research_index.document(source_row[0])
            if _is_code_source(document.location):
                continue
            text = document.text
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            for sentence_start, sentence_end in _sentence_spans(text):
                if processed_sentences >= maximum_sentences:
                    break
                sentence = text[sentence_start:sentence_end].strip()
                if (not sentence or len(sentence) > 8192
                        or len(word_matches(sentence)) > 128):
                    continue
                processed_sentences += 1
                start, end = sentence_start, sentence_end
                if (_sentence_context_kind(sentence, text, start)
                        != "assertion"):
                    continue
                # Truncated extraction windows and title/list fragments can
                # produce convincing-looking slot splits while lacking a full
                # claim. Keep corpus rule discovery to bounded complete
                # sentences. Until corpus mining has a clause-boundary parser,
                # skip comma/semicolon sentences unless the extractor marks a
                # uniquely bounded appositive parse. Source audits found
                # discourse openings and loose appositives being mistaken for
                # relation slots (e.g. "Finally, the quality of ..."). The
                # original text remains untouched in storage and remains
                # available to ordinary retrieval and explicit extraction.
                if sentence[-1:] not in {".", "!", "?"}:
                    continue
                page_number = None
                page_offset = 0
                for page_index, page in enumerate(document.pages, start=1):
                    if page_offset <= start < page_offset + len(page):
                        page_number = page_index
                        break
                    page_offset += len(page) + len("\n\f\n")
                citation = (f"{document.document_id}#sha256={digest}"
                            f"&chars={start}:{end}")
                if page_number is not None:
                    citation += (f"&page={page_number}"
                                 f"&match={start}:{end}")
                candidates = self._discover_surface_relation_candidates(
                        sentence, source=citation,
                        research_index=research_index,
                        morphology_rules=morphology_rules,
                        bare_predicate_support_cache=bare_support_cache)
                for candidate in candidates:
                    relation_tokens_for_review = _tokens(candidate.relation)
                    evidence = next((item for item in candidate.language_evidence
                                     if item.get("kind")
                                     == "surface_relation_discovery"), {})
                    # A page title is not enough to license a reusable
                    # relation frame for a sentence whose grammatical subject
                    # is only a pronoun. The title can identify a likely
                    # entity for retrieval, but it does not prove that the
                    # pronoun refers to that entity in this sentence. Keep
                    # these claims searchable and available for human review;
                    # do not generalize their predicate/argument pattern.
                    if evidence.get("page_title_coreference"):
                        continue
                    method = str(evidence.get("method", ""))
                    relation_words_for_review = (
                        _RESEARCH_STOPWORDS
                        | {"he", "her", "hers", "him", "his", "its",
                           "me", "my", "our", "ours", "she", "them",
                           "their", "theirs", "they", "us", "we", "you",
                           "your", "yours"})
                    numeric_subject = re.match(
                        r"\s*(?:\d+|zero|one|two|three|four|five|six|seven|"
                        r"eight|nine|ten|eleven|twelve|thirteen|fourteen|"
                        r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b",
                        candidate.subject, flags=re.IGNORECASE)
                    object_tokens_for_boundary = _tokens(candidate.object)
                    sentence_tokens_for_boundary = _tokens(sentence)
                    object_is_complete = bool(
                        object_tokens_for_boundary
                        and len(sentence_tokens_for_boundary)
                            >= len(object_tokens_for_boundary)
                        and sentence_tokens_for_boundary[
                            -len(object_tokens_for_boundary):]
                            == object_tokens_for_boundary)
                    if not object_is_complete:
                        # A narrow nominal complement is part of the object
                        # phrase ("Supreme Commander of NATO Europe"). Extend
                        # only a source-matched `of ...` tail; other trailing
                        # material remains a boundary error until parsed.
                        object_match = re.search(
                            re.escape(candidate.object), sentence,
                            flags=re.IGNORECASE)
                        if object_match is not None:
                            tail = sentence[object_match.end():].rstrip(" .!?;:")
                            if (re.match(r"^\s+of\s+\S", tail, re.IGNORECASE)
                                    and len(_tokens(tail)) <= 6
                                    and not re.search(r"\b(?:and|or|but)\b",
                                                      tail, re.IGNORECASE)):
                                expanded_object = (
                                    candidate.object + tail[0:]
                                    if tail.startswith(" ") else
                                    candidate.object + " " + tail)
                                expanded_evidence = tuple({
                                    **item,
                                    "object": expanded_object,
                                    "object_phrase": expanded_object,
                                } for item in candidate.language_evidence)
                                candidate = replace(
                                    candidate, object=expanded_object,
                                    language_evidence=expanded_evidence)
                                object_tokens_for_boundary = _tokens(
                                    candidate.object)
                                sentence_tokens_for_boundary = _tokens(sentence)
                                object_is_complete = bool(
                                    object_tokens_for_boundary
                                    and len(sentence_tokens_for_boundary)
                                        >= len(object_tokens_for_boundary)
                                    and sentence_tokens_for_boundary[
                                        -len(object_tokens_for_boundary):]
                                        == object_tokens_for_boundary)
                    relation_has_determiner = bool(
                        set(relation_tokens_for_review) & {"a", "an", "the"})
                    object_starts_boundary = bool(
                        _tokens(candidate.object)
                        and _tokens(candidate.object)[0] in {
                            "is", "are", "was", "were", "has", "have",
                            "had", "do", "does", "did", "in", "at",
                            "on", "into", "onto", "through", "across",
                            "along", "from", "to", "with", "by", "over",
                            "under", "near", "beside", "within", "without",
                        })
                    subject_match = re.search(
                        rf"(?<!\w){re.escape(candidate.subject)}(?!\w)",
                        sentence, flags=re.IGNORECASE)
                    subject_is_prep_complement = False
                    if subject_match is not None:
                        before_subject = sentence[:subject_match.start()].rstrip()
                        subject_is_prep_complement = bool(re.search(
                            r"\b(?:of|in|at|on|from|near|within|inside|outside|"
                            r"behind|for|with|by)\s+"
                            r"(?:(?:the|a|an)\s+)?$",
                            before_subject, flags=re.IGNORECASE))
                    if (candidate.relation != "is-a"
                            and (not re.fullmatch(
                                r"[A-Za-z][A-Za-z’'-]*(?:\s+[A-Za-z][A-Za-z’'-]*){0,3}",
                                candidate.relation)
                                or numeric_subject is not None
                                or relation_has_determiner
                                or object_starts_boundary
                                or subject_is_prep_complement
                                or not object_is_complete
                                or (relation_tokens_for_review
                                    and set(relation_tokens_for_review)
                                    <= relation_words_for_review)
                                or "versus" in relation_tokens_for_review
                                or (relation_tokens_for_review[-1].endswith("ing")
                                    and not set(relation_tokens_for_review)
                                    & {"is", "are", "was", "were", "be",
                                       "been", "being", "has", "have", "had"}))):
                        continue
                    # Corpus frame mining cannot safely resolve event-list
                    # prefixes, quoted titles, noun-as-verb boundary errors,
                    # or passive-agent role reversal yet. Keep those source
                    # sentences searchable and available to explicit review,
                    # but do not let their shapes become reusable rules.
                    if (re.match(r"\s*(?:\d{1,4}\s*[–—-]|[\"'‘“])", sentence)
                            or (method == "passive by-phrase role normalization"
                                and not evidence.get("morphology_support"))
                            or "that" in relation_tokens_for_review
                            or set(relation_tokens_for_review) <= {
                                "across", "along", "among", "around", "at",
                                "behind", "below", "beside", "between", "beyond",
                                "by", "despite", "during", "for", "from", "in",
                                "inside", "into", "near", "of", "off", "on",
                                "onto", "over", "through", "to", "under", "until",
                                "upon", "with", "within", "without", "such", "as",
                                "versus", "vs", "years",
                            }):
                        continue
                    subject_tokens = _tokens(candidate.subject)
                    object_tokens = _tokens(candidate.object)
                    generic_pronouns = {
                        "i", "me", "my", "we", "us", "our", "you",
                        "your", "he", "him", "his", "she", "her",
                        "it", "they", "them", "their", "there",
                        "this", "that", "these", "those",
                    }
                    if (not subject_tokens or not object_tokens
                            or any(token in generic_pronouns
                                   for token in subject_tokens)
                            or any(token in generic_pronouns
                                   for token in object_tokens)
                            or len(object_tokens) > 8
                            or re.search(r"\b(?:and|or)\b", sentence,
                                         flags=re.IGNORECASE)
                            or (candidate.relation in {
                                "connect", "connects", "connected", "link",
                                "links", "linked", "join", "joins", "joined",
                            } and re.search(r"\bwith\b", sentence,
                                            flags=re.IGNORECASE))):
                        continue
                    if candidate.relation == "is-a":
                        # Copular type frames are especially vulnerable to
                        # pronoun subjects, existential "there is" clauses,
                        # dangling example complements, and coordinated
                        # predicates whose second class was parsed as an
                        # adjunct. Keep those sentences available for normal
                        # retrieval, but do not turn them into learned frames.
                        if (subject_tokens[0] in {
                                "finally", "however", "militarily", "therefore",
                                "currently", "generally", "usually", "also",
                                "moreover", "instead", "consequently",
                            }
                                or any(token in {"who", "which", "that"}
                                       for token in object_tokens)
                                or object_tokens[-1:] in {
                                    ("located",), ("based",), ("called",),
                                    ("known",), ("named",), ("described",),
                                    ("considered",), ("used",),
                                }
                                or re.match(r"\s*there\s+(?:is|are|was|were)\b",
                                            sentence, flags=re.IGNORECASE)
                                or re.search(r"\b(?:and|or)\b", sentence,
                                             flags=re.IGNORECASE)
                                or object_tokens[-1:] in {("example",), ("examples",)}):
                            continue
                    if (("," in sentence or ";" in sentence)
                            and evidence.get("method")
                            != "single bounded nominal appositive with unique core parse"):
                        continue
                    surface_phrase = str(evidence.get(
                        "predicate_phrase", candidate.relation))
                    key = (_tokens(candidate.relation),
                           tuple(("<subject>",) + _tokens(candidate.relation)
                                 + ("<object>",)),
                           candidate.polarity)
                    pair = (_tokens(candidate.subject), _tokens(candidate.object))
                    row = {
                        "subject": candidate.subject,
                        "relation": candidate.relation,
                        "object": candidate.object,
                        "predicate_phrase": surface_phrase,
                        "morphology_support": evidence.get("morphology_support"),
                        "sentence": sentence,
                        "source": citation,
                        "document_id": document.document_id,
                        "polarity": candidate.polarity,
                    }
                    pair_rows = grouped.setdefault(key, {}).setdefault(pair, [])
                    # Keep a small, deterministic set of independent source
                    # rows for each exact pair. The alignment miner needs to
                    # choose different documents on both sides; retaining
                    # only the first occurrence can hide that evidence when
                    # it happens to be in a document containing both forms.
                    if (len(pair_rows) < 8
                            and all(existing["document_id"]
                                    != document.document_id
                                    for existing in pair_rows)):
                        pair_rows.append(row)
            if processed_sentences >= maximum_sentences:
                break

        proposals: list[dict[str, Any]] = []
        for (relation_tokens, template, polarity), rows in sorted(grouped.items()):
            support = [row for pair in sorted(rows)
                       for row in sorted(rows[pair],
                                         key=lambda item: item["document_id"])]
            subjects = {_tokens(row["subject"]) for row in support}
            objects = {_tokens(row["object"]) for row in support}
            documents = {row["document_id"] for row in support}
            if (len(rows) < minimum_examples
                    or len(subjects) < minimum_examples
                    or len(objects) < minimum_examples
                    or len(documents) < minimum_examples):
                continue
            payload = {
                "relation": support[0]["relation"],
                "template": list(template),
                "polarity": polarity,
                "support": support,
                "distinct_subjects": len(subjects),
                "distinct_objects": len(objects),
                "independent_documents": len(documents),
                "processed_sentences": processed_sentences,
                "review_required": True,
            }
            proposal_id = hashlib.sha256(json.dumps(
                payload, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
            proposals.append({"proposal_id": proposal_id, **payload})
        proposals.sort(key=lambda item: (
            item["relation"], tuple(item["template"]), item["proposal_id"]))
        return proposals[:maximum_proposals]

    def accept_corpus_relation_frame(
            self, proposal_id: str, research_index: Any, *,
            minimum_examples: int = 2, maximum_documents: int = 1000,
            maximum_sentences: int = 20_000, maximum_proposals: int = 100,
            document_offset: int = 0) -> dict[str, Any]:
        """Accept a fresh corpus-frame proposal and its explicitly reviewed examples."""
        if not isinstance(proposal_id, str) or not re.fullmatch(
                r"[0-9a-f]{24}", proposal_id):
            raise ValueError("corpus-frame proposal id is malformed")
        proposal = next((item for item in self.propose_corpus_relation_frames(
            research_index, minimum_examples=minimum_examples,
            maximum_documents=maximum_documents,
            maximum_sentences=maximum_sentences,
            maximum_proposals=maximum_proposals,
            document_offset=document_offset)
            if item["proposal_id"] == proposal_id), None)
        if proposal is None:
            raise ValueError("corpus-frame proposal is stale or unsupported")

        staged = copy.deepcopy(self)
        validated: list[FactCandidate] = []
        morphology_rules = staged._licensed_predicate_spelling_rules()
        bare_support_cache: dict[str, list[dict[str, str]]] = {}
        for row in proposal["support"]:
            excerpt = research_index.resolve_citation(row["source"])
            if row["sentence"] not in excerpt:
                raise ValueError("corpus-frame evidence no longer matches its citation")
            parses = staged._discover_surface_relation_candidates(
                row["sentence"], source=row["source"],
                research_index=research_index,
                morphology_rules=morphology_rules,
                bare_predicate_support_cache=bare_support_cache)
            matches = [candidate for candidate in parses
                       if (_tokens(candidate.subject) == _tokens(row["subject"])
                           and candidate.relation == row["relation"]
                           and _tokens(candidate.object) == _tokens(row["object"])
                           and _tokens(next((str(item["predicate_phrase"])
                                             for item in candidate.language_evidence
                                             if item.get("kind")
                                             == "surface_relation_discovery"), ""))
                               == _tokens(row["predicate_phrase"]))]
            if len(matches) != 1:
                raise ValueError("corpus-frame example no longer has a unique parse")
            validated.append(matches[0])
        if len(validated) < 2:
            raise ValueError("corpus-frame proposal lost varied source support")

        for candidate in validated:
            staged.accept_fact_candidate(candidate, research_index)
        self.__dict__.clear()
        self.__dict__.update(staged.__dict__)
        return proposal

    @staticmethod
    def _structured_field_spans(text: str) -> list[tuple[str, str, int, int]]:
        """Return supported exact infobox key/value lines and their spans."""
        rows = []
        offset = 0
        in_infobox = False
        assignment = re.compile(r"^[ \t]*([\w -]{1,48})[ \t]*=[ \t]*(.*)$")
        for line in text.splitlines(keepends=True):
            content = line.rstrip("\r\n")
            if not in_infobox:
                in_infobox = bool(re.match(r"^[ \t]*Infobox\b", content, re.I))
                offset += len(line)
                continue
            match = assignment.match(content)
            if match is not None:
                field = " ".join(match.group(1).casefold().split())
                if field in _STRUCTURED_PREDICATE_FIELDS:
                    leading = len(content) - len(content.lstrip())
                    rows.append((field, match.group(2).strip(),
                                 offset + leading, offset + len(content)))
            offset += len(line)
        return rows

    def _propose_structured_predicate_alignments(
            self, research_index: Any, *, minimum_pairs: int,
            maximum_documents: int, maximum_sentences: int,
            maximum_proposals: int, document_offset: int
            ) -> list[dict[str, Any]]:
        """Use explicit infobox fields as labels for matching prose frames.

        A proposal needs at least two training pairs and one held-out pair.
        For each page, the field value and a complete sentence must identify
        the same exact subject/object pair; the sentence's predicate may then
        differ from the field's canonical relation. This remains review-only.
        """
        grouped: dict[tuple[str, str], dict[
            tuple[tuple[str, ...], tuple[str, ...]], dict[str, dict[str, Any]]]] = {}
        processed_sentences = 0
        morphology_rules = self._licensed_predicate_spelling_rules()
        source_rows = research_index.source_list(
            limit=maximum_documents, offset=document_offset)
        for source_row in source_rows:
            document = research_index.document(source_row[0])
            if _is_code_source(document.location):
                continue
            field_spans = self._structured_field_spans(document.text)
            if not field_spans:
                continue
            digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
            title_tokens = _tokens(document.title)
            if not title_tokens:
                continue
            for start, end in _sentence_spans(document.text):
                if processed_sentences >= maximum_sentences:
                    break
                sentence = document.text[start:end].strip()
                if not sentence or sentence[-1:] not in {".", "!", "?"}:
                    continue
                processed_sentences += 1
                lower_sentence = sentence.casefold()
                if document.title.casefold() not in lower_sentence:
                    continue
                for field, value, field_start, field_end in field_spans:
                    value = value.strip()
                    if (not value or len(value) > 100
                            or value.casefold() in {"unknown", "none", "n/a"}
                            or value.casefold() not in lower_sentence):
                        continue
                    canonical_relation, title_role = (
                        _STRUCTURED_PREDICATE_FIELDS[field])
                    subject = (document.title if title_role == "subject"
                               else value)
                    obj = (document.title if title_role == "object"
                           else value)
                    sentence_start, sentence_end = start, end
                    field_citation = (f"{document.document_id}#sha256={digest}"
                                      f"&chars={field_start}:{field_end}")
                    sentence_citation = (f"{document.document_id}#sha256={digest}"
                                         f"&chars={sentence_start}:{sentence_end}")
                    candidates = self._discover_surface_relation_candidates(
                        sentence, source=sentence_citation,
                        research_index=research_index,
                        morphology_rules=morphology_rules)
                    matches = [candidate for candidate in candidates
                               if (candidate.polarity is True
                                   and _tokens(candidate.subject) == _tokens(subject)
                                   and _tokens(candidate.object) == _tokens(obj))]
                    if len(matches) != 1:
                        continue
                    candidate = matches[0]
                    predicate = next((str(item.get("predicate_phrase", ""))
                                      for item in candidate.language_evidence
                                      if item.get("kind")
                                      == "surface_relation_discovery"),
                                     candidate.relation)
                    if (_tokens(predicate) == _tokens(canonical_relation)
                            or not predicate.strip()):
                        continue
                    # This field currently has one mechanically generated
                    # question construction. Do not suggest coordinated
                    # variants such as "capital and largest city of" until
                    # CRMS can preserve their conjunction semantics.
                    if (canonical_relation == "capital of"
                            and not re.fullmatch(
                                r"capital city of", predicate,
                                flags=re.IGNORECASE)):
                        continue
                    pair = (_tokens(subject), _tokens(obj))
                    key = (canonical_relation, predicate)
                    row = {
                        "subject": subject,
                        "object": obj,
                        "canonical_field": field,
                        "canonical_sentence": document.text[field_start:field_end],
                        "canonical_source": field_citation,
                        "canonical_document_id": document.document_id,
                        "canonical_predicate": field,
                        "alias_sentence": sentence,
                        "alias_source": sentence_citation,
                        "alias_document_id": document.document_id,
                        "alias_predicate": predicate,
                    }
                    grouped.setdefault(key, {}).setdefault(pair, {})[
                        document.document_id] = row
            if processed_sentences >= maximum_sentences:
                break

        proposals = []
        minimum_total = max(3, minimum_pairs)
        for (canonical, predicate), pair_rows in sorted(grouped.items()):
            rows = [row for pair in sorted(pair_rows)
                    for _document_id, row in sorted(pair_rows[pair].items())]
            if len(rows) < minimum_total:
                continue
            # Keep at least two varied examples for learning and reserve a
            # separate page for transfer validation. With larger groups,
            # reserve the final quarter (at least one example).
            holdout_count = max(1, len(rows) // 4)
            training_rows = rows[:-holdout_count]
            holdout_rows = rows[-holdout_count:]
            if (len(training_rows) < 2
                    or len({_tokens(row["object"]) for row in training_rows}) < 2
                    or len({_tokens(row["subject"]) for row in training_rows}) < 2):
                continue
            support = training_rows + holdout_rows
            payload = {
                "evidence_kind": "structured_field_prose",
                "relation": canonical,
                "predicate_phrase": predicate,
                "support": support,
                "training_support": training_rows,
                "holdout_support": holdout_rows,
                "distinct_pairs": len({(_tokens(row["subject"]),
                                         _tokens(row["object"]))
                                        for row in support}),
                "canonical_documents": len({row["canonical_document_id"]
                                             for row in support}),
                "alias_documents": len({row["alias_document_id"]
                                         for row in support}),
                "review_required": True,
            }
            proposal_id = hashlib.sha256(json.dumps(
                payload, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
            proposals.append({"proposal_id": proposal_id, **payload})
        return sorted(proposals, key=lambda item: (
            item["relation"], item["predicate_phrase"],
            item["proposal_id"]))[:maximum_proposals]

    def propose_corpus_predicate_alignments(
            self, research_index: Any, *, minimum_pairs: int = 2,
            maximum_documents: int = 1000, maximum_sentences: int = 20_000,
            maximum_proposals: int = 100,
            document_offset: int = 0) -> list[dict[str, Any]]:
        """Find reviewed predicate alignments from prose and structured fields.

        Two independently parsed predicate frames are candidates for one
        relation when the same distinct subject/object pairs recur in separate
        documents. A bounded allowlist of explicit infobox fields can also
        supervise an alternate prose predicate when the same exact pair is
        stated in a complete sentence. Both routes are report-only; the user
        reviews the canonical relation before acceptance.
        """
        if (type(minimum_pairs) is not int or not 2 <= minimum_pairs <= 20
                or type(maximum_documents) is not int
                or not 1 <= maximum_documents <= 300_000
                or type(maximum_sentences) is not int
                or not 1 <= maximum_sentences <= 1_000_000
                or type(maximum_proposals) is not int
                or not 1 <= maximum_proposals <= 1000
                or type(document_offset) is not int
                or not 0 <= document_offset <= 1_000_000):
            raise ValueError("corpus predicate alignment bounds are outside supported limits")
        frames = self.propose_corpus_relation_frames(
            research_index, minimum_examples=minimum_pairs,
            maximum_documents=min(maximum_documents, 10_000),
            maximum_sentences=min(maximum_sentences, 1_000_000),
            maximum_proposals=1000, document_offset=document_offset)
        by_relation: dict[tuple[str, ...], dict[
            tuple[tuple[str, ...], tuple[str, ...]], list[dict[str, Any]]]] = {}
        for frame in frames:
            if frame["polarity"] is not True:
                continue
            relation = tuple(_tokens(frame["relation"]))
            for row in frame["support"]:
                pair = (_tokens(row["subject"]), _tokens(row["object"]))
                pair_rows = by_relation.setdefault(relation, {}).setdefault(pair, [])
                if all(existing["document_id"] != row["document_id"]
                       for existing in pair_rows):
                    pair_rows.append(row)

        proposals: list[dict[str, Any]] = []
        relations = sorted(by_relation)
        for left_index, left_relation in enumerate(relations):
            for right_relation in relations[left_index + 1:]:
                if left_relation == right_relation:
                    continue
                shared = set(by_relation[left_relation]) & set(by_relation[right_relation])
                aligned = []
                for pair in sorted(shared):
                    independent_rows = sorted(
                        ((left, right)
                         for left in by_relation[left_relation][pair]
                         for right in by_relation[right_relation][pair]
                         if left["document_id"] != right["document_id"]),
                        key=lambda rows: (rows[0]["document_id"],
                                         rows[1]["document_id"]))
                    if independent_rows:
                        left, right = independent_rows[0]
                        aligned.append((pair, left, right))
                if len(aligned) < minimum_pairs:
                    continue
                left_documents = {left["document_id"] for _, left, _ in aligned}
                right_documents = {right["document_id"] for _, _, right in aligned}
                if (len(left_documents) < minimum_pairs
                        or len(right_documents) < minimum_pairs):
                    continue
                # Prefer the more frequently attested relation as canonical;
                # use lexical order only for a deterministic tie. Reviewers
                # can still inspect and reject the proposed direction.
                left_count = len(by_relation[left_relation])
                right_count = len(by_relation[right_relation])
                if (right_count > left_count
                        or (right_count == left_count
                            and right_relation < left_relation)):
                    canonical_relation, alias_relation = right_relation, left_relation
                    canonical_side, alias_side = 2, 1
                else:
                    canonical_relation, alias_relation = left_relation, right_relation
                    canonical_side, alias_side = 1, 2
                support = []
                for _pair, left, right in aligned:
                    canonical = left if canonical_side == 1 else right
                    alias = left if alias_side == 1 else right
                    support.append({
                        "subject": canonical["subject"],
                        "object": canonical["object"],
                        "canonical_sentence": canonical["sentence"],
                        "canonical_source": canonical["source"],
                        "canonical_document_id": canonical["document_id"],
                        "canonical_predicate": canonical["predicate_phrase"],
                        "alias_sentence": alias["sentence"],
                        "alias_source": alias["source"],
                        "alias_document_id": alias["document_id"],
                        "alias_predicate": alias["predicate_phrase"],
                    })
                payload = {
                    "relation": " ".join(canonical_relation),
                    "predicate_phrase": " ".join(alias_relation),
                    "support": support,
                    "distinct_pairs": len(support),
                    "canonical_documents": len({row["canonical_document_id"]
                                                 for row in support}),
                    "alias_documents": len({row["alias_document_id"]
                                             for row in support}),
                    "review_required": True,
                }
                proposal_id = hashlib.sha256(json.dumps(
                    payload, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
                proposals.append({"proposal_id": proposal_id, **payload})
        structured = self._propose_structured_predicate_alignments(
            research_index, minimum_pairs=minimum_pairs,
            maximum_documents=maximum_documents,
            maximum_sentences=maximum_sentences,
            maximum_proposals=maximum_proposals,
            document_offset=document_offset)
        existing_shapes = {(item["relation"], item["predicate_phrase"])
                           for item in proposals}
        proposals.extend(item for item in structured
                         if (item["relation"], item["predicate_phrase"])
                         not in existing_shapes)
        unique = {item["proposal_id"]: item for item in proposals}
        return sorted(unique.values(), key=lambda item: (
            item["relation"], item["predicate_phrase"],
            item["proposal_id"]))[:maximum_proposals]

    def accept_corpus_predicate_alignment(
            self, proposal_id: str, research_index: Any, *,
            minimum_pairs: int = 2, maximum_documents: int = 1000,
            maximum_sentences: int = 20_000, maximum_proposals: int = 100,
            document_offset: int = 0) -> dict[str, Any]:
        """Accept a freshly revalidated corpus-only predicate alignment."""
        if not isinstance(proposal_id, str) or not re.fullmatch(
                r"[0-9a-f]{24}", proposal_id):
            raise ValueError("corpus predicate alignment ID is malformed")
        proposal = next((item for item in self.propose_corpus_predicate_alignments(
            research_index, minimum_pairs=minimum_pairs,
            maximum_documents=maximum_documents,
            maximum_sentences=maximum_sentences,
            maximum_proposals=maximum_proposals,
            document_offset=document_offset)
            if item["proposal_id"] == proposal_id), None)
        if proposal is None:
            raise ValueError("corpus predicate alignment is stale or unsupported")
        staged = copy.deepcopy(self)
        if proposal.get("evidence_kind") == "structured_field_prose":
            accepted = staged._accept_structured_predicate_alignment(
                proposal, research_index)
            self.__dict__.clear()
            self.__dict__.update(staged.__dict__)
            return accepted
        validated = []
        for row in proposal["support"]:
            parsed_rows = []
            for sentence_key, source_key, predicate_key in (
                    ("canonical_sentence", "canonical_source", "canonical_predicate"),
                    ("alias_sentence", "alias_source", "alias_predicate")):
                excerpt = research_index.resolve_citation(row[source_key])
                if row[sentence_key] not in excerpt:
                    raise ValueError("predicate alignment evidence no longer matches its source")
                parses = staged._discover_surface_relation_candidates(
                    row[sentence_key], source=row[source_key],
                    research_index=research_index,
                    morphology_rules=staged._licensed_predicate_spelling_rules())
                matching = [candidate for candidate in parses
                            if (_tokens(candidate.subject) == _tokens(row["subject"])
                                and _tokens(candidate.object) == _tokens(row["object"])
                                and _tokens(next((str(item["predicate_phrase"])
                                                  for item in candidate.language_evidence
                                                  if item.get("kind") == "surface_relation_discovery"), ""))
                                    == _tokens(row[predicate_key]))]
                if len(matching) != 1:
                    raise ValueError("predicate alignment sentence no longer has a unique parse")
                parsed_rows.append(matching[0])
            validated.append((row, parsed_rows[0], parsed_rows[1]))
        if len(validated) < minimum_pairs:
            raise ValueError("predicate alignment lost distinct-pair support")
        for row, canonical, alias in validated:
            staged.add_fact(row["subject"], proposal["relation"],
                            row["object"], row["canonical_source"])
            staged.teach_fact_pattern(
                row["canonical_sentence"], subject=row["subject"],
                relation=proposal["relation"], obj=row["object"],
                predicate_phrase=row["canonical_predicate"],
                source=row["canonical_source"])
            staged.add_fact(row["subject"], proposal["relation"],
                            row["object"], row["alias_source"])
            staged.teach_fact_pattern(
                row["alias_sentence"], subject=row["subject"],
                relation=proposal["relation"], obj=row["object"],
                predicate_phrase=row["alias_predicate"],
                source=row["alias_source"])
        self.__dict__.clear()
        self.__dict__.update(staged.__dict__)
        return proposal

    def _accept_structured_predicate_alignment(
            self, proposal: dict[str, Any], research_index: Any
            ) -> dict[str, Any]:
        """Revalidate metadata/prose pairs, learn on training pages, test holdout."""
        if proposal.get("relation") != "capital of":
            raise ValueError("no reviewed question frame exists for this field relation")
        predicate = str(proposal.get("predicate_phrase", ""))
        if not re.fullmatch(r"capital(?: city)? of", predicate, flags=re.I):
            raise ValueError("the capital-field question form is not licensed")
        support = proposal.get("support", [])
        training = proposal.get("training_support", [])
        holdout = proposal.get("holdout_support", [])
        if (len(support) < 3 or len(training) < 2 or not holdout
                or len({(_tokens(row["subject"]), _tokens(row["object"]))
                        for row in training}) < 2):
            raise ValueError("structured alignment needs varied training and a held-out page")

        validated = []
        morphology = self._licensed_predicate_spelling_rules()
        for row in support:
            document = research_index.document(row["alias_document_id"])
            if document.title != row["object"]:
                raise ValueError("structured-field title no longer matches the proposal")
            field_excerpt = research_index.resolve_citation(row["canonical_source"])
            if row["canonical_sentence"] not in field_excerpt:
                raise ValueError("structured field no longer matches its citation")
            field_match = re.fullmatch(
                r"\s*capital\s*=\s*(.+?)\s*", row["canonical_sentence"],
                flags=re.IGNORECASE)
            if (field_match is None
                    or _tokens(field_match.group(1)) != _tokens(row["subject"])):
                raise ValueError("capital field no longer supports the proposed city")
            sentence_excerpt = research_index.resolve_citation(row["alias_source"])
            if row["alias_sentence"] not in sentence_excerpt:
                raise ValueError("prose example no longer matches its citation")
            parses = self._discover_surface_relation_candidates(
                row["alias_sentence"], source=row["alias_source"],
                research_index=research_index, morphology_rules=morphology)
            matches = [candidate for candidate in parses
                       if (candidate.polarity is True
                           and _tokens(candidate.subject) == _tokens(row["subject"])
                           and _tokens(candidate.object) == _tokens(row["object"])
                           and _tokens(next((str(item.get("predicate_phrase", ""))
                                             for item in candidate.language_evidence
                                             if item.get("kind")
                                             == "surface_relation_discovery"), ""))
                               == _tokens(predicate))]
            if len(matches) != 1:
                raise ValueError("prose pair no longer has one exact source parse")
            validated.append(row)

        training_ids = {row["alias_document_id"] for row in training}
        holdout_ids = {row["alias_document_id"] for row in holdout}
        if training_ids & holdout_ids:
            raise ValueError("training and held-out pages must be disjoint")
        for row in validated:
            self.add_fact(row["subject"], proposal["relation"], row["object"],
                          row["canonical_source"])
            self.add_fact(row["subject"], proposal["relation"], row["object"],
                          row["alias_source"])
        for row in training:
            question = f"What city is the {predicate} {row['object']}?"
            self.teach_question(
                question, relation=proposal["relation"],
                answer_field="subject", bound_entity=row["object"],
                answer=row["subject"])
            self.teach_fact_pattern(
                row["alias_sentence"], subject=row["subject"],
                relation=proposal["relation"], obj=row["object"],
                predicate_phrase=predicate, source=row["alias_source"])

        expected_template = (f"what city is the {predicate} "
                             "{object}")
        heldout_checks = []
        for heldout in holdout:
            heldout_question = f"What city is the {predicate} {heldout['object']}?"
            result = self.ask(heldout_question)
            expected_sources = {heldout["canonical_source"],
                                heldout["alias_source"]}
            observed_sources = {source for evidence in result.evidence or []
                                for source in evidence.get("sources", ())}
            valid_sources = sorted(observed_sources.intersection(expected_sources))
            if (result.status != "answered"
                    or result.answer != heldout["subject"]
                    or expected_template not in (result.matched_templates or [])
                    or not valid_sources):
                raise ValueError(
                    "accepted training examples failed a held-out "
                    "question-frame check")
            heldout_checks.append({
                "question": heldout_question,
                "answer": result.answer,
                "source": valid_sources[0],
                "matched_template": expected_template,
                "heldout_document": heldout["alias_document_id"],
            })
        first_check = heldout_checks[0]
        return {
            **proposal,
            "heldout_validation": {
                **first_check,
                "checks": heldout_checks,
                "training_documents": sorted(training_ids),
            },
        }

    def propose_predicate_form_alignments(
            self, research_index: Any, *, minimum_facts: int = 2,
            maximum_facts: int = 100, maximum_hits_per_fact: int = 100,
            maximum_proposals: int = 100, fact_offset: int = 0
            ) -> list[dict[str, Any]]:
        """Find repeated alternate predicate wording for accepted relations.

        The proposal is report-only. It requires distinct accepted
        subject/object pairs, separate source documents, and a unique
        capitalized-span analysis for each supporting sentence.
        """
        if (type(minimum_facts) is not int or not 2 <= minimum_facts <= 20
                or type(maximum_facts) is not int
                or not 1 <= maximum_facts <= 10_000
                or type(maximum_hits_per_fact) is not int
                or not 1 <= maximum_hits_per_fact <= 1000
                or type(maximum_proposals) is not int
                or not 1 <= maximum_proposals <= 1000
                or type(fact_offset) is not int
                or not 0 <= fact_offset <= 1_000_000):
            raise ValueError("predicate alignment bounds are outside supported limits")
        facts = [fact for fact in self._facts.values() if not fact.qualifiers]
        facts.sort(key=lambda fact: (fact.relation.casefold(),
                                     fact.subject.casefold(),
                                     fact.object.casefold()))
        groups: dict[tuple[Any, ...], dict[tuple[Any, ...], dict[str, Any]]] = {}
        for fact in facts[fact_offset:fact_offset + maximum_facts]:
            known_forms = {
                form for (template, relation), forms
                in self._fact_pattern_predicates.items()
                if relation == _tokens(fact.relation)
                for form in forms
            }
            query = " ".join((fact.subject, fact.object))
            try:
                hits = research_index.search(query, limit=maximum_hits_per_fact)
            except (AttributeError, TypeError, ValueError):
                continue
            for hit in hits:
                citation = research_index.citation(hit)
                document_id = hit.document_id
                if any(source.partition("#sha256=")[0] == document_id
                       for source in fact.sources):
                    continue
                sentence_rows = re.split(r"(?<=[.!?])\s+|\n+", hit.snippet)
                for sentence in sentence_rows:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    for candidate in self._discover_surface_relation_candidates(
                            sentence, source=citation, allow_uninflected=True):
                        if (_tokens(candidate.subject) != _tokens(fact.subject)
                                or _tokens(candidate.object) != _tokens(fact.object)):
                            continue
                        phrase = next((
                            str(item["predicate_phrase"])
                            for item in candidate.language_evidence
                            if item.get("kind") == "surface_relation_discovery"),
                            "")
                        phrase_tokens = _tokens(phrase)
                        if (not phrase_tokens or phrase_tokens in known_forms
                                or phrase_tokens == _tokens(fact.relation)):
                            continue
                        group_key = (_tokens(fact.relation), phrase_tokens,
                                     tuple(_tokens(candidate.template)))
                        pair_key = (_tokens(fact.subject), _tokens(fact.object))
                        groups.setdefault(group_key, {}).setdefault(
                            pair_key, {
                                "subject": fact.subject,
                                "object": fact.object,
                                "sentence": sentence,
                                "source": citation,
                                "document_id": document_id,
                            })

        proposals = []
        for (relation_tokens, phrase_tokens, template), rows in sorted(groups.items()):
            support = [rows[key] for key in sorted(rows)]
            subjects = {_tokens(row["subject"]) for row in support}
            objects = {_tokens(row["object"]) for row in support}
            documents = {row["document_id"] for row in support}
            if (len(support) < minimum_facts
                    or len(subjects) < minimum_facts
                    or len(objects) < minimum_facts
                    or len(documents) < minimum_facts):
                continue
            payload = {
                "relation": " ".join(relation_tokens),
                "predicate_phrase": " ".join(phrase_tokens),
                "template": list(template),
                "support": support,
                "distinct_subjects": len(subjects),
                "distinct_objects": len(objects),
                "independent_documents": len(documents),
                "review_required": True,
            }
            artifact_id = hashlib.sha256(json.dumps(
                payload, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
            proposals.append({"proposal_id": artifact_id, **payload})
        return sorted(proposals, key=lambda item: (
            item["relation"], item["predicate_phrase"],
            item["proposal_id"]))[:maximum_proposals]

    def accept_predicate_form_alignment(
            self, proposal_id: str, research_index: Any, *,
            maximum_hits_per_fact: int = 100, fact_offset: int = 0
            ) -> dict[str, Any]:
        """Accept one freshly regenerated predicate-form proposal."""
        if (type(maximum_hits_per_fact) is not int
                or not 1 <= maximum_hits_per_fact <= 1000
                or type(fact_offset) is not int
                or not 0 <= fact_offset <= 1_000_000):
            raise ValueError("predicate alignment search bounds are invalid")
        if not isinstance(proposal_id, str) or not re.fullmatch(
                r"[0-9a-f]{24}", proposal_id):
            raise ValueError("predicate-form proposal id is malformed")
        proposal = next((item for item in self.propose_predicate_form_alignments(
            research_index, maximum_hits_per_fact=maximum_hits_per_fact,
            fact_offset=fact_offset)
            if item["proposal_id"] == proposal_id), None)
        if proposal is None:
            raise ValueError("predicate-form proposal is stale or unsupported")
        validated = []
        for row in proposal["support"]:
            excerpt = research_index.resolve_citation(row["source"])
            if row["sentence"] not in excerpt:
                raise ValueError("predicate-form evidence no longer matches its source")
            fact = self._facts.get(self._fact_key(
                row["subject"], proposal["relation"], row["object"]))
            if fact is None or row["source"] in fact.sources:
                raise ValueError("predicate-form claim lacks a current distinct fact")
            parses = self._discover_surface_relation_candidates(
                row["sentence"], source=row["source"], allow_uninflected=True)
            if not any(
                    _tokens(candidate.subject) == _tokens(row["subject"])
                    and _tokens(candidate.object) == _tokens(row["object"])
                    and _tokens(next((str(item["predicate_phrase"])
                                      for item in candidate.language_evidence
                                      if item.get("kind")
                                      == "surface_relation_discovery"), ""))
                        == _tokens(proposal["predicate_phrase"])
                    for candidate in parses):
                raise ValueError("predicate-form roles are no longer uniquely licensed")
            validated.append((row, fact))
        if len(validated) < 2:
            raise ValueError("predicate-form proposal lost varied fact support")

        for row, _fact in validated:
            self.add_fact(row["subject"], proposal["relation"], row["object"],
                          row["source"])
            self.teach_fact_pattern(
                row["sentence"], subject=row["subject"],
                relation=proposal["relation"], obj=row["object"],
                source=row["source"],
                predicate_phrase=proposal["predicate_phrase"])
        return proposal

    def _propose_facts(
            self, sentence: str, source: str,
            memo: dict[tuple[str, str], tuple[FactCandidate, ...]],
    ) -> list[FactCandidate]:
        """Memoized implementation shared by coordinated clause parses."""
        sentence = _display(sentence, "sentence")
        source = _display(source, "source")
        memo_key = (sentence, source)
        if memo_key in memo:
            return list(memo[memo_key])
        structured = re.fullmatch(
            r"\s*(?P<subject>.+?)\s+—\s+(?P<relation>.+?)\s+→\s+"
            r"(?P<object>.+?)\s*[.!?]?\s*", sentence)
        if structured is not None:
            subject, relation, obj = (self._canonicalize_entity(
                structured.group(field).strip())
                for field in ("subject", "relation", "object"))
            candidate = FactCandidate(
                subject, relation, obj, source,
                "<subject> — <relation> → <object>", sentence, True,
                ({"kind": "structured_claim", "review_required": True},))
            memo[memo_key] = (candidate,)
            return [candidate]
        token_matches = word_matches(sentence)
        words = tuple(match.group() for match in token_matches)
        if len(words) > 256:
            memo[memo_key] = ()
            return []
        # Contrastive corrections change which entity is asserted ("X, not
        # Y" / "not X but Y"). A flat learned frame cannot safely distinguish
        # that scope, so hold the sentence for better evidence instead of
        # absorbing the correction into a positive object span.
        if (re.search(r",\s*not\s+\S", sentence, flags=re.IGNORECASE)
                or re.search(r"\bnot\s+\S.{0,100}?\bbut\b",
                             sentence, flags=re.IGNORECASE)):
            memo[memo_key] = ()
            return []
        # A disjunction does not assert both branches. Refuse the whole
        # sentence before the flexible object-span matcher can absorb the
        # second branch into a misleading single object phrase.
        if "or" in words:
            memo[memo_key] = ()
            return []

        # Handle a single comma-delimited subject-relative clause such as
        # "Ada, who designed the Engine, built the Compiler." Reconstruct both
        # propositions from the same subject, then require each side to match
        # its own learned fact frame. This does not infer the relative-clause
        # relation or accept a partial parse.
        relative_markers = list(re.finditer(
            r",\s*(?:who|which)\b", sentence, flags=re.IGNORECASE))
        if relative_markers:
            if len(relative_markers) != 1:
                memo[memo_key] = ()
                return []
            relative = re.fullmatch(
                r"\s*(.+?),\s*(?:who|which)\s+(.+?),\s*(.+?)\s*[.!?]?\s*",
                sentence, flags=re.IGNORECASE)
            if relative is None:
                memo[memo_key] = ()
                return []
            antecedent, relative_predicate, main_predicate = (
                part.strip() for part in relative.groups())
            relative_candidates = self._propose_facts(
                f"{antecedent} {relative_predicate}", source, memo)
            main_candidates = self._propose_facts(
                f"{antecedent} {main_predicate}", source, memo)
            if not relative_candidates or not main_candidates:
                memo[memo_key] = ()
                return []
            if any(casefold_nfc(candidate.subject) != casefold_nfc(antecedent)
                   for candidate in (*relative_candidates, *main_candidates)):
                memo[memo_key] = ()
                return []
            unique = {
                (casefold_nfc(candidate.subject), candidate.relation,
                 casefold_nfc(candidate.object), candidate.polarity): candidate
                for candidate in (*relative_candidates, *main_candidates)
            }
            result = tuple(replace(unique[key], sentence=sentence)
                           for key in sorted(unique))
            memo[memo_key] = result
            return list(result)

        # Also support one restrictive relative clause without commas. The
        # relative/main boundary and whether the antecedent fills the subject
        # or object role are not marked in a uniform way, so try token
        # boundaries and both role assignments. Accept only a single distinct
        # result licensed by learned frames on both sides. This does not guess
        # a missing relation or discard an unsupported clause.
        restrictive_markers = [
            match for match in re.finditer(r"\b(?:who|whom|which|that)\b", sentence,
                                           flags=re.IGNORECASE)
            if not re.search(r",\s*$", sentence[:match.start()])
        ]
        if restrictive_markers:
            if len(restrictive_markers) != 1:
                memo[memo_key] = ()
                return []
            marker = restrictive_markers[0]
            antecedent = sentence[:marker.start()].strip(" ,;:")
            if not antecedent:
                memo[memo_key] = ()
                return []
            canonical_antecedent = self._canonicalize_entity(antecedent)
            known_entities = {
                casefold_nfc(entity)
                for fact in (*self._facts.values(),
                             *self._negative_facts.values())
                for entity in (fact.subject, fact.object)
            }
            if casefold_nfc(canonical_antecedent) not in known_entities:
                # Do not reinterpret complementizer "that" or an unknown
                # phrase as a relative clause.
                restrictive_markers = []
            if not restrictive_markers:
                # Leave ordinary learned sentence frames such as
                # "Ada said that the Engine failed" to the standard matcher.
                pass
            else:
                marker_word_index = next(
                    (index for index, token in enumerate(token_matches)
                     if token.start() == marker.start()), None)
                if not antecedent or marker_word_index is None:
                    memo[memo_key] = ()
                    return []
                parses: dict[
                    tuple[tuple[str, str, str, bool], ...],
                    dict[tuple[str, str, str, bool], FactCandidate],
                ] = {}
                for boundary_index in range(marker_word_index + 2,
                                            len(token_matches)):
                    boundary = token_matches[boundary_index].start()
                    relative_predicate = sentence[marker.end():boundary].strip(
                        " ,;:")
                    main_predicate = sentence[boundary:].strip(" ,;:")
                    if not relative_predicate or not main_predicate:
                        continue

                    # Subject-relative: "Ada who designed the Engine built ..."
                    subject_relative = self._propose_facts(
                        f"{antecedent} {relative_predicate}", source, memo)
                    main_candidates = self._propose_facts(
                        f"{antecedent} {main_predicate}", source, memo)
                    if (subject_relative and main_candidates
                            and all(casefold_nfc(candidate.subject)
                                    == casefold_nfc(canonical_antecedent)
                                    for candidate in
                                    (*subject_relative, *main_candidates))):
                        unique = {
                            (casefold_nfc(candidate.subject), candidate.relation,
                             casefold_nfc(candidate.object), candidate.polarity): candidate
                            for candidate in (*subject_relative, *main_candidates)
                        }
                        parses[tuple(sorted(unique))] = unique

                    # Object-relative: "the Engine that Ada designed passed ..."
                    object_relative = self._propose_facts(
                        f"{relative_predicate} {antecedent}", source, memo)
                    if (object_relative and main_candidates
                            and all(casefold_nfc(candidate.object)
                                    == casefold_nfc(canonical_antecedent)
                                    for candidate in object_relative)
                            and all(casefold_nfc(candidate.subject)
                                    == casefold_nfc(canonical_antecedent)
                                    for candidate in main_candidates)):
                        unique = {
                            (casefold_nfc(candidate.subject), candidate.relation,
                             casefold_nfc(candidate.object), candidate.polarity): candidate
                            for candidate in (*object_relative, *main_candidates)
                        }
                        parses[tuple(sorted(unique))] = unique
                if len(parses) > 1:
                    memo[memo_key] = ()
                    return []
                if parses:
                    only_parse = next(iter(parses.values()))
                    result = tuple(replace(only_parse[key], sentence=sentence)
                                   for key in sorted(only_parse))
                    memo[memo_key] = result
                    return list(result)
                memo[memo_key] = ()
                return []

        # Compose independently grounded assertions joined by "and", "but",
        # or a semicolon. A split is accepted only when both sides produce
        # learned-frame candidates; otherwise the ordinary whole-sentence
        # matcher remains responsible. "Or" is excluded because it does not
        # assert both alternatives. Ellipsis recovery is limited to the two
        # coordinators, not semicolons, which conventionally separate complete
        # clauses. Separators themselves are not modeled as fact relations.
        separators = [
            (match.start(), match.end(), True)
            for match in token_matches
            if match.group(0).casefold() in {"and", "but"}
        ]
        separators.extend((match.start(), match.end(), False)
                          for match in re.finditer(r";", sentence))
        # Keep recursive segmentation work bounded for malformed or highly
        # coordinated passages; large constructions require a narrower query.
        if len(separators) > 8:
            memo[memo_key] = ()
            return []
        coordinated_parses: dict[
            tuple[tuple[str, str, str, bool], ...], list[FactCandidate]
        ] = {}
        for separator_start, separator_end, allow_ellipsis in separators:
            left_text = sentence[:separator_start].strip(" ,;:")
            right_text = sentence[separator_end:].strip(" ,;:")
            if not left_text or not right_text:
                continue
            left = self._propose_facts(left_text, source, memo)
            right = self._propose_facts(right_text, source, memo)
            if not left:
                continue
            if not right:
                if not allow_ellipsis:
                    continue
                # Recover only a shared subject. The fragment still has to
                # match an independently learned frame after the antecedent
                # is restored, so this does not supply a missing relation.
                recovered: dict[
                    tuple[str, str, str, bool], FactCandidate
                ] = {}
                for antecedent in left:
                    expanded = self._propose_facts(
                        f"{antecedent.subject} {right_text}", source, memo)
                    for candidate in expanded:
                        if candidate.subject.casefold() != antecedent.subject.casefold():
                            continue
                        recovered[(candidate.subject.casefold(),
                                   candidate.relation,
                                   candidate.object.casefold(),
                                   candidate.polarity)] = candidate
                if not recovered:
                    # Also recover a shared predicate for an object-only
                    # continuation ("designed A and B"). Predicate forms
                    # come from the antecedent's licensed relation frames,
                    # and the reconstructed clause must match one of them.
                    for antecedent in left:
                        relation_tokens = _tokens(antecedent.relation)
                        observed = {
                            phrase
                            for key, examples in self._fact_pattern_examples.items()
                            if (key[1] == relation_tokens
                                and self._fact_pattern_is_licensed(key, examples))
                            for phrase in self._fact_pattern_predicates.get(key, set())
                        }
                        predicate_forms, _evidence = (
                            self._predicate_forms_for_relation(
                                relation_tokens, observed))
                        for predicate in sorted(predicate_forms):
                            expanded = self._propose_facts(
                                " ".join((antecedent.subject,
                                          " ".join(predicate), right_text)),
                                source, memo)
                            for candidate in expanded:
                                if (candidate.subject.casefold()
                                        != antecedent.subject.casefold()
                                        or candidate.relation
                                        != antecedent.relation):
                                    continue
                                recovered[(candidate.subject.casefold(),
                                           candidate.relation,
                                           candidate.object.casefold(),
                                           candidate.polarity)] = candidate
                right = [recovered[key] for key in sorted(recovered)]
            if not right:
                continue
            combined = [replace(candidate, sentence=sentence)
                        for candidate in (*left, *right)]
            unique = {
                (candidate.subject.casefold(), candidate.relation,
                 candidate.object.casefold(), candidate.polarity): candidate
                for candidate in combined
            }
            signature = tuple(sorted(unique))
            coordinated_parses[signature] = [unique[key] for key in signature]
        if len(coordinated_parses) == 1:
            result = next(iter(coordinated_parses.values()))
            memo[memo_key] = tuple(result)
            return result
        if len(coordinated_parses) > 1:
            # More than one distinct complete clause analysis is unresolved.
            memo[memo_key] = ()
            return []
        if ";" in sentence:
            # A semicolon marks a clause boundary. Do not let a flexible
            # object span swallow an unmatched second clause as one object.
            memo[memo_key] = ()
            return []

        context_candidates, context_recognized = (
            self._propose_context_fact_patterns(
                sentence, source, token_matches, words))
        if context_recognized:
            memo[memo_key] = tuple(context_candidates)
            return list(context_candidates)

        # Distribute a coordinated subject over a shared predicate, e.g.
        # "Ada and Grace designed the Engine." The left subject anchors the
        # parse to a known entity; the right subject may be new, but both
        # reconstructed clauses must independently match a learned frame and
        # agree on relation, object, and polarity. A leading "both" is an
        # optional cue. This preserves separate claims without requiring a
        # previously known entity for every source-backed name.
        and_matches = [match for match in token_matches
                       if match.group(0).casefold() == "and"]
        if len(and_matches) > 1:
            first_left = sentence[:and_matches[0].start()].strip(" ,;:")
            first_left = re.sub(r"^both\b", "", first_left,
                                count=1, flags=re.IGNORECASE).strip()
            first_tokens = _tokens(first_left)
            known_first = (
                first_tokens in {
                    _tokens(entity)
                    for fact in (*self._facts.values(),
                                 *self._negative_facts.values())
                    for entity in (fact.subject, fact.object)
                }
                or first_tokens in self._entity_alias_records())
            if known_first:
                memo[memo_key] = ()
                return []
        if len(and_matches) == 1:
            conjunction = and_matches[0]
            left_surface = sentence[:conjunction.start()].strip(" ,;:")
            has_both = bool(re.match(r"^both\b", left_surface,
                                     flags=re.IGNORECASE))
            if has_both:
                left_surface = re.sub(r"^both\b", "", left_surface,
                                      count=1, flags=re.IGNORECASE).strip()
            known_surface_entities: dict[tuple[str, ...], set[str]] = {}
            for fact in (*self._facts.values(), *self._negative_facts.values()):
                for entity in (fact.subject, fact.object):
                    known_surface_entities.setdefault(_tokens(entity), set()).add(entity)
            for alias, record in self._entity_alias_records().items():
                known_surface_entities.setdefault(alias, set()).add(record["entity"])
            left_entities = known_surface_entities.get(_tokens(left_surface), set())
            if has_both or left_entities:
                if len(left_entities) != 1:
                    memo[memo_key] = ()
                    return []
                left_entity = next(iter(left_entities))
                conjunction_index = next(
                    index for index, token in enumerate(token_matches)
                    if token.start() == conjunction.start())
                parses: dict[
                    tuple[tuple[str, str, str, bool], ...],
                    dict[tuple[str, str, str, bool], FactCandidate],
                ] = {}
                for subject_end in range(conjunction_index + 2,
                                         len(token_matches) + 1):
                    right_surface = sentence[
                        token_matches[conjunction_index + 1].start():
                        token_matches[subject_end - 1].end()]
                    predicate_tail = sentence[
                        token_matches[subject_end - 1].end():].strip(" ,;:")
                    if not predicate_tail:
                        continue
                    right_entity = self._canonicalize_entity(right_surface)
                    if right_entity.casefold() == left_entity.casefold():
                        continue
                    left_candidates = self._propose_facts(
                        f"{left_surface} {predicate_tail}", source, memo)
                    right_candidates = self._propose_facts(
                        f"{right_surface} {predicate_tail}", source, memo)
                    left_candidates = [candidate for candidate in left_candidates
                                       if candidate.subject.casefold()
                                       == left_entity.casefold()]
                    right_candidates = [candidate for candidate in right_candidates
                                        if candidate.subject.casefold()
                                        == right_entity.casefold()]
                    for left_candidate in left_candidates:
                        for right_candidate in right_candidates:
                            if (left_candidate.relation != right_candidate.relation
                                    or left_candidate.object.casefold()
                                    != right_candidate.object.casefold()
                                    or left_candidate.polarity
                                    != right_candidate.polarity):
                                continue
                            unique = {
                                (candidate.subject.casefold(), candidate.relation,
                                 candidate.object.casefold(), candidate.polarity):
                                replace(candidate, sentence=sentence)
                                for candidate in (left_candidate, right_candidate)
                            }
                            signature = tuple(sorted(unique))
                            parses[signature] = unique
                if len(parses) == 1:
                    result = list(next(iter(parses.values())).values())
                    result.sort(key=lambda candidate: (
                        candidate.subject.casefold(), candidate.relation,
                        candidate.object.casefold(), candidate.polarity))
                    memo[memo_key] = tuple(result)
                    return result
                if len(parses) > 1 or left_entities or has_both:
                    memo[memo_key] = ()
                    return []

        proposals: dict[
            tuple[str, tuple[str, ...], tuple[str, ...], bool], FactCandidate] = {}
        entity_alias_records = self._entity_alias_records()
        for (template, relation_tokens), examples in self._fact_pattern_examples.items():
            pattern_key = (template, relation_tokens)
            if not self._fact_pattern_is_licensed(pattern_key, examples):
                continue
            polarity = self._fact_pattern_polarities.get(pattern_key, True)
            contrastive_frame_tokens = {
                token
                for other_key, other_examples in self._fact_pattern_examples.items()
                if (other_key != pattern_key
                    and other_key[1] == relation_tokens
                    and self._fact_pattern_polarities.get(other_key, True) == polarity
                    and self._fact_pattern_is_licensed(other_key, other_examples))
                for token in other_key[0]
                if not (token.startswith("<") and token.endswith(">"))
            }
            subject_role_tokens = {
                token for subject_tokens, _ in examples for token in subject_tokens}
            object_role_tokens = {
                token for _, object_tokens in examples for token in object_tokens}
            language_evidence = tuple(
                {"template": " ".join(evidence_key[0]),
                 "subject": " ".join(pair[0]),
                 "object": " ".join(pair[1]),
                 "sources": sorted(example_sources)}
                for evidence_key, evidence_examples in sorted(
                    self._fact_pattern_examples.items())
                if (evidence_key == pattern_key
                    or (evidence_key[1] == relation_tokens
                        and self._fact_pattern_polarities.get(evidence_key, True) == polarity
                        and self._fact_pattern_is_licensed(
                            evidence_key, evidence_examples)))
                for pair, example_sources in sorted(evidence_examples.items())
            )
            predicate_phrases, induced_predicate_evidence = (
                self._predicate_forms_for_relation(
                    relation_tokens,
                    self._fact_pattern_predicates.get(
                        (template, relation_tokens), {relation_tokens})))
            predicate_surface_tokens = {
                token for phrase in predicate_phrases for token in phrase
            }
            for predicate_words in predicate_phrases:
                compiled_template: list[str] = []
                for token in template:
                    if token == "<predicate>":
                        compiled_template.extend(predicate_words)
                    else:
                        compiled_template.append(token)
                predicate_positions = [
                    i for i in range(len(words) - len(predicate_words) + 1)
                    if words[i:i + len(predicate_words)] == predicate_words]
                if len(predicate_positions) != 1:
                    continue
                matches = self._match_fact_template(tuple(compiled_template), words)
                # A pattern with multiple variable-span parses is not a unique
                # structural analysis. Abstain for this pattern.
                if len(matches) != 1:
                    continue
                (subject_words, object_words, subject_start, subject_end,
                 object_start, object_end) = matches[0]
                predicate_start = predicate_positions[0]
                predicate_end = predicate_start + len(predicate_words)
                # A productive prefix joined to a verb with a hyphen is part
                # of that surface predicate, not the preceding subject. If
                # this compound has no grounded alignment, leave it to the
                # review-only surface discovery path instead of proposing
                # "Ken Thompson co" as a subject for the frame "created".
                if predicate_start > 0:
                    previous = token_matches[predicate_start - 1]
                    current = token_matches[predicate_start]
                    connector = sentence[previous.end():current.start()]
                    if (previous.group().casefold() in {"co", "re", "pre", "non"}
                            and "-" in connector):
                        continue
                if ((predicate_start < subject_end and predicate_end > subject_start)
                        or (predicate_start < object_end and predicate_end > object_start)):
                    continue
                # Do not let a frame's literal structure words be swallowed by
                # a competing frame's open entity slots unless the exact role
                # is grounded to those words in that frame's own examples.
                if ((set(subject_words) & contrastive_frame_tokens
                     - subject_role_tokens)
                        or (set(object_words) & contrastive_frame_tokens
                            - object_role_tokens)):
                    continue
                # A shorter canonical predicate form must not let the
                # unconsumed function words from a longer licensed surface
                # form leak into open entity slots. For example, matching
                # only "parent" inside "Cal is parent of Dee" must not
                # create the spurious fact "Cal is — parent → of Dee" when
                # the model has also learned "is parent of" as the full
                # predicate wording.
                if ((set(subject_words) & predicate_surface_tokens
                     - subject_role_tokens)
                        or (set(object_words) & predicate_surface_tokens
                            - object_role_tokens)):
                    continue
                subject = sentence[token_matches[subject_start].start():
                                   token_matches[subject_end - 1].end()]
                obj = sentence[token_matches[object_start].start():
                               token_matches[object_end - 1].end()]
                # A variable object slot can otherwise absorb a following
                # locative or dated adjunct. Trim only a narrow, explicit
                # form whose marker is followed by a proper-name or numeric
                # phrase; ambiguous lower-case complements remain intact for
                # human review rather than being guessed away.
                adjunct = re.match(
                    r"(?P<object>.+?)\s+(?:at|in|on)\s+(?=(?:[A-Z0-9]|the\s+[A-Z]))",
                    obj)
                if adjunct is not None and object_end - object_start > 1:
                    obj = adjunct.group("object")
                subject_surface, object_surface = subject, obj
                subject_alias = entity_alias_records.get(_tokens(subject_surface))
                object_alias = entity_alias_records.get(_tokens(object_surface))
                subject = (subject_alias["entity"] if subject_alias
                           else self._canonicalize_entity(subject))
                obj = (object_alias["entity"] if object_alias
                       else self._canonicalize_entity(obj))
                relation = " ".join(relation_tokens)
                template_text = " ".join(template)
                candidate_evidence = language_evidence
                if predicate_words in induced_predicate_evidence:
                    candidate_evidence += (induced_predicate_evidence[predicate_words],)
                candidate_evidence += tuple(
                    dict(record) | {"alias": surface}
                    for record, surface in ((subject_alias, subject_surface),
                                            (object_alias, object_surface))
                    if record is not None)
                candidate = FactCandidate(subject, relation, obj, source,
                                          template_text, sentence,
                                          self._fact_pattern_polarities.get(
                                              pattern_key, True),
                                          candidate_evidence)
                proposal_key = (relation, _tokens(subject), _tokens(obj),
                                candidate.polarity)
                existing = proposals.get(proposal_key)
                if existing is None:
                    proposals[proposal_key] = candidate
                    continue
                evidence_by_key = {
                    json.dumps(item, sort_keys=True, ensure_ascii=False): item
                    for item in (*existing.language_evidence,
                                 *candidate.language_evidence)
                }
                selected = min((existing, candidate),
                               key=lambda item: item.template)
                proposals[proposal_key] = replace(
                    selected,
                    language_evidence=tuple(evidence_by_key[key]
                                            for key in sorted(evidence_by_key)))
        result = [proposals[key] for key in sorted(proposals)]
        memo[memo_key] = tuple(result)
        return result

    def propose_facts_from_hit(self, sentence: str, *,
                               research_index: Any, hit: Any) -> list[FactCandidate]:
        """Propose cited facts, including explicit relation-schema claims.

        Relation types are proposed only when a source sentence explicitly
        names both a relation and one supported schema type. The proposal is
        still an ordinary review-only fact candidate; relation names alone do
        not imply integrity constraints.
        """
        citation = research_index.citation(hit)
        excerpt = research_index.resolve_citation(citation)
        if sentence not in excerpt:
            raise ValueError("candidate sentence is not contained in the cited passage")
        proposals = self.propose_facts(sentence, source=citation)
        schema = self._propose_explicit_relation_type(sentence, citation)
        if schema is not None:
            key = (schema.subject.casefold(), schema.relation.casefold(),
                   schema.object.casefold(), schema.source,
                   schema.polarity, schema.qualifiers)
            proposals = [candidate for candidate in proposals
                         if (candidate.subject.casefold(),
                             candidate.relation.casefold(),
                             candidate.object.casefold(), candidate.source,
                             candidate.polarity, candidate.qualifiers) != key]
            proposals.append(schema)
        return sorted(proposals, key=lambda candidate: (
            candidate.subject.casefold(), candidate.relation.casefold(),
            candidate.object.casefold(), candidate.polarity,
            candidate.source))

    @staticmethod
    def _propose_explicit_relation_type(
            sentence: str, source: str) -> FactCandidate | None:
        """Extract only a literal, affirmative relation-type declaration."""
        schema_pattern = (
            r"transitive|symmetric|irreflexive|asymmetric|functional|"
            r"closed[- ]world")
        pattern = re.compile(
            r"\s*the\s+relation\s+(?:"
            r"\"(?P<double>[^\"\r\n]+)\"|"
            r"'(?P<single>[^'\r\n]+)'|"
            r"(?P<bare>[\w][\w'-]*)"
            r")\s+is\s+(?P<schema>" + schema_pattern +
            r")(?:\s+relation)?\s*[.!?]?\s*\Z",
            re.IGNORECASE)
        match = pattern.fullmatch(sentence)
        if match is None:
            return None
        relation = next((match.group(name) for name in
                         ("double", "single", "bare")
                         if match.group(name) is not None), "").strip()
        relation_type = match.group("schema").casefold().replace(" ", "-")
        if not relation or not _tokens(relation):
            return None
        return FactCandidate(
            relation, "has relation type", relation_type, source,
            "explicit relation schema declaration", sentence, True,
            ({"kind": "relation_type_schema_discovery",
              "method": "explicit relation declaration sentence",
              "review_required": True,
              "template": "explicit relation schema declaration",
              "subject": relation,
              "object": relation_type,
              "declared_relation_type": relation_type,
              "sources": [source]},))

    @staticmethod
    def _realize_question_from_passive_source(
            question: str, source_sentences: list[dict[str, Any]],
            query_expansions: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Realize a bounded subject/object question from a source clause.

        This is a retrieval-time, source-grounded wording operation. It does
        not store or accept a fact. Active clauses must align the named agent,
        predicate, and requested object; passive clauses must state an explicit
        ``by`` agent. Negated, corrected, coordinated, and example sentences
        are excluded.
        """
        direct = re.fullmatch(
            r"\s*who\s+(?:(?:did|does|do)\s+)?"
            r"(?P<predicate>[a-z][\w’'-]*)\s+(?P<object>.+?)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        nominal = re.fullmatch(
            r"\s*who\s+(?:is|was)\s+(?:the\s+)?"
            r"(?P<agent_noun>[a-z][\w’'-]*)\s+of\s+"
            r"(?P<object>.+?)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        object_question = re.fullmatch(
            r"\s*(?:what|which(?:\s+[a-z][\w’'-]*){0,2})\s+"
            r"(?:did|does|do)\s+(?P<agent>.+?)\s+"
            r"(?P<predicate>[a-z][\w’'-]*)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        expected_agent = None
        spelling_base = None
        if nominal is not None:
            object_text = nominal.group("object").strip()
            agent_noun = nominal.group("agent_noun").casefold()
            predicates = {
                " ".join(_tokens(item["text"]))
                for item in query_expansions
                if item.get("kind") == "agent_noun_spelling_candidate"
                and agent_noun in _tokens(item.get("evidence", ""))
            }
        elif object_question is not None:
            object_text = ""
            expected_agent = object_question.group("agent").strip()
            spelling_base = object_question.group("predicate").casefold()
            predicates = {spelling_base}
            # A reviewed predicate alignment can license an irregular surface
            # form for the same relation (for example, the query's ``write``
            # may be observed as ``wrote`` in the cited clause). Resolve the
            # query form to its canonical relation first, then admit only the
            # sibling forms that carry that same explicit source license.
            licensed_relations = {
                tuple(_tokens(item.get("evidence", "")))
                for item in query_expansions
                if item.get("kind") == "licensed_predicate"
                and tuple(_tokens(item.get("text", "")))
                    == (spelling_base,)
                and _tokens(item.get("evidence", ""))
            }
            for item in query_expansions:
                if (item.get("kind") == "licensed_predicate"
                        and tuple(_tokens(item.get("evidence", "")))
                            in licensed_relations):
                    form = tuple(_tokens(item.get("text", "")))
                    if len(form) == 1:
                        predicates.add(form[0])
        elif direct is not None:
            object_text = direct.group("object").strip()
            query_predicate = direct.group("predicate").casefold()
            predicates = {query_predicate}
            # Closed irregular morphology is a grammatical alignment, not a
            # synonym guess. The source clause must still fill the requested
            # object role (or provide an explicit passive by-agent) below.
            irregular_base = _base_verb_for_surface((query_predicate,))
            irregular_lemma = (irregular_base[0] if irregular_base else
                               query_predicate)
            predicates.update(
                form for lemma, forms in _IRREGULAR_VERB_PARADIGMS.items()
                if lemma == irregular_lemma for form in forms)
            irregular_family = {
                tuple(_tokens(item.get("text", "")))
                for item in query_expansions
                if item.get("kind") == "irregular_verb_inflection"
                and _tokens(item.get("evidence", ""))
                    == (query_predicate,)
            }
            predicates.update(
                form[0] for form in irregular_family if len(form) == 1)
        else:
            return None
        object_text = re.sub(r"[?!.]+$", "", object_text).strip()
        object_words = _tokens(object_text)
        if object_words and object_words[0] in {"a", "an", "the"}:
            object_text = " ".join(object_text.split()[1:]).strip()
        object_words = _tokens(object_text)
        if (expected_agent is None and not object_words) or not predicates:
            return None
        patient_pattern = (
            r"[^.!?,;:]+?" if expected_agent is not None else
            r"(?:(?i:the|a|an)\s+)?\b"
            + r"\s+".join(re.escape(word) for word in object_words)
            + r"\b")
        object_pattern = rf"(?P<patient>{patient_pattern})"
        agent_pattern = (
            r"(?P<agent>(?-i:[A-Z][\w’'-]*)"
            r"(?:\s+(?:(?i:van|von|de|del|da|di|la|le)\s+)?"
            r"(?-i:[A-Z][\w’'-]*))*)")
        for source in source_sentences:
            if source.get("context_kind") != "assertion":
                continue
            source_text = source.get("text", "")
            source_predicates = set(predicates)
            if spelling_base is not None:
                source_predicates.update(
                    token for token in _tokens(source_text)
                    if _analyze_predicate_spelling(spelling_base, token))
            predicate_pattern = "|".join(
                re.escape(word) for word in sorted(
                    source_predicates, key=lambda value: (-len(value), value)))
            active = re.compile(
                r"^\s*" + agent_pattern
                + rf"\s+(?P<verb>(?:{predicate_pattern}))\b\s+"
                + object_pattern
                + r"(?=\s*(?:[,.;!?]|$)|\s+(?:at|in|from|with|during|on|near)\b)",
                flags=re.IGNORECASE)
            active_match = active.search(source_text)
            if active_match is not None:
                weak_agent_starts = {
                    "a", "an", "any", "each", "every", "first", "many",
                    "one", "second", "several", "some", "that", "the",
                    "these", "this", "those", "there", "they", "we",
                }
                if (_tokens(active_match.group("agent"))[:1]
                        in {(word,) for word in weak_agent_starts}):
                    active_match = None
                elif (expected_agent is not None
                        and _tokens(active_match.group("agent"))
                        != _tokens(expected_agent)):
                    active_match = None
                elif re.search(
                        r"\b(?:not|never|but|and|or|although|unless|instead|rather|except)\b",
                        source_text[active_match.end():], flags=re.IGNORECASE):
                    active_match = None
            if active_match is not None:
                answer = (f"{active_match.group('agent')} "
                          f"{active_match.group('verb')} "
                          f"{active_match.group('patient')}.")
                return {
                    "text": answer,
                    "source_title": source.get("title") or "source",
                    "citation": source.get("citation"),
                    "document_id": source.get("document_id"),
                    "method": "explicit-agent active-clause realization",
                    "stored_as_fact": False,
                }
            # Resolve a leading page-subject pronoun from the exact source
            # title when the question asks for that title's explicit passive
            # agent. Parenthetical title disambiguators are retained in the
            # citation label but omitted for matching the user's entity.
            title = str(source.get("title") or "")
            page_entity = title.split("(", 1)[0].strip()
            if _tokens(page_entity) == object_words:
                # Some encyclopedia lead sentences put a descriptive
                # predicate between the page title and the participle:
                # "Frankenstein; or, The Modern Prometheus is a gothic novel
                # written by Mary Shelley." Match that title-led construction
                # while keeping the agent and predicate explicitly stated.
                page_subject = re.escape(title.strip())
                if not page_subject:
                    page_subject = r"(?!)"
                page_passive = re.compile(
                    r"^\s*(?:(?:the\s+)?" + page_subject
                    + r"|(?:it|this|that))"
                    + r"(?:\s*\([^.!?]{0,120}\))?"
                    + r"(?:;\s*[^.!?]{0,100})?\s+"
                    r"(?:(?:has|have|had)\s+been|is|are|was|were)\s+"
                    r"[^.!?;:]{0,120}?"
                    + rf"(?P<verb>(?:{predicate_pattern}))\b"
                    r"(?:\s+[^.!?;,:]{1,60})?\s+by\s+"
                    r"(?:(?:a|an|the)\s+(?:[a-z][\w’'-]*\s+){0,4}"
                    r"(?:named|called)\s+)?"
                    + agent_pattern
                    + r"(?=\s+(?:at|in|from|with|during|on|near|for|who)\b"
                    r"|\s*[,.;!?]|$)",
                    flags=re.IGNORECASE)
                page_match = page_passive.search(source_text)
                if page_match is not None:
                    tail = source_text[page_match.end():]
                    if not re.search(
                            r"\b(?:not|never|but|and|or|although|unless|"
                            r"instead|rather|except)\b",
                            tail, flags=re.IGNORECASE):
                        active_verb = (direct.group("predicate")
                                       if direct is not None else
                                       page_match.group("verb"))
                        answer = (f"{page_match.group('agent')} "
                                  f"{active_verb} {page_entity}.")
                        return {
                            "text": answer,
                            "source_title": title or "source",
                            "citation": source.get("citation"),
                            "document_id": source.get("document_id"),
                            "method": "exact-title page-subject passive realization",
                            "agent": page_match.group("agent"),
                            "predicate": page_match.group("verb"),
                            "object": page_entity,
                            "stored_as_fact": False,
                        }
            passive = re.compile(
                rf"^\s*{object_pattern}\s+"
                r"(?:(?:has|have|had)\s+been|is|are|was|were)\s+"
                rf"(?P<verb>(?:{predicate_pattern}))\b"
                r"(?P<adjunct>[^.!?;,:]{0,120}?)\s+by\s+"
                + agent_pattern
                + r"(?=\s+(?:at|in|from|with|during|on|near|for)\b|\s*[,.;!?]|$)",
                flags=re.IGNORECASE)
            match = passive.search(source.get("text", ""))
            if match is None:
                continue
            if (expected_agent is not None
                    and _tokens(match.group("agent"))
                    != _tokens(expected_agent)):
                continue
            adjunct = match.group("adjunct")
            # Do not move a verb across a contrast, coordination, or negation
            # while converting passive to active voice.
            if re.search(r"\b(?:not|never|but|and|or|although|unless)\b",
                         adjunct, flags=re.IGNORECASE):
                continue
            tail = source.get("text", "")[match.end():]
            if re.search(r"\b(?:not|never|but|instead|rather|except)\b",
                         tail, flags=re.IGNORECASE):
                continue
            # Restore the exact surface predicate and requested object casing
            # from the source. The object phrase is explicitly anchored at the
            # start of the passive clause.
            answer = (f"{match.group('agent')} "
                      f"{match.group('verb')} "
                      f"{match.group('patient')}.")
            return {
                "text": answer,
                "source_title": source.get("title") or "source",
                "citation": source.get("citation"),
                "document_id": source.get("document_id"),
                "method": "explicit-agent passive-to-active realization",
                "stored_as_fact": False,
            }
        return None

    def research(self, question: str, research_index: Any, *,
                 limit: int = 5) -> ResearchResult:
        """Retrieve sources, answer from stored facts, and suggest new facts.

        Retrieved text is never committed as knowledge here. Sentence-pattern
        matches are returned as cited candidates for explicit review. Verified
        inferred answers may expand retrieval, but are kept separate from source
        passages and their extracted-fact candidates.
        """
        question = _display(question, "question")
        response = self.ask(question)
        query_words = _tokens(question)
        expansions: list[str] = []
        expansion_licenses: list[dict[str, Any]] = []

        def add_expansion(text: str, *, kind: str, evidence: str,
                          sources: Iterable[str] = (),
                          rules: Iterable[str] = ()) -> None:
            expansions.append(text)
            expansion_licenses.append({
                "text": text,
                "kind": kind,
                "evidence": evidence,
                "sources": sorted(set(sources)),
                "rules": sorted(set(rules)),
            })

        # Reuse already licensed question frames as retrieval knowledge. A
        # frame such as "Who was the designer of {object}?" is explicitly
        # grounded to a relation by the teacher; its relation wording can
        # therefore help find source sentences that express the same relation
        # verbally ("... designed ..."). It does not make retrieved claims
        # accepted facts. Exact prefix/suffix matching prevents a frame from
        # expanding unrelated questions.
        question_frames, _induced_frames = self._question_frames_for_ask()
        for frame_key, examples in question_frames.items():
            if not self._question_frame_is_licensed(frame_key, examples):
                continue
            relation = tuple(json.loads(frame_key[0]))
            answer_field, prefix, suffix = frame_key[1:]
            if (not relation or len(query_words) <= len(prefix) + len(suffix)
                    or query_words[:len(prefix)] != prefix
                    or (suffix and query_words[-len(suffix):] != suffix)):
                continue
            if answer_field == "subject" and query_words[:1] not in {
                    ("who",), ("whom",)}:
                continue
            frame_text = " ".join((*prefix, "{bound_entity}", *suffix))
            frame_sources = sorted({
                source for fact in (*self._facts.values(),
                                    *self._negative_facts.values())
                if _tokens(fact.relation) == relation
                for source in fact.sources
            })
            add_expansion(
                " ".join(relation), kind="learned_question_frame",
                evidence=frame_text, sources=frame_sources,
                rules=[f"grounded question frame; answer_field={answer_field}"])

        # Irregular inflectional forms are a grammatical family, not a
        # synonym relation. Use them only to find source wording; each answer
        # still needs a sentence-level role match and citation.
        if query_words and query_words[0] in {
                "who", "whom", "what", "which", "where", "when",
                "why", "how", "explain"}:
            for token in query_words:
                paradigm = next((forms for forms in
                                 _IRREGULAR_VERB_PARADIGMS.values()
                                 if token in forms), None)
                if paradigm is None:
                    continue
                for form in paradigm:
                    if form != token:
                        add_expansion(
                            form, kind="irregular_verb_inflection",
                            evidence=token,
                            rules=["bounded irregular verb paradigm",
                                   "retrieval-only spelling correspondence"])

        # A progressive verb in a question can have a regular past-tense
        # counterpart in the source sentence ("designing" / "designed").
        # This is a spelling-only retrieval aid: it neither licenses a fact
        # relation nor treats surrounding wording such as "responsible for"
        # as equivalent to the predicate. Identity terms and sentence-level
        # evidence still have to match before a source is returned.
        if query_words and query_words[0] in {
                "who", "whom", "what", "which", "where", "when",
                "why", "how"}:
            irregular_past_stems = {
                "be", "begin", "break", "bring", "build", "buy",
                "catch", "choose", "come", "cut", "do", "draw",
                "drink", "drive", "eat", "fall", "feel", "find",
                "fly", "get", "give", "go", "grow", "have", "hear",
                "hold", "keep", "know", "lead", "leave", "let", "lie",
                "lose", "make", "meet", "pay", "put", "read", "ride",
                "rise", "run", "say", "see", "send", "set", "show",
                "sit", "speak", "stand", "take", "teach", "tell",
                "think", "throw", "understand", "wear", "win", "write",
            }
            for token in query_words:
                if len(token) < 6 or not token.endswith("ing"):
                    continue
                base = token[:-3]
                if not base.isalpha() or len(base) < 3:
                    continue
                if base.endswith("y") and len(base) > 2:
                    past = base[:-1] + "ied"
                    rule = "regular progressive -ying to past -ied"
                elif (len(base) > 3 and base[-1] == base[-2]
                      and base[-1] not in "aeiou"
                      and base[:-1] not in irregular_past_stems):
                    past = base + "ed"
                    rule = "regular doubled-consonant progressive to past -ed"
                else:
                    if base in irregular_past_stems:
                        continue
                    past = base + "ed"
                    rule = "regular progressive -ing to past -ed"
                if past == token:
                    continue
                add_expansion(
                    past, kind="regular_question_verb_inflection",
                    evidence=token,
                    rules=[rule, "retrieval-only spelling correspondence"])

        # A common locative question uses an uninflected verb after do/does,
        # while its evidence may use a regular finite form ("work" / "worked").
        # Generate only transparent regular spellings; this changes retrieval
        # terms, never the fact store or the wording of quoted evidence.
        if (len(query_words) >= 3 and query_words[0] == "where"
                and query_words[1] in {"do", "does", "did"}):
            base = query_words[-1]
            irregular = {
                "be", "begin", "break", "bring", "build", "buy", "catch",
                "choose", "come", "cut", "do", "drive", "eat", "fall",
                "feel", "find", "fly", "get", "give", "go", "grow",
                "have", "hear", "hold", "keep", "know", "lead", "leave",
                "let", "lie", "lose", "make", "meet", "pay", "put", "read",
                "rise", "run", "say", "see", "send", "set", "show", "sit",
                "speak", "stand", "take", "teach", "tell", "think", "throw",
                "understand", "wear", "win", "write",
            }
            if base.isalpha() and len(base) >= 2 and base not in irregular:
                context, removed = _predicate_spelling_class(base)
                stem = base[:-1] if context == "final-e" else base
                plural = (base + "es" if context in {"sibilant", "final-o"}
                          else base + "s")
                past = base + "ed"
                progressive = base + "ing"
                if context == "final-e":
                    past = base + "d"
                    progressive = stem + "ing"
                elif context == "consonant-y":
                    stem = base[:-1]
                    plural, past = stem + "ies", stem + "ied"
                elif context == "cvc-double":
                    doubled = base + base[-1]
                    past, progressive = doubled + "ed", doubled + "ing"
                elif context == "final-c":
                    past, progressive = base + "ked", base + "king"
                for form in sorted({plural, past, progressive} - {base}):
                    add_expansion(
                        form, kind="regular_question_verb_inflection",
                        evidence=f"where-question verb: {base}",
                        rules=[f"{context}; removed={removed or 'none'}"])

        # A bounded agent-noun question can retrieve evidence written with its
        # related verb ("designer" -> "designed", "creator" -> "created").
        # This is only a spelling-based retrieval proposal: it neither asserts
        # that the noun and verb are semantically equivalent nor creates a
        # fact. The cited source sentence remains the evidence to inspect.
        if (len(query_words) >= 6
                and query_words[:3] in {
                    ("who", "was", "the"), ("who", "is", "the")}):
            for of_index in range(4, len(query_words) - 1):
                nominal = query_words[3:of_index]
                if len(nominal) != 1 or query_words[of_index] != "of":
                    continue
                noun = nominal[0]
                base = ""
                rule = ""
                if noun.endswith("er") and len(noun) > 3:
                    base = noun[:-2]
                    rule = "agent noun -er suffix removal"
                elif noun.endswith("or") and len(noun) > 3:
                    base = noun[:-2]
                    rule = "agent noun -or suffix removal"
                if not base:
                    continue
                verb_bases = {base}
                # Silent-e verb stems (create/creator, write/writer) lose
                # their final e in the corresponding agent noun.
                verb_bases.add(base + "e")
                for verb_base in sorted(verb_bases):
                    context, removed = _predicate_spelling_class(verb_base)
                    stem = (verb_base[:-1] if context == "final-e"
                            else verb_base)
                    plural = (verb_base + "es"
                              if context in {"sibilant", "final-o"}
                              else verb_base + "s")
                    past = verb_base + "ed"
                    progressive = verb_base + "ing"
                    if context == "final-e":
                        past = verb_base + "d"
                        progressive = stem + "ing"
                    elif context == "consonant-y":
                        stem = verb_base[:-1]
                        plural, past = stem + "ies", stem + "ied"
                    elif context == "cvc-double":
                        doubled = verb_base + verb_base[-1]
                        past, progressive = doubled + "ed", doubled + "ing"
                    elif context == "final-c":
                        past, progressive = verb_base + "ked", verb_base + "king"
                    for form in sorted({verb_base, plural, past, progressive}):
                        if form != noun:
                            add_expansion(
                                form, kind="agent_noun_spelling_candidate",
                                evidence=f"agent noun in question: {noun}",
                                rules=[f"{rule}; {context}; "
                                       f"removed={removed or 'none'}"])

        for alias, record in self._entity_alias_records().items():
            if any(query_words[index:index + len(alias)] == alias
                   for index in range(len(query_words) - len(alias) + 1)):
                add_expansion(record["entity"], kind=record["kind"],
                              evidence=" ".join(alias),
                              sources=record["sources"],
                              rules=([record["context"]]
                                     if record.get("context") else ()))
        # Use only source-grounded, licensed predicate frames. A phrase that
        # the teacher aligned to a canonical relation can retrieve passages
        # using that relation label or another observed phrase for the same
        # frame; unlearned words never trigger semantic expansion.
        predicates_by_relation: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        predicate_sources_by_relation: dict[
            tuple[str, ...], dict[tuple[str, ...], set[str]]
        ] = {}
        for key, examples in self._fact_pattern_examples.items():
            if self._fact_pattern_is_licensed(key, examples):
                predicates = self._fact_pattern_predicates.get(key, set())
                predicates_by_relation.setdefault(key[1], set()).update(predicates)
                by_form = predicate_sources_by_relation.setdefault(key[1], {})
                for predicate in predicates:
                    sources_by_pair = self._fact_pattern_predicate_sources.get(
                        key, {}).get(predicate, {})
                    by_form.setdefault(predicate, set()).update(
                        source for pair_sources in sources_by_pair.values()
                        for source in pair_sources)
        for relation_tokens, observed in predicates_by_relation.items():
            predicates, spelling_evidence = self._predicate_forms_for_relation(
                relation_tokens, observed)
            triggers = predicates

            def query_uses_licensed_predicate(
                    phrase: tuple[str, ...]) -> bool:
                if not phrase:
                    return False
                if any(query_words[index:index + len(phrase)] == phrase
                       for index in range(len(query_words) - len(phrase) + 1)):
                    return True
                # The question commonly uses a bare verb after do-support
                # ("What did X investigate?") while examples store past tense
                # ("X investigated Y"). Treat that regular spelling as a
                # trigger for the already licensed predicate family.
                return (len(phrase) == 1 and any(
                    _analyze_predicate_spelling(query_word, phrase[0])
                    or _analyze_predicate_spelling(phrase[0], query_word)
                    for query_word in query_words))

            if any(query_uses_licensed_predicate(phrase)
                   for phrase in triggers):
                canonical_sources = {
                    source for form_sources in predicate_sources_by_relation[
                        relation_tokens].values()
                    for source in form_sources
                }
                forms = set(predicates) | {relation_tokens}
                for phrase in sorted(forms):
                    sources = set(predicate_sources_by_relation[
                        relation_tokens].get(phrase, set()))
                    generated = spelling_evidence.get(phrase, {})
                    for support in generated.get("support", []):
                        sources.update(support.get("sources", []))
                    if not sources:
                        sources.update(canonical_sources)
                    add_expansion(
                        " ".join(phrase), kind="licensed_predicate",
                        evidence=" ".join(relation_tokens), sources=sources)
        derived_context: list[dict[str, Any]] = []
        if response.status == "answered":
            proof_rows = {repr(proof): proof
                          for proof in response.inference_proofs or []}
            for proof in (proof_rows[key] for key in sorted(proof_rows)):
                conclusion = dict(proof.get("conclusion", {}))
                if not all(conclusion.get(field) for field in
                           ("subject", "relation", "object")):
                    continue
                leaves = self._inference_fact_leaves(proof)
                sources = sorted({source for leaf in leaves
                                  for source in leaf.get("sources", [])})
                scopes = {tuple(tuple(pair) for pair in
                                leaf.get("qualifiers", ()))
                          for leaf in leaves}
                qualifier_scope = (next(iter(scopes))
                                   if len(scopes) == 1 else ())
                rules = sorted({rule["rule_id"]
                                for rule in self._inference_rule_steps(proof)})
                derived_context.append({
                    "conclusion": conclusion, "proof": proof,
                    "sources": sources, "rules": rules,
                    "qualifiers": [list(pair) for pair in qualifier_scope],
                })
                for field in ("subject", "relation", "object"):
                    add_expansion(
                        conclusion[field], kind="verified_inference",
                        evidence=(f"{conclusion['subject']} "
                                  f"{conclusion['relation']} "
                                  f"{conclusion['object']}"),
                        sources=sources, rules=rules)
                for name, value in qualifier_scope:
                    add_expansion(
                        value, kind="verified_inference",
                        evidence=(f"{conclusion['subject']} "
                                  f"{conclusion['relation']} "
                                  f"{conclusion['object']}"),
                        sources=sources, rules=rules)
        # Keep the original question intact; only licensed aliases and
        # independently checked derived conclusions may expand retrieval.
        retrieval_query = " ".join([question, *sorted(set(expansions))])
        acronym_search_limit = limit
        explanatory_query = bool(
            query_words and query_words[0] in {"how", "why", "explain"})
        if (re.search(r"\b[A-Z][A-Z0-9]{1,}\b", question)
                or explanatory_query):
            # Acronym-specific questions often have many high-scoring lexical
            # matches from unrelated papers. Explanatory questions can also
            # lose a direct source among the first few lexical hits. Retrieve
            # a wider candidate set, then rank using sentence-level context.
            document_count = research_index.document_count()
            acronym_search_limit = max(limit, min(document_count, 50))
        hits = research_index.search(
            retrieval_query, limit=acronym_search_limit, context_chars=240)
        extractive = research_index.summarize(
            question, limit=acronym_search_limit, per_document=1,
            retrieval_terms=sorted(set(expansions)),
            expansion_licenses=expansion_licenses,
            precomputed_hits=hits)
        source_sentences = [asdict(sentence)
                            for sentence in extractive.sentences]
        # A named entity in the question is an identity constraint, not just
        # another retrieval keyword. Without this gate, a sentence about a
        # different person can win on shared topical words (for example,
        # Einstein's Nobel Prize sentence for a Marie Curie question).
        capitalized = list(re.finditer(
            r"\b[A-Z][\w’'-]*\b", question, flags=re.UNICODE))
        named_anchor_tokens: set[str] = set()
        first_word = next(re.finditer(r"\w+", question), None)
        for match in capitalized:
            if first_word is not None and match.start() == first_word.start():
                continue
            term = match.group(0)
            if term.casefold() in {"i"}:
                continue
            named_anchor_tokens.update(_tokens(term))
        if named_anchor_tokens:
            source_sentences = [
                sentence for sentence in source_sentences
                if named_anchor_tokens.issubset(set(_tokens(
                    sentence.get("text", ""))))
            ]
        question_seeks_example = bool(
            set(query_words) & {"example", "examples", "sample", "samples",
                                "illustration", "illustrative", "template",
                                "templates", "pattern", "patterns"})
        factual_wh_question = bool(
            query_words and query_words[0] in {
                "who", "whom", "what", "which", "where", "when", "why"}
            and not question_seeks_example)
        if factual_wh_question and any(
                sentence.get("context_kind") == "example"
                for sentence in source_sentences):
            # An illustrative sentence may mention the same entity and even
            # quote the question, but it is not evidence for a factual answer.
            assertion_documents = {
                sentence.get("document_id") for sentence in source_sentences
                if sentence.get("context_kind") == "assertion"}
            source_sentences = [
                sentence for sentence in source_sentences
                if sentence.get("context_kind") == "assertion"]
            hits = [hit for hit in hits
                    if hit.document_id in assertion_documents]
        # An inverse object question explicitly asks for an agent's action.
        # Entity-only overlap must not turn a sentence about a different
        # action into apparent evidence ("invent" must not retrieve
        # "created" just because both mention Guido and Python).
        inverse_action = re.fullmatch(
            r"\s*(?:what|which(?:\s+[a-z][\w’'-]*){0,2})\s+"
            r"(?:did|does|do)\s+(?P<agent>.+?)\s+"
            r"(?P<predicate>[a-z][\w’'-]*)\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        if inverse_action is not None:
            requested_agent = set(_tokens(inverse_action.group("agent")))
            requested_predicate = inverse_action.group("predicate").casefold()
            licensed_predicate_phrases = tuple(
                tuple(_tokens(record.get("text", "")))
                for record in expansion_licenses
                if record.get("kind") == "licensed_predicate"
                and _tokens(record.get("text", "")))

            def action_is_supported(text: str) -> bool:
                words = _tokens(text)
                if not requested_agent.issubset(set(words)):
                    return True
                if any(
                    word == requested_predicate
                    or _analyze_predicate_spelling(requested_predicate, word)
                    for word in words):
                    return True
                # A reviewed corpus alignment can license a different surface
                # predicate for this action. Reuse only the forms that the
                # current question activated above; an unlearned synonym still
                # cannot turn entity overlap into evidence for an answer.
                return any(
                    words[index:index + len(phrase)] == phrase
                    for phrase in licensed_predicate_phrases
                    for index in range(len(words) - len(phrase) + 1))

            source_sentences = [sentence for sentence in source_sentences
                                if action_is_supported(sentence.get("text", ""))]
            hits = [hit for hit in hits if action_is_supported(hit.snippet)]
        # Acronyms in a question are identity-bearing terms. A sentence about
        # language learning in general cannot answer a question about CRMS
        # merely because it shares words like "learn" and "language".
        acronym_anchors = {
            token.casefold() for token in re.findall(
                r"\b[A-Z][A-Z0-9]{1,}\b", question)
            if token.casefold() not in {"who", "what", "where", "when", "why"}
        }
        if acronym_anchors:
            def contains_acronyms(text: str) -> bool:
                return acronym_anchors.issubset(set(_tokens(text)))

            def source_has_acronym_context(
                    document_id: str, title: str, text: str,
                    start: int | None, end: int | None) -> bool:
                if contains_acronyms(text) or contains_acronyms(title):
                    return True
                try:
                    document = research_index.document(document_id)
                except (AttributeError, KeyError):
                    return False
                if start is None or end is None:
                    return False
                left = document.text.rfind("\n\n", 0, start) + 2
                right = document.text.find("\n\n", end)
                if right < 0:
                    right = len(document.text)
                paragraph = document.text[left:right]
                if contains_acronyms(paragraph):
                    return True
                previous_blocks = document.text[:left].rsplit("\n\n", 2)
                heading = next((block for block in reversed(previous_blocks)
                                if re.match(r"\s*#{1,6}\s+", block)), "")
                return contains_acronyms(heading)

            def sentence_start(sentence: Mapping[str, Any]) -> tuple[
                    int | None, int | None]:
                citation = str(sentence.get("citation", ""))
                match = re.search(r"&chars=(\d+):(\d+)", citation)
                return ((int(match.group(1)), int(match.group(2)))
                        if match else (None, None))

            source_sentences = [
                sentence for sentence in source_sentences
                if source_has_acronym_context(
                    str(sentence.get("document_id", "")),
                    str(sentence.get("title", "")),
                    str(sentence.get("text", "")),
                    *sentence_start(sentence))]
            hits = [hit for hit in hits if source_has_acronym_context(
                hit.document_id, hit.title, hit.snippet, hit.start, hit.end)]
        evidence_terms = set(query_words) - {
            "what", "which", "who", "whom", "where", "when", "why", "how",
            "does", "do", "did", "is", "are", "was", "were", "the", "a",
            "an", "of", "in", "for", "to", "and", "or", "say", "says",
            "about", "please", "me", "tell", "explain", "describe",
        }
        if evidence_terms:
            source_sentences.sort(
                key=lambda sentence: len(evidence_terms.intersection(
                    set(_tokens(sentence.get("text", ""))))), reverse=True)
            hits.sort(
                key=lambda hit: len(evidence_terms.intersection(
                    set(_tokens(hit.snippet)))), reverse=True)
        structured_list_answer: dict[str, Any] | None = None
        query_count_words = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        list_question = bool(
            (query_words[:2] in {("what", "are"), ("which", "are")}
             or query_words[:1] in {("list",), ("name",)}))
        list_number = next((int(token) if token.isdigit()
                            else query_count_words[token]
                            for token in query_words
                            if token.isdigit() or token in query_count_words), None)
        if list_question and response.status != "answered":
            query_content = set(query_words) - {
                "what", "which", "are", "is", "the", "a", "an", "of",
                "in", "for", "to", "and", "or", "list", "name",
                *query_count_words,
            }
            for hit in hits:
                document = research_index.document(hit.document_id)
                if document.pages:
                    continue
                lines = document.text.splitlines(keepends=True)
                line_starts = []
                cursor = 0
                for line in lines:
                    line_starts.append(cursor)
                    cursor += len(line)
                for index, header_line in enumerate(lines[:-2]):
                    separator = lines[index + 1].strip()
                    if ("|" not in header_line
                            or not re.fullmatch(
                                r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?",
                                separator)):
                        continue

                    def cells(line: str) -> list[str]:
                        value = line.strip()
                        if value.startswith("|"):
                            value = value[1:]
                        if value.endswith("|"):
                            value = value[:-1]
                        return [cell.strip() for cell in value.split("|")]

                    headers = cells(header_line)
                    header_words = set(_tokens(" ".join(headers)))
                    normalized_query = set(query_content)
                    normalized_query.update(
                        word[:-1] for word in query_content
                        if len(word) > 4 and word.endswith("s"))
                    if not header_words.intersection(normalized_query):
                        continue
                    end_index = index + 2
                    table_rows = []
                    while end_index < len(lines) and "|" in lines[end_index]:
                        row = cells(lines[end_index])
                        if len(row) == len(headers):
                            table_rows.append(row)
                        end_index += 1
                    if not table_rows or (list_number is not None
                                          and len(table_rows) != list_number):
                        continue
                    table_start = line_starts[index]
                    table_end = (line_starts[end_index]
                                 if end_index < len(lines)
                                 else len(document.text))
                    table_text = document.text[table_start:table_end].rstrip()
                    table_hit = SearchHit(
                        document.document_id, document.title,
                        document.location, hit.score, table_text,
                        table_start, table_start + len(table_text),
                        tuple(sorted(header_words.intersection(
                            set(_tokens(question))))))
                    citation = research_index.citation(table_hit)
                    rendered_rows = []
                    for row in table_rows:
                        label = re.sub(r"[`*_]", "", row[0]).strip()
                        details = []
                        for header, value in zip(headers[1:], row[1:]):
                            clean_header = re.sub(r"[`*_]", "", header).strip()
                            clean_value = re.sub(r"[`*_]", "", value).strip()
                            if clean_header and clean_value:
                                details.append(f"{clean_header}: {clean_value}")
                        rendered_rows.append(
                            f"- {label}" + (" — " + "; ".join(details)
                                             if details else ""))
                    structured_list_answer = {
                        "text": (f"The source lists {len(table_rows)} "
                                 "routes:\n" + "\n".join(rendered_rows)),
                        "source_title": document.title or "source",
                        "citation": citation,
                        "document_id": document.document_id,
                        "method": "structured source-table realization",
                        "stored_as_fact": False,
                    }
                    source_sentences = [asdict(SummarySentence(
                        table_text, citation, document.document_id,
                        document.title, document.location, hit.score,
                        table_hit.matched_terms, context_kind="assertion"))]
                    hits = [table_hit]
                    break
                if structured_list_answer is not None:
                    break
        contextual_explanation: dict[str, Any] | None = None
        explanation_question = bool(
            query_words and query_words[0] in {"how", "why", "explain"})
        if (explanation_question and response.status != "answered"
                and hits):
            # The best matching sentence can be only the last clause of an
            # explanation. For how/why questions, recover its containing
            # paragraph when it independently matches multiple meaningful
            # query terms. This preserves the source's explanation without
            # expanding an unrelated generic title match.
            explanation_terms = set(query_words) - {
                "how", "why", "explain", "does", "do", "did", "is",
                "are", "was", "were", "the", "a", "an", "of", "in",
                "for", "to", "and", "or", "what", "with", "before",
                "after", "from", "on", "by", "it", "this", "that",
                "work", "works", "working", "needed", "need",
            }
            for hit in hits:
                document = research_index.document(hit.document_id)
                if document.pages or hit.start is None or hit.end is None:
                    continue
                left = document.text.rfind("\n\n", 0, hit.start) + 2
                right = document.text.find("\n\n", hit.end)
                if right < 0:
                    right = len(document.text)
                raw_paragraph = document.text[left:right]
                if "```" in raw_paragraph:
                    continue
                relative_hit_start = hit.start - left
                line_start = raw_paragraph.rfind("\n", 0, relative_hit_start) + 1
                line_end = raw_paragraph.find("\n", relative_hit_start)
                if line_end < 0:
                    line_end = len(raw_paragraph)
                line = raw_paragraph[line_start:line_end]
                if re.match(r"\s*[-*+]\s+", line):
                    raw_paragraph = line
                    left += line_start
                paragraph_start = left + len(raw_paragraph) - len(
                    raw_paragraph.lstrip())
                paragraph = raw_paragraph.strip()
                heading = re.match(r"#{1,6}\s+[^\n]*(?:\n|$)", paragraph)
                if heading:
                    paragraph = paragraph[heading.end():]
                    paragraph_start += heading.end()
                    leading = len(paragraph) - len(paragraph.lstrip())
                    paragraph = paragraph.lstrip()
                    paragraph_start += leading
                if len(paragraph) < 100:
                    continue
                def normalized_explanation_terms(value: str) -> set[str]:
                    terms = set(_tokens(value))
                    return {
                        term[:-1] if (len(term) > 4 and term.endswith("s")
                                      and not term.endswith("ss")) else term
                        for term in terms
                    }

                normalized_query_terms = normalized_explanation_terms(
                    " ".join(explanation_terms))
                ordinal_focus = normalized_query_terms & {
                    "first", "second", "third", "fourth", "fifth",
                    "sixth", "seventh", "eighth", "ninth", "tenth",
                    "initial", "final", "last",
                }
                relevant_sentences = []
                for sentence_index, (sentence_start, sentence_end) in enumerate(
                        _sentence_spans(paragraph)):
                    sentence_text = paragraph[sentence_start:sentence_end].strip()
                    if len(sentence_text) < 35 or len(sentence_text) > 1200:
                        continue
                    absolute_start = paragraph_start + sentence_start
                    sentence_context = _sentence_context_kind(
                        sentence_text, document.text, absolute_start)
                    if sentence_context != "assertion":
                        continue
                    sentence_terms = normalized_explanation_terms(sentence_text)
                    if ordinal_focus and not ordinal_focus.issubset(sentence_terms):
                        continue
                    overlap = len(normalized_query_terms & sentence_terms)
                    if overlap < 2:
                        continue
                    relevant_sentences.append((
                        overlap, abs(absolute_start - (hit.start or 0)),
                        sentence_index, absolute_start,
                        absolute_start + len(sentence_text), sentence_text))
                if not relevant_sentences:
                    continue
                # Keep explanation retrieval extractive and small. A
                # single-newline wiki page can look like one paragraph to the
                # paragraph scanner; selecting independently matching
                # sentences prevents returning the whole article.
                anchor = min(relevant_sentences,
                             key=lambda row: (-row[0], row[1], row[3]))
                nearby = sorted(
                    (row for row in relevant_sentences
                     if row != anchor and row[0] >= 1
                     and abs(row[2] - anchor[2]) <= 2),
                    key=lambda row: (abs(row[2] - anchor[2]), row[3]))
                selected = [anchor, *nearby[:2]]
                selected.sort(key=lambda row: row[3])
                answer_text = "\n".join(row[5] for row in selected)
                if len(answer_text) > 1800:
                    selected = selected[:1]
                    answer_text = selected[0][5]
                citation_start = min(row[3] for row in selected)
                citation_end = max(row[4] for row in selected)
                cited_excerpt = document.text[citation_start:citation_end]
                paragraph_hit = SearchHit(
                    hit.document_id, hit.title, hit.location, hit.score,
                    cited_excerpt, citation_start, citation_end,
                    tuple(sorted(set(explanation_terms)
                                 & set(_tokens(answer_text)))))
                contextual_explanation = {
                    "text": answer_text,
                    "source_title": document.title or "source",
                    "citation": research_index.citation(paragraph_hit),
                    "document_id": document.document_id,
                    "method": "bounded matching-sentence realization",
                    "stored_as_fact": False,
                }
                source_sentences = [asdict(SummarySentence(
                    answer_text, contextual_explanation["citation"],
                    document.document_id, document.title, document.location,
                    hit.score, paragraph_hit.matched_terms,
                    context_kind="assertion"))]
                hits = [paragraph_hit]
                break
        definition_question = re.fullmatch(
            r"\s*what\s+(?:is|are)\s+(?P<entity>[A-Z][A-Z0-9]{1,})\s*[?!.]?\s*",
            question, flags=re.IGNORECASE)
        if definition_question is not None:
            entity = re.escape(definition_question.group("entity"))
            definition_pattern = re.compile(
                rf"\b{entity}\b\s*(?:\([^)]{{1,160}}\))?\s+"
                r"(?:(?:is|are)\s+(?:a|an|the)\b|"
                r"means\b|stands\s+for\b|refers\s+to\b)",
                flags=re.IGNORECASE)
            source_sentences = [sentence for sentence in source_sentences
                                if definition_pattern.search(
                                    sentence.get("text", ""))]
            hits = [hit for hit in hits if definition_pattern.search(hit.snippet)]
            # Definition sentences can be buried in a large document whose
            # title or other passages rank higher for the acronym alone. Do a
            # bounded, corpus-local scan of documents that contain the exact
            # acronym and promote only a sentence that explicitly defines it.
            if not source_sentences:
                definition_hits = research_index.search(
                    definition_question.group("entity"),
                    limit=research_index.document_count(), context_chars=240)
                for definition_hit in definition_hits:
                    document = research_index.document(
                        definition_hit.document_id)
                    if document.pages:
                        continue
                    for start, end in _sentence_spans(document.text):
                        sentence_text = document.text[start:end].strip()
                        if not definition_pattern.search(sentence_text):
                            continue
                        exact_start = start + len(document.text[start:end]) - len(
                            document.text[start:end].lstrip())
                        exact_end = exact_start + len(sentence_text)
                        exact_hit = SearchHit(
                            document.document_id, document.title,
                            document.location, definition_hit.score,
                            document.text[exact_start:exact_end], exact_start,
                            exact_end,
                            (definition_question.group("entity").casefold(),))
                        citation = research_index.citation(exact_hit)
                        source_sentences = [asdict(SummarySentence(
                            sentence_text, citation, document.document_id,
                            document.title, document.location,
                            definition_hit.score,
                            exact_hit.matched_terms))]
                        hits = [exact_hit]
                        break
                    if source_sentences:
                        break
        # Numbered names and measurements are identity-bearing query terms.
        # Do not answer a question about one numbered entity from a sentence
        # about another entity merely because the surrounding category words
        # overlap (for example, "Nacre City 9999" vs "Nacre City 0133").
        query_numbers = set(re.findall(r"\d+", question))
        if query_numbers:
            def has_requested_number(text: str) -> bool:
                return bool(query_numbers & set(re.findall(r"\d+", text)))
            hits = [hit for hit in hits if has_requested_number(hit.snippet)]
            source_sentences = [sentence for sentence in source_sentences
                                if has_requested_number(sentence.get("text", ""))]
        passages: list[dict[str, Any]] = []
        question_terms = set(query_words)
        candidates: dict[tuple[str, str, str, str, bool], FactCandidate] = {}
        for hit in hits:
            citation = research_index.citation(hit)
            matched_question_terms = sorted(
                term for term in hit.matched_terms if term in question_terms)
            matched_expansion_terms = sorted(
                term for term in hit.matched_terms if term not in question_terms)
            matched_expansion_set = set(matched_expansion_terms)
            matched_expansion_licenses = []
            for license_record in expansion_licenses:
                matching_terms = sorted(
                    set(_tokens(license_record["text"])) & matched_expansion_set)
                if matching_terms:
                    matched_expansion_licenses.append({
                        **license_record, "matched_terms": matching_terms})
            passages.append({
                "title": hit.title,
                "location": hit.location,
                "citation": citation,
                "excerpt": research_index.resolve_citation(citation),
                "matched_question_terms": matched_question_terms,
                "matched_licensed_expansion_terms": matched_expansion_terms,
                "matched_expansion_licenses": matched_expansion_licenses,
            })
            # Source code is valuable retrieval evidence for programming
            # questions, but ordinary sentence-frame extraction must not
            # interpret assertions, string literals, or test fixtures as
            # natural-language facts. Code needs a syntax-aware learning path.
            if _is_code_source(hit.location):
                continue
            # Split at sentence boundaries, including punctuation followed by
            # closing quotation marks. Keep offsets so example framing in the
            # surrounding source can be checked before proposing a fact.
            source_document = research_index.document(hit.document_id)
            for sentence_start, sentence_end in _sentence_spans(hit.snippet):
                sentence = hit.snippet[sentence_start:sentence_end].strip()
                absolute_start = hit.start + sentence_start
                if _sentence_context_kind(
                        sentence, source_document.text, absolute_start) == "example":
                    continue
                for candidate in self.propose_facts_from_hit(
                        sentence, research_index=research_index, hit=hit):
                    fact_store = self._facts if candidate.polarity else self._negative_facts
                    if self._fact_key(candidate.subject, candidate.relation,
                                      candidate.object,
                                      candidate.qualifiers) in fact_store:
                        continue
                    key = (candidate.subject.casefold(), candidate.relation,
                           candidate.object.casefold(), candidate.source,
                           candidate.polarity, candidate.qualifiers)
                    candidates[key] = candidate
                # If no learned frame recognized this sentence, offer a
                # separate heuristic path for simple capitalized-name claims.
                # It never bypasses citation review or writes to the fact store.
                if not any(candidate.sentence == sentence
                           and candidate.source == citation
                           for candidate in candidates.values()):
                    for candidate in self._discover_surface_relation_candidates(
                            sentence, source=citation,
                            research_index=research_index):
                        fact_store = (self._facts if candidate.polarity
                                      else self._negative_facts)
                        if self._fact_key(candidate.subject, candidate.relation,
                                          candidate.object,
                                          candidate.qualifiers) in fact_store:
                            continue
                        key = (candidate.subject.casefold(), candidate.relation,
                               candidate.object.casefold(), candidate.source,
                               candidate.polarity, candidate.qualifiers)
                        candidates[key] = candidate

        # An unrelated extractable claim must not turn every research query
        # into a review interruption. Keep all candidates visible below, but
        # make review the primary status only when its claim touches the
        # query's content words.
        review_stopwords = {"a", "an", "and", "are", "at", "did", "do",
                            "does", "for", "from", "how", "in", "is", "of",
                            "on", "the", "to", "was", "what", "when",
                            "where", "which", "who", "whom", "why", "with"}
        content_terms = set(query_words) - review_stopwords
        expansion_words = {
            word for phrase in expansions for word in _tokens(phrase)
        }

        def phrase_occurs(phrase: tuple[str, ...], words: tuple[str, ...]) -> bool:
            return bool(phrase) and any(
                words[index:index + len(phrase)] == phrase
                for index in range(len(words) - len(phrase) + 1))

        def phrase_occurs_with_one_regular_base(
                phrase: tuple[str, ...], words: tuple[str, ...]) -> bool:
            """Match one regular past/present token in a compound predicate."""
            if not phrase or len(phrase) > len(words):
                return False
            for start in range(len(words) - len(phrase) + 1):
                changes = 0
                for stored, asked in zip(
                        phrase, words[start:start + len(phrase)]):
                    if stored == asked:
                        continue
                    bare_forms = set()
                    if stored.endswith("ied") and len(stored) > 3:
                        bare_forms.add(stored[:-3] + "y")
                    if stored.endswith("ed") and len(stored) > 2:
                        bare_forms.update({stored[:-2], stored[:-2] + "e"})
                        if (len(stored) > 4 and stored[-3] == stored[-4]
                                and stored[-3].isalpha()):
                            bare_forms.add(stored[:-3])
                    if stored.endswith("s") and len(stored) > 1:
                        bare_forms.add(stored[:-1])
                    if asked not in bare_forms:
                        break
                    changes += 1
                    if changes > 1:
                        break
                else:
                    if changes == 1:
                        return True
            return False

        def candidate_touches_question(candidate: FactCandidate) -> bool:
            subject_object = (set(_tokens(candidate.subject))
                              | set(_tokens(candidate.object)))
            relation_words = _tokens(candidate.relation)
            entity_match = bool(content_terms & subject_object)
            if not entity_match:
                return False
            definition_subject = re.fullmatch(
                r"\s*what\s+is\s+(?:the\s+)?(?P<entity>.+?)\s*[?!.]?\s*",
                question, flags=re.IGNORECASE)
            if (definition_subject is not None
                    and relation_words == _tokens("is-a")
                    and _tokens(candidate.subject)
                    == _tokens(definition_subject.group("entity"))):
                return True
            if any(item.get("kind") == "relation_type_schema_discovery"
                   for item in candidate.language_evidence):
                # For a schema claim, the question must name both its
                # relation and its proposed type; lexical proximity to only
                # one side is not enough to interrupt the user for review.
                relation_terms = set(_tokens(candidate.subject))
                type_terms = set(_tokens(candidate.object))
                if (relation_terms & content_terms
                        and type_terms & content_terms):
                    return True
                return False
            expanded_query = tuple(dict.fromkeys(
                (*query_words, *sorted(expansion_words))))
            if phrase_occurs(relation_words, query_words) or phrase_occurs(
                    relation_words, expanded_query):
                return True
            if (len(relation_words) > 1
                    and phrase_occurs_with_one_regular_base(
                        relation_words, query_words)):
                return True
            # A single-token canonical relation can match a regular inflected
            # surface form. Do not match one word inside an unrelated
            # multiword relation ("matters" must not select "matters if").
            if len(relation_words) == 1:
                base = relation_words[0]
                for surface in content_terms | expansion_words:
                    if (base == surface
                            or _analyze_predicate_spelling(base, surface)
                            or _analyze_predicate_spelling(surface, base)):
                        return True
            # Locative do-support questions omit the preposition after the
            # verb; their relation phrase must still end in a known locative.
            if (len(relation_words) > 1 and len(query_words) >= 4
                    and query_words[0] == "where"
                    and query_words[1] in {"do", "does", "did"}
                    and relation_words[-1] in {"at", "in", "near"}):
                base = query_words[-1]
                surface = relation_words[0]
                if (base == surface
                        or _analyze_predicate_spelling(base, surface)
                        or _analyze_predicate_spelling(surface, base)):
                    return True
            return False

        relevant_candidates = [candidate for candidate in candidates.values()
                               if candidate_touches_question(candidate)]
        # If retrieval finds a claim about an entity named in the question,
        # review that claim instead of interrupting the user with every other
        # claim that happens to share its relation. This also makes numbered
        # review stable and useful for questions about one member of a corpus.
        entity_candidates = [
            candidate for candidate in relevant_candidates
            if ((set(_tokens(candidate.subject))
                 | set(_tokens(candidate.object))) & content_terms)
        ]
        if entity_candidates:
            relevant_candidates = entity_candidates
        # A common relation/object word may match many records in a large
        # corpus. Prefer candidates whose quoted sentence matches the most
        # distinct question content terms; otherwise a lexically earlier
        # neighboring entity can be offered for review despite an exact-ID
        # match elsewhere in the retrieved set.
        if relevant_candidates:
            def sentence_overlap(candidate: FactCandidate) -> int:
                return len(set(_tokens(candidate.sentence)) & content_terms)
            strongest_overlap = max(map(sentence_overlap, relevant_candidates))
            relevant_candidates = [
                candidate for candidate in relevant_candidates
                if sentence_overlap(candidate) == strongest_overlap]
        if response.status == "answered":
            status = "answered"
        elif relevant_candidates:
            status = "needs_review"
        elif passages:
            status = "sources_found"
        else:
            status = "unknown"
        realized_answer = None
        if response.status != "answered":
            realized_answer = (structured_list_answer or contextual_explanation or
                               self._realize_question_from_passive_source(
                                   question, source_sentences,
                                   expansion_licenses))
        # A successful answer stands on its own. Unrelated source candidates
        # belong to review flows, not as a trailing block after that answer.
        returned_candidates = (
            relevant_candidates if status == "needs_review" else
            [] if status == "answered" else
            [candidates[key] for key in sorted(candidates)])
        return ResearchResult(
            status, response, passages, returned_candidates,
            derived_context=derived_context,
            query_expansions=expansion_licenses,
            source_sentences=source_sentences,
            realized_answer=realized_answer, query=question)

    def render_research(self, result: ResearchResult) -> str:
        """Render research results without treating candidates as established facts."""
        lines: list[str] = []
        if result.response and result.response.status == "answered":
            lines.append(self.render(result.response))
        elif result.status == "needs_review":
            lines.append("I found a source-backed candidate related to this question. It remains unaccepted; review the proposed claim below before I use it.")
        elif result.status == "sources_found":
            lines.append(
                "I found source sentences related to this question. They are "
                "quoted as evidence; they have not been converted into accepted "
                "facts or interpreted beyond their wording. A reusable relation "
                "frame can be taught with /teach-fact SUBJECT|RELATION|OBJECT|"
                "SOURCE QUERY|PREDICATE PHRASE|positive/negative.")
        elif result.response is not None and result.response.request:
            lines.append(result.response.request)
        else:
            lines.append(
                "I couldn't answer this from the supplied sources. Add a source "
                "or teach a fact-backed example with /teach-fact.")
        for context in result.derived_context or []:
            conclusion = context["conclusion"]
            lines.append(
                "Verified derived query context used for retrieval (not extracted "
                "from the retrieved passage): "
                f"{conclusion['subject']} — {conclusion['relation']} → "
                f"{conclusion['object']}"
                + (("; context: " + ", ".join(
                    f"{name}={value}" for name, value in context.get("qualifiers", [])))
                   if context.get("qualifiers") else "")
                + f"; rules: {', '.join(context['rules'])}; "
                f"supporting fact sources: {', '.join(context['sources'])}.")
        if result.source_sentences:
            lines.append("Best matching source sentences (wording unchanged):")
            for sentence in result.source_sentences:
                label = sentence["title"]
                if sentence.get("location"):
                    label += f" ({sentence['location']})"
                if sentence.get("page_number") is not None:
                    label += f", page {sentence['page_number']}"
                lines.append(
                    f"- {sentence['text']} [{label}; "
                    f"{sentence['citation']}]")
        for passage in result.passages or []:
            label = passage["title"]
            if passage.get("location"):
                label += f" ({passage['location']})"
            lines.append(f"Retrieved source: {label} [{passage['citation']}]")
            question_terms = passage.get("matched_question_terms", [])
            expansion_terms = passage.get("matched_licensed_expansion_terms", [])
            if question_terms or expansion_terms:
                explanation = []
                if question_terms:
                    explanation.append(
                        "query terms: " + ", ".join(question_terms))
                if expansion_terms:
                    explanation.append(
                        "licensed expansion terms: " + ", ".join(expansion_terms))
                lines.append("  Retrieval match: " + "; ".join(explanation))
            licenses = passage.get("matched_expansion_licenses", [])
            if licenses:
                rendered_licenses = []
                for license_record in licenses:
                    details = [license_record["kind"]]
                    source_ids = sorted({
                        source.partition("#sha256=")[0]
                        for source in license_record.get("sources", [])
                    })
                    if source_ids:
                        details.append("sources: " + ", ".join(source_ids))
                    if license_record.get("rules"):
                        details.append("rules: " + ", ".join(
                            license_record["rules"]))
                    rendered_licenses.append(
                        f"{license_record['evidence']} → {license_record['text']} "
                        f"({'; '.join(details)})")
                lines.append("  Expansion support: "
                             + "; ".join(rendered_licenses))
        groups: dict[tuple[Any, ...], list[FactCandidate]] = {}
        for candidate in result.candidates or []:
            key = (_tokens(candidate.subject), _tokens(candidate.relation),
                   _tokens(candidate.object), candidate.polarity)
            groups.setdefault(key, []).append(candidate)
        if groups:
            if any(
                    item.get("kind") == "surface_relation_discovery"
                    for candidate in (result.candidates or [])
                    for item in candidate.language_evidence):
                lines.append(
                    "Some claims below are exploratory relation proposals from "
                    "capitalized spans and predicate morphology; inspect their "
                    "source wording and roles before accepting them.")
            lines.append("Review-only claim synthesis:")
            keys_by_relation: dict[tuple[Any, ...], set[tuple[Any, ...]]] = {}
            for key in groups:
                keys_by_relation.setdefault(key[:2], set()).add(key)
            for key in sorted(groups):
                candidates = groups[key]
                first = min(candidates, key=lambda item: (item.sentence, item.source))
                label = "supports" if first.polarity else "opposes"
                fact_label = "fact" if first.polarity else "negative fact"
                indexed_sources = {
                    candidate.source.partition("#sha256=")[0]
                    for candidate in candidates
                }
                lines.append(
                    f"Proposed for review ({fact_label}): Candidate claim ({label}; "
                    f"{len(indexed_sources)} indexed "
                    f"source(s), not yet accepted): {first.subject} — "
                    f"{first.relation} → {first.object}.")
                if any(other != key for other in keys_by_relation[key[:2]]):
                    lines.append("  Competing candidate claims were also extracted.")
                seen_support = set()
                for candidate in sorted(candidates,
                                        key=lambda item: (item.source, item.sentence)):
                    support_key = (candidate.source, candidate.sentence)
                    if support_key in seen_support:
                        continue
                    seen_support.add(support_key)
                    source_id = candidate.source.partition("#sha256=")[0]
                    lines.append(
                        f"  Evidence: {candidate.sentence} "
                        f"[source: {source_id}; citation: {candidate.source}]")
                language_rows = {
                    json.dumps(item, sort_keys=True, ensure_ascii=False): item
                    for candidate in candidates
                    for item in candidate.language_evidence
                }
                if language_rows:
                    examples = [
                        (f"induced morphology: {item['canonical_form']} → "
                         f"{item['surface_form']} (context {item['context']}, "
                         f"suffix {item['suffix']!r}; "
                         f"licensed by " + ", ".join(
                             f"{support['relation']} → "
                             f"{', '.join(support['surface_forms'])} "
                             f"[sources: {', '.join(support['sources'])}]"
                             for support in item['support']) + ")")
                        if item.get("kind") == "induced_suffix" else
                        (f"observed predicate form: {item['canonical_form']} → "
                         f"{item['surface_form']} (grounded by " + "; ".join(
                             f"{support['relation']} → "
                             f"{', '.join(support['surface_forms'])} "
                             f"[sources: {', '.join(support['sources'])}]"
                             for support in item['support']) + ")")
                        if item.get("kind") == "observed_predicate_form" else
                        (f"induced entity plural: {item['alias']} → "
                         f"{item['entity']} (context {item['context']}; "
                         f"shared roles: " + ", ".join(
                             f"{role['relation']} {role['role']}"
                             for role in item.get("shared_roles", [])) + "; "
                         f"target role evidence: " + ", ".join(
                             item.get("target_role_sources", [])) + "; "
                         f"licensed by " + "; ".join(
                             f"{support['entity']} → "
                             f"{', '.join(support['surface_forms'])} "
                             f"[sources: {', '.join(support['sources'])}]"
                             for support in item.get("support", [])) + ")")
                        if item.get("kind") == "induced_entity_plural" else
                        (f"entity alias: {item['alias']} → {item['entity']} "
                         f"[sources: {', '.join(item.get('sources', []))}]")
                        if item.get("kind") == "entity_alias" else
                        f"{item['template']}: {item['subject']} → "
                        f"{item['object']} [{', '.join(item['sources'])}]"
                        for item in (language_rows[name]
                                     for name in sorted(language_rows))]
                    lines.append("  Language-frame support: " + "; ".join(examples))
        return "\n\n".join(lines)

    def render_research_brief(self, result: ResearchResult) -> str:
        """Render the user-facing answer first; keep evidence for /explain."""
        response = result.response
        if response is not None and response.status == "answered":
            text = self.render_brief(response)
            sources = ([] if response.proofs or response.inference_proofs else
                       [source for fact in (response.evidence or [])
                        for source in fact.get("sources", [])])
            if not sources:
                sources = [item.get("title", "")
                           for item in (result.source_sentences or [])]
            labels = sorted({Path(source.split("#", 1)[0]).name
                             for source in sources if source})
            if labels and "\nSource:" not in text:
                text += "\nSource: " + ", ".join(labels[:3])
            return text
        query = result.query or ""
        generic_action = re.fullmatch(
            r"\s*what\s+(?:does|do)\s+(?P<entity>.+?)\s+do\s*[?!.]?\s*",
            query, flags=re.IGNORECASE)
        if (generic_action is not None and result.status == "sources_found"
                and result.realized_answer is None):
            entity = generic_action.group("entity").strip()
            entity = re.sub(r"^(?:the|a|an)\s+", "", entity,
                            flags=re.IGNORECASE)
            entity_tokens = _tokens(entity)
            action_facts = [
                fact for fact in self._facts.values()
                if _tokens(fact.subject) == entity_tokens
                and _tokens(fact.relation) not in {
                    _tokens("is-a"), _tokens("has relation type")
                }
                and not fact.qualifiers
            ]
            if action_facts:
                sentences = []
                sources = set()
                for fact in action_facts[:3]:
                    realized = self.write_fact(
                        fact.subject, fact.relation, fact.object)
                    if realized:
                        sentences.append(realized[0])
                    else:
                        sentences.append(
                            f"{fact.subject} — {fact.relation} → {fact.object}.")
                    sources.update(fact.sources)
                reply = "Known facts: " + " ".join(sentences)
                source_names = sorted({
                    Path(source.split("#", 1)[0]).name for source in sources
                    if source
                })
                if source_names:
                    reply += "\nSource: " + ", ".join(source_names[:3])
                return reply
            if not action_facts:
                return (f"I found sources that mention {entity}, but no "
                        f"accepted fact states what {entity} does. Which "
                        f"{entity} do you mean, or can you point me to a "
                        "source about its function?")
        if result.realized_answer is not None:
            realized = result.realized_answer
            return (f"{realized['text']} "
                    f"[Source: {realized['source_title']}; "
                    "quoted evidence, not an accepted fact]")
        if result.status == "needs_review":
            candidate = next(iter(result.candidates or []), None)
            if candidate is not None:
                source = Path(candidate.source.split("#", 1)[0]).name
                type_question = re.fullmatch(
                    r"\s*what\s+is\s+(?:a|an)\s+(?P<type>.+?)\s*[?!.]?\s*",
                    query, flags=re.IGNORECASE)
                if (type_question is not None
                        and _tokens(candidate.relation) == _tokens("is-a")
                        and _tokens(candidate.object)
                        == _tokens(type_question.group("type"))
                        and _tokens(candidate.subject)
                        != _tokens(candidate.object)):
                    return ("Unverified example, not a definition: "
                            f"“{candidate.sentence}” This is a candidate claim "
                            f"about one {candidate.subject}; it does not give "
                            f"a full definition of {candidate.object}. Review "
                            "the claim before I use it.\nSource: " + source)
                claim_status = ("supporting claim awaiting review"
                                if candidate.polarity else
                                "opposing claim awaiting review")
                return (f"{candidate.sentence} [Source: {source}; "
                        f"{claim_status}; not yet an accepted fact]")
            return "I found a related claim, but it hasn't been verified yet. Ask ‘why?’ to review its wording and source."
        if (response is not None and response.status == "unknown"
                and response.reason_code == "missing_is_a_evidence"):
            return response.request or "I don't have evidence for that type claim."
        if (response is not None and response.status == "unknown"
                and response.reason_code == "missing_subject_relation_fact"):
            return response.request or "I don't have an accepted fact for this question."
        if result.status == "sources_found":
            if result.source_sentences:
                sentence = result.source_sentences[0]
                source = sentence.get("title") or Path(
                    sentence.get("location", "source")).name
                if sentence.get("context_kind") == "example":
                    return (f"Illustrative example, not a factual assertion: "
                            f"{sentence['text']}\nSource: {source}. Ask "
                            "‘why?’ for its citation.")
                return (f"Source text: {sentence['text']}\n"
                        f"Source: {source}. This is quoted evidence, not an "
                        "accepted fact; ask ‘why?’ for its citation.")
            return ("I found relevant source text, but no accepted fact supports "
                    "an answer yet. Ask ‘why?’ to see the best matching sentence.")
        if (response is not None and response.status == "unknown"
                and response.matched_templates and response.request
                and "no explicit positive or negative evidence" in response.request):
            return response.request
        if (response is not None and response.status == "unknown"
                and response.reason_code == "missing_premise"):
            return self.render_brief(response)
        return "I don't know this from the sources and facts I have. Add a source or teach the fact."

    def render_brief(self, result: QuestionResult) -> str:
        """Give a concise, grounded default reply; diagnostics stay in render()."""
        if result.status == "answered":
            text = ""
            # A multi-edge path proves the answer through several facts; none
            # of its leaves alone states the answer. Only realize a leaf as a
            # declarative when the proof is a single fact and no rule-derived
            # proof is carrying the conclusion.
            has_composite_proof = (
                bool(result.inference_proofs)
                or any(len(proof) > 1 for proof in result.proofs or []))
            # A truth-valued question needs a truth-valued answer. Do not
            # realize its supporting triple as a declarative, which can be
            # ungrammatical when the stored relation is a bare form ("X create
            # Y") and can obscure an explicit negative answer.
            if result.truth is None and not has_composite_proof:
                # Use a sentence only when an accepted, varied source frame
                # licenses it.
                for fact in result.evidence or []:
                    if all(fact.get(key) for key in
                           ("subject", "relation", "object")):
                        sentences = self.write_fact(
                            fact["subject"], fact["relation"], fact["object"],
                            qualifiers=dict(fact.get("qualifiers", [])))
                        if sentences:
                            text = sentences[0]
                            break
            if (result.truth is None and not has_composite_proof
                    and not text and result.evidence):
                # If no varied sentence frame is licensed yet, a single-token
                # predicate from the matched grounded question can still be
                # realized as a plain fact sentence. Keep this fallback narrow:
                # multiword relations have uncertain syntax and use the
                # structured answer fallback below.
                for fact in result.evidence:
                    relation_tokens = _tokens(fact.get("relation", ""))
                    if (all(fact.get(key) for key in
                            ("subject", "relation", "object"))
                            and len(relation_tokens) == 1
                            and relation_tokens not in {
                                _tokens("is-a"), _tokens("has relation type")
                            }):
                        text = (f"{fact['subject']} {fact['relation']} "
                                f"{fact['object']}.")
                        break
            if (result.truth is None and not text and result.answer
                    and result.matched_templates):
                # A successful subject-answer frame already licenses the
                # wording and binds its object slot. Substitute the verified
                # subject answer into that exact frame to produce a sentence
                # without inventing a predicate or inflection. The binding
                # must agree with an accepted fact or a verified proof.
                supported_subjects = []
                for fact in result.evidence or []:
                    if all(fact.get(key) for key in
                           ("subject", "relation", "object")):
                        supported_subjects.append((
                            fact["subject"], fact["object"]))
                for proof in result.inference_proofs or []:
                    conclusion = proof.get("conclusion", {})
                    if conclusion.get("subject") and conclusion.get("object"):
                        supported_subjects.append((
                            conclusion["subject"], conclusion["object"]))
                if any(subject == result.answer
                       for subject, _obj in supported_subjects):
                    for raw_template in result.matched_templates:
                        template = raw_template
                        for subject, obj in supported_subjects:
                            if subject == result.answer:
                                template = template.replace("{object}", obj)
                                break
                        wh = re.match(
                            r"(?i)^\s*(?:who|whom|what|which\s+\w+)\b",
                            template)
                        if wh is None:
                            continue
                        remainder = template[wh.end():].strip()
                        remainder = re.sub(r"[?!.]+\s*$", "", remainder)
                        if remainder:
                            text = f"{result.answer} {remainder}."
                            text = text[0].upper() + text[1:]
                            break
            if not text:
                if result.truth is not None:
                    text = "Yes." if result.truth else "No."
                else:
                    text = f"{result.answer}." if result.answer else "I don't know."
            sources = ([] if result.proofs or result.inference_proofs else
                       sorted({Path(source.split("#", 1)[0]).name
                               for fact in (result.evidence or [])
                               for source in fact.get("sources", []) if source}))
            if sources:
                text += "\nSource: " + ", ".join(sources[:3])
            return text
        if result.status == "ambiguous":
            return "The sources or facts I have disagree; I can't choose an answer yet."
        if result.reason_code == "missing_premise":
            entries = result.missing_premises or []
            if entries:
                item = entries[0]
                missing = item.get("missing_premise", {})
                supported = item.get("supported_premises", [])
                known = ""
                if supported:
                    premise = supported[0]
                    known = (f"I have {premise.get('subject', '?')} — "
                             f"{premise.get('relation', '?')} → "
                             f"{premise.get('object', '?')}. ")
                needed = (f"{missing.get('subject', '?')} — "
                          f"{missing.get('relation', '?')} → "
                          f"{missing.get('object', '?')}")
                return (known + f"I need {needed} to derive this. "
                        "Tell me that fact or point me to a source.")
            return (result.request or
                    "I can't derive that yet; a required premise is missing. "
                    "Ask ‘why?’ to see what I would need.")
        if (result.status == "unknown" and result.matched_templates
                and result.request
                and "no explicit positive or negative evidence" in result.request):
            return result.request
        return "I don't know this from the facts I have."

    def accept_fact_candidate(self, candidate: FactCandidate,
                              research_index: Any) -> FactEvidence:
        """Commit a reviewed source claim and reuse its reviewed frame evidence."""
        excerpt = research_index.resolve_citation(candidate.source)
        if candidate.sentence not in excerpt:
            raise ValueError("candidate sentence does not match its source citation")
        add = self.add_fact if candidate.polarity else self.add_negative_fact
        fact = add(candidate.subject, candidate.relation,
                   candidate.object, candidate.source,
                   qualifiers=dict(candidate.qualifiers))
        discovery = next((item for item in candidate.language_evidence
                          if item.get("kind") == "surface_relation_discovery"),
                         None)
        if discovery is not None and candidate.polarity and not candidate.qualifiers:
            # Explicit acceptance supplies the missing role labels for this
            # exact sentence. Existing licensing thresholds still require
            # varied accepted examples before the extracted frame can transfer.
            relation_words = _tokens(candidate.relation)
            discovery_method = discovery.get("method")
            class_membership_discovery = discovery_method in {
                "copular class-membership pattern",
                "bounded common-noun copular classification",
                "bounded named-entity copular type with adjunct",
            }
            try:
                self.teach_fact_pattern(
                    candidate.sentence, subject=candidate.subject,
                    relation=candidate.relation, obj=candidate.object,
                    source=candidate.source,
                    predicate_phrase=str(discovery["predicate_phrase"]),
                    subject_phrase=str(discovery.get(
                        "subject_phrase", candidate.subject)),
                    object_phrase=str(discovery.get(
                        "object_phrase", candidate.object)),
                    learn_surface_entity_aliases=not bool(
                        discovery.get("page_title_coreference")),
                    ordered_class_membership_spans=
                        class_membership_discovery)
            except ValueError:
                if not class_membership_discovery:
                    raise
                # The reviewed type fact remains valid even if a different
                # span ambiguity prevents teaching its sentence frame.
            if class_membership_discovery:
                # Type assertions are useful as symbolic proof guards, but
                # they do not establish whether an answer slot should be
                # verbalized with Who or What.
                generated_question = None
            elif discovery_method in {
                    "copular nominal relation pattern",
                    "direct copular nominal relation pattern",
                    "bounded nominal appositive relation"}:
                nominal_relation = _tokens(str(
                    discovery["predicate_phrase"]))
                nominal_head = (nominal_relation[:-1]
                                if nominal_relation[-1:] == ("of",)
                                else nominal_relation)
                # Agent nouns such as "author", "creator", and "designer"
                # make the subject a person-bearing answer slot. Other
                # nominal relations (for example, "capital of") keep the
                # broader "What" form. This is a grammatical frame choice;
                # the accepted source fact still supplies all content.
                wh = ("Who" if nominal_head
                      and nominal_head[-1].endswith(("er", "or", "ist"))
                      else "What")
                generated_question = (
                    f"{wh} is the {discovery['predicate_phrase']} "
                    f"{candidate.object}?")
            else:
                typed_source_match = next((item for item in
                                           candidate.language_evidence
                                           if item.get("kind")
                                           == "typed_relation_source_match"),
                                          None)
                if typed_source_match is not None:
                    generated_question = str(
                        typed_source_match.get("question", "")
                    ).rstrip("?.!") + "?"
                else:
                    question_word = ("What" if relation_words
                                    and relation_words[0] in {
                                        "am", "are", "be", "been", "being", "is",
                                        "was", "were"}
                                    else "Who")
                    generated_question = (
                        f"{question_word} {discovery['predicate_phrase']} "
                        f"{candidate.object}?")
            if generated_question is not None:
                try:
                    self.teach_question(
                        generated_question, relation=candidate.relation,
                        answer_field="subject", bound_entity=candidate.object,
                        answer=candidate.subject)
                except ValueError:
                    # A predicate phrase whose literal wording cannot form one
                    # unambiguous question remains usable for fact extraction.
                    pass
            # A reviewed active fact also licenses the mechanically paired
            # do-support question that asks for its object. Use the canonical
            # relation in the question ("What did Ada write?"), while the
            # fact-pattern evidence retains the exact observed source form
            # (which may be an irregular inflection such as "wrote").
            if (len(relation_words) == 1 and relation_words[0] not in {
                    "am", "are", "be", "been", "being", "is", "was", "were",
                    "do", "does", "did", "have", "has", "had"}):
                object_question = (
                    f"What did {candidate.subject} {candidate.relation}?")
                try:
                    self.teach_question(
                        object_question, relation=candidate.relation,
                        answer_field="object",
                        bound_entity=candidate.subject,
                        answer=candidate.object)
                except ValueError:
                    # A conflicting or ambiguous question parse must not
                    # prevent the reviewed source fact from being retained.
                    pass
            predicate_words = _tokens(str(discovery["predicate_phrase"]))
            if (predicate_words and predicate_words[-1].endswith(("ed", "ied"))
                    and predicate_words[0] not in {
                        "am", "are", "be", "been", "being", "is", "was", "were"}):
                # Passive voice provides a mechanically formed inverse
                # question without guessing the verb's infinitive spelling.
                # The relation and answer remain grounded in the reviewed fact.
                inverse_question = (
                    f"What was {discovery['predicate_phrase']} by "
                    f"{candidate.subject}?")
                try:
                    self.teach_question(
                        inverse_question, relation=candidate.relation,
                        answer_field="object", bound_entity=candidate.subject,
                        answer=candidate.object)
                except ValueError:
                    pass
            spelling_support = discovery.get("morphology_support")
            canonical_relation = _tokens(candidate.relation)
            predicate_words = _tokens(str(discovery["predicate_phrase"]))
            if (isinstance(spelling_support, Mapping)
                    and spelling_support.get("kind")
                        == "licensed_predicate_spelling"
                    and len(canonical_relation) == len(predicate_words)):
                active_inverse = (
                    f"What did {candidate.subject} {candidate.relation}?")
                try:
                    self.teach_question(
                        active_inverse, relation=candidate.relation,
                        answer_field="object", bound_entity=candidate.subject,
                        answer=candidate.object)
                except ValueError:
                    pass
        page_coreference = next((item for item in candidate.language_evidence
                                 if item.get("kind")
                                 == "page_title_coreference"), None)
        if (page_coreference is not None and candidate.polarity
                and not candidate.qualifiers):
            # Store the exact user wording as one reviewed example. The usual
            # varied-entity threshold still governs whether it can generalize.
            question = str(page_coreference.get("question", ""))
            if question:
                try:
                    self.teach_question(
                        question, relation=candidate.relation,
                        answer_field="subject", bound_entity=candidate.object,
                        answer=candidate.subject)
                except ValueError:
                    pass
        return fact

    def write_fact(self, subject: str, relation: str, obj: str, *,
                   polarity: bool = True,
                   qualifiers: Mapping[str, str] | None = None) -> list[str]:
        """Write a stored fact using source-grounded sentence structures.

        Only frames learned from at least two varied, fact-backed examples
        are eligible. The method returns every licensed surface realization,
        ordered by independent source-document support and then lexically.
        """
        subject, relation, obj = (_display(subject, "subject"),
                                  _display(relation, "relation"),
                                  _display(obj, "object"))
        subject = self._canonicalize_entity(subject)
        obj = self._canonicalize_entity(obj)
        if type(polarity) is not bool:
            raise ValueError("polarity must be a bool")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        fact_store = self._facts if polarity else self._negative_facts
        if self._fact_key(subject, relation, obj, normalized_qualifiers) not in fact_store:
            return []
        realizations = self._realize_fact_pattern(
            subject, relation, obj, polarity=polarity)
        if _tokens(relation) == _tokens("is-a"):
            article = _indefinite_article_for(obj)
            if article is not None:
                article_pattern = re.compile(
                    r"(?P<copula>\b(?:is|are|was|were)\s+)"
                    r"(?:a|an)(?P<space>\s+)"
                    r"(?=" + re.escape(obj) + r"(?:\b|$))",
                    flags=re.IGNORECASE)
                realizations = [article_pattern.sub(
                    lambda match: match.group("copula") + article
                    + match.group("space"), sentence)
                    for sentence in realizations]
        if not normalized_qualifiers:
            return realizations
        context = "context: " + ", ".join(
            f"{name}={value}" for name, value in normalized_qualifiers)
        return [f"{sentence} [{context}]" for sentence in realizations]

    def _realize_fact_pattern(self, subject: str, relation: str, obj: str, *,
                              polarity: bool) -> list[str]:
        """Realize a proven proposition, ranking frames by source support."""
        return [item["sentence"] for item in self._realize_fact_patterns(
            subject, relation, obj, polarity=polarity)]

    def realize_claim(self, subject: str, relation: str, obj: str, *,
                      polarity: bool = True) -> list[dict[str, Any]]:
        """Return source-grounded sentence frames for a verified claim.

        Unlike ``write_fact``, this method does not require the exact claim to
        already be stored: proof renderers use it after independently checking
        the claim. The returned frame records identify the wording evidence.
        """
        if type(polarity) is not bool:
            raise ValueError("polarity must be a bool")
        subject = self._canonicalize_entity(_display(subject, "subject"))
        obj = self._canonicalize_entity(_display(obj, "object"))
        relation = " ".join(_tokens(_display(relation, "relation")))
        return self._realize_fact_patterns(
            subject, relation, obj, polarity=polarity)

    def _realize_fact_patterns(self, subject: str, relation: str, obj: str, *,
                               polarity: bool) -> list[dict[str, Any]]:
        """Return realizations with the source evidence for each wording frame."""
        relation_tokens = _tokens(relation)
        by_sentence: dict[str, dict[str, Any]] = {}
        for (template, trained_relation), examples in self._fact_pattern_examples.items():
            subjects = {pair[0] for pair in examples}
            objects = {pair[1] for pair in examples}
            if (trained_relation != relation_tokens or len(examples) < 2
                    or len(subjects) < 2 or len(objects) < 2
                    or self._fact_pattern_polarities.get(
                        (template, trained_relation), True) != polarity):
                continue
            surface_source_map = self._fact_pattern_surface_sources.get(
                (template, trained_relation), {})
            for surface in self._fact_pattern_surfaces.get(
                    (template, trained_relation), set()):
                surface_examples = surface_source_map.get(surface, {})
                # The shared structural frame above already requires varied
                # subject/object support. A surface may be backed by one
                # explicit teacher alignment (for example a second observed
                # predicate form); requiring that exact wording to repeat
                # across two more pairs would discard useful grounded variants.
                if not surface_examples:
                    continue
                sources = {source for example_sources in surface_examples.values()
                           for source in example_sources}
                document_sources = sorted({source.split("#", 1)[0]
                                            for source in sources})
                sentence = (surface.replace("{{subject}}", subject)
                                   .replace("{{object}}", obj))
                record = {
                    "sentence": sentence,
                    "surface": surface,
                    "template": " ".join(template),
                    "sources": sorted(sources),
                    "source_documents": document_sources,
                    "document_count": len(document_sources),
                    "citation_count": len(sources),
                }
                prior = by_sentence.get(sentence)
                rank = (record["document_count"], record["citation_count"])
                prior_rank = ((prior["document_count"], prior["citation_count"])
                              if prior else (-1, -1))
                if (rank > prior_rank
                        or (rank == prior_rank and record["template"]
                            < prior["template"])):
                    by_sentence[sentence] = record
        return sorted(by_sentence.values(), key=lambda item: (
            -item["document_count"], -item["citation_count"],
            item["sentence"].casefold(), item["sentence"], item["template"]))

    @staticmethod
    def _coordinated_writing_lines(
            statements: list[dict[str, Any]],
    ) -> list[tuple[tuple[int, ...], str]]:
        """Join bounded groups of compatible claims with citations intact."""
        def join_list(items: list[str]) -> str:
            if len(items) == 2:
                return f"{items[0]} and {items[1]}"
            return ", ".join(items[:-1]) + f", and {items[-1]}"

        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for statement in statements:
            fact = statement.get("fact", {})
            frame = statement.get("frame_evidence", {})
            subject = fact.get("subject")
            relation = fact.get("relation")
            obj = fact.get("object")
            surface = frame.get("surface")
            template = frame.get("template", "").split()
            if not all(isinstance(value, str) and value for value in
                       (subject, relation, obj, surface)):
                continue
            if (surface.count("{{subject}}") != 1
                    or surface.count("{{object}}") != 1
                    or "," in obj or ";" in obj
                    or any(token in _tokens(obj) for token in ("and", "or"))):
                continue
            try:
                subject_position = template.index("<subject>")
                predicate_position = template.index("<predicate>")
                object_position = template.index("<object>")
            except ValueError:
                continue
            if not subject_position < predicate_position < object_position:
                continue
            qualifiers = tuple(tuple(pair) for pair in fact.get("qualifiers", ()))
            key = (_tokens(subject), _tokens(relation), qualifiers,
                   bool(statement.get("polarity", True)),
                   bool(statement.get("inferred")), frame["template"], surface)
            groups.setdefault(key, []).append(statement)

        coordinated: list[tuple[tuple[int, ...], str]] = []
        for group in groups.values():
            if not 2 <= len(group) <= _MAX_COORDINATED_WRITING_CLAIMS:
                continue
            objects = [statement["fact"]["object"] for statement in group]
            if len({_tokens(obj) for obj in objects}) != len(objects):
                continue
            first = group[0]
            first_fact = first["fact"]
            surface = first["frame_evidence"]["surface"]
            sentence = (surface.replace("{{subject}}", first_fact["subject"])
                                .replace("{{object}}", join_list(objects)))
            indexes = tuple(statement["_line_index"] for statement in group)
            inferred = bool(first.get("inferred"))
            source_values = sorted({source for statement in group
                                    for source in (
                                        statement.get("sources", ())
                                        if inferred else
                                        statement["fact"].get("sources", ()))})
            wording_sources = sorted({source for statement in group
                                      for source in statement.get(
                                          "frame_evidence", {}).get("sources", ())})
            notes = []
            if inferred:
                rules = sorted({rule for statement in group
                                for rule in statement.get("rules", ())})
                if rules:
                    notes.append("rules: " + ", ".join(rules))
                if source_values:
                    notes.append("sources: " + ", ".join(source_values))
            elif source_values:
                notes.append("sources: " + ", ".join(source_values))
            if first_fact.get("qualifiers"):
                notes.append("context: " + ", ".join(
                    f"{name}={value}" for name, value in
                    first_fact["qualifiers"]))
            if wording_sources:
                notes.append("wording sources: " + ", ".join(wording_sources))
            line = f"{'Derived: ' if inferred else ''}{sentence}"
            if notes:
                line += " [" + "; ".join(notes) + "]"
            coordinated.append((indexes, line))

        # A second bounded composition shares the subject across distinct
        # predicates. Require the same minimal active syntax on both frames;
        # this does not infer a connective for arbitrary clause structures.
        used_indexes = {index for indexes, _line in coordinated
                        for index in indexes}
        predicate_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for statement in statements:
            if statement["_line_index"] in used_indexes:
                continue
            fact = statement.get("fact", {})
            frame = statement.get("frame_evidence", {})
            subject, relation, obj = (fact.get("subject"), fact.get("relation"),
                                      fact.get("object"))
            template = frame.get("template", "")
            surface = frame.get("surface", "")
            if (not all(isinstance(value, str) and value
                        for value in (subject, relation, obj, surface))
                    or template != "<subject> <predicate> <object>"
                    or surface.count("{{subject}}") != 1
                    or surface.count("{{object}}") != 1
                    or "," in obj or ";" in obj
                    or any(token in _tokens(obj) for token in ("and", "or"))):
                continue
            match = re.fullmatch(
                r"\{\{subject\}\}\s+(.+?)\s+\{\{object\}\}([.!?]?)",
                surface)
            if match is None:
                continue
            predicate_phrase, terminator = match.groups()
            if (not predicate_phrase.strip()
                    or any(token in _tokens(predicate_phrase)
                           for token in ("and", "or"))
                    or "," in predicate_phrase or ";" in predicate_phrase):
                continue
            qualifiers = tuple(tuple(pair) for pair in fact.get("qualifiers", ()))
            key = (_tokens(subject), qualifiers,
                   bool(statement.get("polarity", True)),
                   bool(statement.get("inferred")), template, terminator)
            row = dict(statement)
            row["_predicate_phrase"] = predicate_phrase
            row["_terminator"] = terminator
            predicate_groups.setdefault(key, []).append(row)

        for group in predicate_groups.values():
            if (not 2 <= len(group) <= _MAX_COORDINATED_WRITING_CLAIMS
                    or len({_tokens(row["fact"]["relation"])
                            for row in group}) != len(group)):
                continue
            first = group[0]
            first_fact = first["fact"]
            clauses = [f"{row['_predicate_phrase']} {row['fact']['object']}"
                       for row in group]
            sentence = (f"{first_fact['subject']} {join_list(clauses)}"
                        f"{first['_terminator']}")
            indexes = tuple(row["_line_index"] for row in group)
            inferred = bool(first.get("inferred"))
            source_values = sorted({source for statement in group
                                    for source in (
                                        statement.get("sources", ())
                                        if inferred else
                                        statement["fact"].get("sources", ()))})
            wording_sources = sorted({source for statement in group
                                      for source in statement.get(
                                          "frame_evidence", {}).get("sources", ())})
            notes = []
            if inferred:
                rules = sorted({rule for statement in group
                                for rule in statement.get("rules", ())})
                if rules:
                    notes.append("rules: " + ", ".join(rules))
            if source_values:
                notes.append("sources: " + ", ".join(source_values))
            if first_fact.get("qualifiers"):
                notes.append("context: " + ", ".join(
                    f"{name}={value}" for name, value in
                    first_fact["qualifiers"]))
            if wording_sources:
                notes.append("wording sources: " + ", ".join(wording_sources))
            line = f"{'Derived: ' if inferred else ''}{sentence}"
            if notes:
                line += " [" + "; ".join(notes) + "]"
            coordinated.append((indexes, line))
        return coordinated

    def teach_about_frame(self, question: str, *, entity: str) -> bool:
        """Teach a literal about-entity request frame from a stored entity.

        Two distinct entities are required to license a frame. The frame only
        identifies the requested entity; prose still comes from `write_about`
        and its source-grounded sentence patterns.
        """
        question = _display(question, "question")
        entity = self._canonicalize_entity(_display(entity, "entity"))
        entity_words = _tokens(entity)
        if not entity_words or not any(
                _tokens(fact.subject) == entity_words
                for fact in self.facts() + self.negative_facts()):
            raise ValueError("about-frame entity must have stored subject facts")
        words = _tokens(question)
        starts = [index for index in range(len(words) - len(entity_words) + 1)
                  if words[index:index + len(entity_words)] == entity_words]
        if len(starts) != 1:
            raise ValueError("entity must occur exactly once in the about request")
        start = starts[0]
        key = (words[:start], words[start + len(entity_words):])
        examples = self._about_question_examples.setdefault(key, {})
        examples[entity_words] = entity
        return len(examples) >= 2

    def resolve_about_request(self, question: str) -> tuple[str | None, bool]:
        """Resolve one licensed literal frame to the entity span in a request."""
        question = _display(question, "question")
        direct_write = re.fullmatch(
            r"\s*(?:(?:please\s+)?|(?:can|could|would)\s+you\s+"
            r"(?:please\s+)?)"
            r"(?:write|compose|draft)\s+"
            r"(?:(?:(?:a\s+)?(?:(?:short|sourced)\s+)*(?:digest|summary))\s+about|"
            r"about)\s+(.+?)\s*[.!?]*\s*",
            question, flags=re.IGNORECASE)
        if direct_write is not None:
            return self._canonical_subject_display(
                direct_write.group(1).strip().rstrip(".!? ")), False
        words = _tokens(question)
        token_matches = list(re.finditer(r"[\w']+", question, flags=re.UNICODE))
        subjects: set[str] = set()
        for (prefix, suffix), examples in self._about_question_examples.items():
            if len(examples) < 2 or len(words) <= len(prefix) + len(suffix):
                continue
            if prefix and words[:len(prefix)] != prefix:
                continue
            if suffix and words[-len(suffix):] != suffix:
                continue
            end = len(words) - len(suffix) if suffix else len(words)
            entity_words = words[len(prefix):end]
            if entity_words:
                surface = question[token_matches[len(prefix)].start():
                                   token_matches[end - 1].end()]
                subjects.add(self._canonical_subject_display(surface))
        if len(subjects) == 1:
            subject = next(iter(subjects))
            group = self._resolve_subject_group(subject)
            return (self._format_subject_group(group) if group else subject), False
        if len(subjects) > 1:
            return None, True
        return None, False

    def _resolve_subject_group(self, subject: str) -> tuple[str, ...] | None:
        """Resolve an explicit bounded subject coordination to stored subjects."""
        subject_words = _tokens(subject)
        subject_facts = {
            _tokens(fact.subject): fact.subject
            for fact in self.facts() + self.negative_facts()
        }
        if subject_words in subject_facts:
            return None
        surface = re.sub(r"^both\b", "", subject.strip(), count=1,
                         flags=re.IGNORECASE).strip()
        surface = re.sub(r",\s*and\s+", ", ", surface,
                         flags=re.IGNORECASE)
        parts = [part.strip() for part in re.split(
            r"\s*,\s*|\s+and\s+", surface, flags=re.IGNORECASE)]
        if not 2 <= len(parts) <= 8 or any(not part for part in parts):
            return None
        known_surfaces: dict[tuple[str, ...], set[str]] = {}
        for fact in self.facts() + self.negative_facts():
            known_surfaces.setdefault(_tokens(fact.subject), set()).add(fact.subject)
        for alias, record in self._entity_alias_records().items():
            canonical = record["entity"]
            if _tokens(canonical) in subject_facts:
                known_surfaces.setdefault(alias, set()).add(subject_facts[_tokens(canonical)])
        resolved = []
        for part in parts:
            entities = known_surfaces.get(_tokens(part.strip()), set())
            if len(entities) != 1:
                return None
            resolved.append(next(iter(entities)))
        if len({_tokens(entity) for entity in resolved}) != len(resolved):
            return None
        return tuple(resolved)

    @staticmethod
    def _format_subject_group(subjects: tuple[str, ...]) -> str:
        if len(subjects) == 2:
            return " and ".join(subjects)
        return ", ".join(subjects[:-1]) + ", and " + subjects[-1]

    def write_about_group(
            self, subjects: Iterable[str], *,
            qualifiers: Mapping[str, str] | None = None) -> WritingResult:
        """Write separate grounded digests for two to eight named subjects."""
        values = list(subjects)
        if not 2 <= len(values) <= 8:
            raise ValueError("group writing requires between two and eight subjects")
        resolved = self._resolve_subject_group(", ".join(values))
        if resolved is None:
            raise ValueError("group members must be distinct stored subjects")
        digests = [self.write_about(entity, qualifiers=qualifiers)
                   for entity in resolved]
        group_label = self._format_subject_group(resolved)
        statements = [item for digest in digests for item in digest.statements]
        conflicts = [item for digest in digests for item in digest.conflicts]
        omitted = [item for digest in digests for item in digest.omitted]
        lines = [f"About {group_label}:"]
        for entity, digest in zip(resolved, digests):
            lines.append(f"{entity}:")
            body = digest.text.splitlines()[1:]
            lines.extend(f"  {line}" for line in body)
        statuses = {digest.status for digest in digests}
        if all(status == "written" for status in statuses):
            status = "written"
        elif statements:
            status = "partial"
        elif "ambiguous" in statuses:
            status = "ambiguous"
        else:
            status = "unknown"
        return WritingResult(status, group_label, statements, conflicts,
                             omitted, "\n".join(lines))

    def write_about(self, subject: str, *,
                    qualifiers: Mapping[str, str] | None = None
                    ) -> WritingResult:
        """Compose a digest from licensed facts and verified derived relations.

        Derived statements require both an independently checked rule proof
        and a learned positive sentence frame. Their proof sources and rule
        identifiers remain attached to the written sentence.
        """
        requested_subject = _display(subject, "subject")
        group = self._resolve_subject_group(requested_subject)
        if group is not None:
            return self.write_about_group(group, qualifiers=qualifiers)
        canonical_subject = self._canonical_subject_display(requested_subject)
        subject_key = _tokens(canonical_subject)
        requested_qualifiers = self._normalize_qualifiers(qualifiers)
        grouped: dict[tuple[Any, ...], dict[bool, FactEvidence]] = {}
        for polarity, store in ((True, self._facts), (False, self._negative_facts)):
            for fact in store.values():
                if (_tokens(self._canonicalize_entity(fact.subject)) != subject_key
                        or not self._has_qualifiers(fact, requested_qualifiers)):
                    continue
                key = self._fact_key(fact.subject, fact.relation, fact.object,
                                     fact.qualifiers)
                grouped.setdefault(key, {})[polarity] = fact

        statements: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        lines = [f"About {canonical_subject}:"]
        for key in sorted(grouped):
            polarities = grouped[key]
            if True in polarities and False in polarities:
                positive, negative = polarities[True], polarities[False]
                conflict = {
                    "positive": asdict(positive),
                    "negative": asdict(negative),
                }
                conflicts.append(conflict)
                qualifier_text = ("; context: " + ", ".join(
                    f"{name}={value}" for name, value in positive.qualifiers)
                    if positive.qualifiers else "")
                line = (f"Conflicting evidence for {positive.relation} → "
                        f"{positive.object}{qualifier_text}: positive sources "
                        f"{', '.join(positive.sources)}; negative sources "
                        f"{', '.join(negative.sources)}.")
                lines.append(line)
                continue

            polarity, fact = next(iter(polarities.items()))
            frame_realizations = self._realize_fact_patterns(
                fact.subject, fact.relation, fact.object, polarity=polarity)
            alternatives = [item["sentence"] for item in frame_realizations]
            if not alternatives:
                omitted.append(asdict(fact) | {
                    "polarity": polarity, "reason": "no learned sentence frame"})
                context = ("; context: " + ", ".join(
                    f"{name}={value}" for name, value in fact.qualifiers)
                    if fact.qualifiers else "")
                lines.append(
                    f"Not written: no learned sentence frame for "
                    f"{fact.relation} → {fact.object}{context} "
                    f"[sources: {', '.join(fact.sources)}].")
                continue
            sentence = alternatives[0]
            frame_evidence = frame_realizations[0]
            notes = ["sources: " + ", ".join(fact.sources)]
            notes.append("wording sources: "
                         + ", ".join(frame_evidence["sources"]))
            if fact.qualifiers:
                notes.append("context: " + ", ".join(
                    f"{name}={value}" for name, value in fact.qualifiers))
            statement = {
                "sentence": sentence,
                "alternatives": alternatives,
                "frame_evidence": frame_evidence,
                "fact": asdict(fact),
                "polarity": polarity,
            }
            statement["_line_index"] = len(lines)
            statements.append(statement)
            lines.append(f"{sentence} [{'; '.join(notes)}]")

        relation_names = self._inference_relation_names(requested_qualifiers)
        if relation_names:
            entities = {
                _tokens(value): value
                for fact in self.facts() + self.negative_facts()
                if self._qualifiers_equal(fact.qualifiers, requested_qualifiers)
                and _tokens(fact.relation) != _tokens("has relation type")
                for value in (fact.subject, fact.object)
            }
            if len(entities) > 256:
                omitted.append({"reason": "inference entity limit reached"})
                lines.append("Not written: inference search exceeded the 256-entity limit.")
            else:
                budget = 10_000
                inferred_triples: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
                for relation in relation_names:
                    for obj in entities.values():
                        triple_key = self._fact_key(
                            canonical_subject, relation, obj,
                            requested_qualifiers)
                        explicit_polarities = grouped.get(triple_key, {})
                        if (True in explicit_polarities
                                and False not in explicit_polarities):
                            # The fact digest already contains this exact
                            # relation and scope. Do not repeat its sentence
                            # as a derived statement merely because another
                            # proof also supports it.
                            continue
                        if budget < 1:
                            omitted.append({"reason": "inference expansion limit reached"})
                            lines.append("Not written: inference search exceeded its expansion budget.")
                            break
                        result = self.infer_relation(
                            canonical_subject, relation, obj,
                            qualifiers=dict(requested_qualifiers),
                            max_expansions=budget)
                        budget -= result.expansions
                        if result.status == "unknown":
                            if not result.complete:
                                omitted.append({"reason": result.request})
                                lines.append("Not written: " + result.request)
                            continue
                        if result.status == "ambiguous":
                            leaves = [leaf for proof in result.proofs
                                      for leaf in self._inference_fact_leaves(proof)]
                            negative_by_key = {
                                self._fact_key(fact.subject, fact.relation, fact.object,
                                               fact.qualifiers): fact
                                for fact in self.negative_facts()
                                if self._qualifiers_equal(
                                    fact.qualifiers, requested_qualifiers)
                            }
                            conflict_evidence = []
                            for leaf in leaves:
                                key = self._fact_key(leaf["subject"], leaf["relation"],
                                                     leaf["object"],
                                                     tuple(tuple(item) for item in
                                                           leaf.get("qualifiers", ())))
                                negative = negative_by_key.get(key)
                                if negative:
                                    conflict_evidence.append({
                                        "positive": leaf,
                                        "negative": asdict(negative),
                                    })
                            conflict = {
                                "subject": canonical_subject, "relation": relation,
                                "object": obj,
                                "inference_proofs": list(result.proofs),
                                "evidence": conflict_evidence,
                            }
                            if requested_qualifiers:
                                conflict["qualifiers"] = list(requested_qualifiers)
                            conflicts.append(conflict)
                            lines.append(
                                f"Not stated: inferred {relation} → {obj} conflicts "
                                "with explicit negative evidence.")
                            continue
                        rule_proofs = [proof for proof in result.proofs
                                       if _is_derived_proof(proof)]
                        if rule_proofs:
                            triple_key = self._fact_key(
                                canonical_subject, relation, obj, requested_qualifiers)
                            inferred_triples.setdefault(triple_key, []).extend(rule_proofs)
                    if budget < 1:
                        break

                for triple_key in sorted(inferred_triples):
                    relation = next((rule for rule in relation_names
                                     if _tokens(rule) == triple_key[1]),
                                    " ".join(triple_key[1]))
                    obj = entities.get(triple_key[2], " ".join(triple_key[2]))
                    proofs_by_key = {repr(proof): proof
                                     for proof in inferred_triples[triple_key]}
                    proofs = [proofs_by_key[key] for key in sorted(proofs_by_key)]
                    frame_realizations = self._realize_fact_patterns(
                        canonical_subject, relation, obj, polarity=True)
                    alternatives = [item["sentence"]
                                    for item in frame_realizations]
                    if not alternatives:
                        omitted.append({"subject": canonical_subject,
                                        "relation": relation, "object": obj,
                                        "polarity": True,
                                        "reason": "no learned sentence frame"})
                        lines.append(
                            f"Not written: no learned sentence frame for derived "
                            f"{relation} → {obj}.")
                        continue
                    sources = sorted({source for proof in proofs
                                      for leaf in self._inference_fact_leaves(proof)
                                      for source in leaf.get("sources", [])})
                    rule_ids = sorted({rule["rule_id"]
                                       for proof in proofs
                                       for rule in self._inference_rule_steps(proof)})
                    fact_record = {"subject": canonical_subject,
                                   "relation": relation, "object": obj}
                    if requested_qualifiers:
                        fact_record["qualifiers"] = list(requested_qualifiers)
                    sentence = alternatives[0]
                    frame_evidence = frame_realizations[0]
                    statement = {
                        "sentence": sentence, "alternatives": alternatives,
                        "frame_evidence": frame_evidence,
                        "fact": fact_record, "polarity": True, "inferred": True,
                        "sources": sources, "rules": rule_ids, "proofs": proofs,
                    }
                    statement["_line_index"] = len(lines)
                    statements.append(statement)
                    notes = []
                    if rule_ids:
                        notes.append("rules: " + ", ".join(rule_ids))
                    if sources:
                        notes.append("sources: " + ", ".join(sources))
                    if requested_qualifiers:
                        notes.append("context: " + ", ".join(
                            f"{name}={value}"
                            for name, value in requested_qualifiers))
                    notes.append("wording sources: "
                                 + ", ".join(frame_evidence["sources"]))
                    lines.append(f"Derived: {sentence} [{'; '.join(notes)}]")

        if not grouped and not statements and not conflicts:
            reasons = sorted({str(item.get("reason")) for item in omitted
                              if item.get("reason")})
            text = (f"No stored or proven facts match {canonical_subject}."
                    if not reasons else
                    f"Could not complete writing for {canonical_subject}: "
                    + "; ".join(reasons) + ".")
            return WritingResult(
                "unknown", canonical_subject, [], [], omitted,
                text)

        for indexes, sentence_line in self._coordinated_writing_lines(statements):
            lines[indexes[0]] = sentence_line
            for index in indexes[1:]:
                lines[index] = ""
        for statement in statements:
            statement.pop("_line_index", None)
        lines = [line for line in lines if line]

        if conflicts and not statements:
            status = "ambiguous"
        elif statements and (conflicts or omitted):
            status = "partial"
        elif statements:
            status = "written"
        elif any(item.get("reason") != "no learned sentence frame"
                 for item in omitted):
            status = "unknown"
        else:
            status = "no_licensed_frame"
            lines = [f"Stored facts match {canonical_subject}, but no learned "
                     "sentence frame can write them yet."]
        return WritingResult(status, canonical_subject, statements, conflicts,
                             omitted, "\n".join(lines))

    def write_timeline(self, subject: str, *, order_by: str = "year",
                       qualifiers: Mapping[str, str] | None = None
                       ) -> WritingResult:
        """Write a source-grounded timeline ordered by explicit year/date facts.

        This composes existing event facts and learned sentence frames. It does
        not infer chronology, causality, or connective prose from relation order.
        """
        canonical_subject = self._canonical_subject_display(
            _display(subject, "subject"))
        subject_key = _tokens(canonical_subject)
        order_name = _display(order_by, "order qualifier")
        order_key = _tokens(order_name)
        requested_qualifiers = self._normalize_qualifiers(qualifiers)
        grouped: dict[tuple[Any, ...], dict[bool, FactEvidence]] = {}
        for polarity, store in ((True, self._facts), (False, self._negative_facts)):
            for fact in store.values():
                if (_tokens(self._canonicalize_entity(fact.subject)) != subject_key
                        or not self._has_qualifiers(fact, requested_qualifiers)
                        or _tokens(fact.relation) == _tokens("has relation type")):
                    continue
                scope = {tuple(_tokens(name)): value
                         for name, value in fact.qualifiers}
                if order_key not in scope:
                    continue
                key = self._fact_key(fact.subject, fact.relation, fact.object,
                                     fact.qualifiers)
                grouped.setdefault(key, {})[polarity] = fact

        statements: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        omitted: list[dict[str, Any]] = []
        lines = [f"Timeline for {canonical_subject}, ordered by {order_name}:"]
        events = []
        precisions = set()
        for key in sorted(grouped):
            polarities = grouped[key]
            if True in polarities and False in polarities:
                conflict = {"positive": asdict(polarities[True]),
                            "negative": asdict(polarities[False])}
                conflicts.append(conflict)
                lines.append(
                    f"Not ordered: conflicting evidence for "
                    f"{polarities[True].relation} → {polarities[True].object} "
                    f"in {order_name}={dict(polarities[True].qualifiers).get(order_name)}.")
                continue
            fact = polarities.get(True)
            if fact is None:
                continue
            value = next((value for name, value in fact.qualifiers
                          if _tokens(name) == order_key), None)
            order_match = re.fullmatch(r"\d{4}(?:-\d{2}-\d{2})?", value or "")
            if order_match is None:
                omitted.append(asdict(fact) | {
                    "reason": f"{order_name} must use YYYY or YYYY-MM-DD"})
                lines.append(
                    f"Not ordered: {fact.relation} → {fact.object} has an "
                    f"unsupported {order_name} value {value!r}.")
                continue
            if len(value) == 4:
                precision, order_value = "year", (int(value),)
            else:
                try:
                    parsed = date.fromisoformat(value)
                except ValueError:
                    omitted.append(asdict(fact) | {
                        "reason": f"invalid {order_name} date"})
                    lines.append(
                        f"Not ordered: {fact.relation} → {fact.object} has an "
                        f"invalid {order_name} date {value!r}.")
                    continue
                precision, order_value = "date", (parsed.year, parsed.month,
                                                    parsed.day)
            precisions.add(precision)
            frame_rows = self._realize_fact_patterns(
                fact.subject, fact.relation, fact.object, polarity=True)
            if not frame_rows:
                omitted.append(asdict(fact) | {
                    "reason": "no learned sentence frame"})
                lines.append(
                    f"Not written: no learned sentence frame for "
                    f"{fact.relation} → {fact.object}.")
                continue
            events.append((order_value, key, fact, value, frame_rows))

        if len(precisions) > 1:
            for _order, _key, fact, value, _frames in events:
                omitted.append(asdict(fact) | {
                    "reason": "mixed year and full-date precision"})
                lines.append(
                    f"Not ordered: {fact.relation} → {fact.object} uses "
                    f"{value}, which cannot be ranked against the other "
                    f"{order_name} precision.")
            events = []
        events.sort(key=lambda item: (item[0], item[1]))
        for _order, _key, fact, value, frame_rows in events:
            frame = frame_rows[0]
            prefix = "In" if len(value) == 4 else "On"
            sentence = f"{prefix} {value}, {frame['sentence']}"
            statement = {
                "sentence": sentence,
                "event_sentence": frame["sentence"],
                "order_by": order_name,
                "order_value": value,
                "frame_evidence": frame,
                "fact": asdict(fact),
                "polarity": True,
            }
            statements.append(statement)
            lines.append(
                f"{sentence} [sources: {', '.join(fact.sources)}; wording "
                f"sources: {', '.join(frame['sources'])}].")

        if statements and not conflicts and not omitted:
            status = "written"
        elif statements:
            status = "partial"
        elif conflicts:
            status = "ambiguous"
        else:
            status = "unknown"
            if not grouped:
                lines.append(
                    f"No facts with an explicit {order_name} are stored for "
                    f"{canonical_subject}.")
        return WritingResult(status, canonical_subject, statements,
                             conflicts, omitted, "\n".join(lines))

    def facts(self) -> list[FactEvidence]:
        if isinstance(self._facts, SQLiteFactMap):
            return sorted(self._facts.values(), key=lambda fact: self._fact_key(
                fact.subject, fact.relation, fact.object,
                self._normalize_qualifiers(dict(fact.qualifiers))))
        return [self._facts[key] for key in sorted(self._facts)]

    def negative_facts(self) -> list[FactEvidence]:
        if isinstance(self._negative_facts, SQLiteFactMap):
            return sorted(self._negative_facts.values(), key=lambda fact: self._fact_key(
                fact.subject, fact.relation, fact.object,
                self._normalize_qualifiers(dict(fact.qualifiers))))
        return [self._negative_facts[key] for key in sorted(self._negative_facts)]

    def _facts_for_object(self, obj: str) -> list[FactEvidence]:
        """Return positive facts for an object using the endpoint index."""
        object_key = _tokens(self._canonicalize_entity(obj))
        if isinstance(self._facts, SQLiteFactMap):
            candidates = self._facts.lookup_object(object_key)
        else:
            keys = self._facts_by_object.get(object_key, ())
            candidates = (self._facts[key] for key in keys)
        return sorted(
            (fact for fact in candidates
             if _tokens(fact.object) == object_key),
            key=lambda fact: (fact.subject.casefold(), fact.relation.casefold(),
                              fact.object.casefold()))

    def _find_fact(self, relation: str, bound_field: str,
                   bound_value: str, answer: str,
                   qualifiers: tuple[tuple[str, str], ...] = ()
                   ) -> list[FactEvidence]:
        relation_key = _tokens(relation)
        bound_key = _tokens(self._canonicalize_entity(bound_value))
        answer_key = _tokens(self._canonicalize_entity(answer))
        if isinstance(self._facts, SQLiteFactMap):
            candidate_facts = self._facts.lookup(
                relation_key, bound_key, bound_field)
        else:
            index = (self._facts_by_relation_object if bound_field == "object"
                     else self._facts_by_relation_subject)
            candidate_keys = index.get((relation_key, bound_key), ())
            candidate_facts = (self._facts[key] for key in candidate_keys)
        matches = []
        for fact in candidate_facts:
            bound = fact.object if bound_field == "object" else fact.subject
            value = fact.subject if bound_field == "object" else fact.object
            if (_tokens(bound) == bound_key and _tokens(value) == answer_key
                    and self._has_qualifiers(fact, qualifiers)):
                matches.append(fact)
        return sorted(matches, key=lambda fact: (fact.subject, fact.relation, fact.object))

    def _relation_has_inference_schema(
            self, relation: str,
            qualifiers: tuple[tuple[str, str], ...] = ()) -> bool:
        relation_key = _tokens(relation)
        if any(_tokens(rule.conclusion_relation) == relation_key
               for rule in self._inference_rules.values()):
            return True
        return any(
            _tokens(fact.subject) == relation_key
            and _tokens(fact.relation) == _tokens("has relation type")
            and _tokens(fact.object) in {
                _tokens("transitive"), _tokens("irreflexive"),
                _tokens("asymmetric"), _tokens("closed-world")}
            and self._scope_is_within(fact.qualifiers, qualifiers)
            for fact in self._facts.values())

    def _relation_type_fact(
            self, relation: str, relation_type: str,
            qualifiers: tuple[tuple[str, str], ...] = ()
            ) -> FactEvidence | None:
        """Return a declaration whose scope is covered by the query context."""
        if isinstance(self._facts, SQLiteFactMap):
            candidates = self._facts.lookup(
                _tokens("has relation type"), _tokens(relation), "subject")
        else:
            candidates = self._facts.values()
        return next((fact for fact in candidates
                     if _tokens(fact.subject) == _tokens(relation)
                     and _tokens(fact.relation) == _tokens("has relation type")
                     and _tokens(fact.object) == _tokens(relation_type)
                     and self._scope_is_within(fact.qualifiers, qualifiers)), None)

    def _inference_relation_names(
            self, qualifiers: tuple[tuple[str, str], ...] = ()) -> list[str]:
        relations = {rule.conclusion_relation
                     for rule in self._inference_rules.values()}
        relations.update(
            fact.subject for fact in self._facts.values()
            if (_tokens(fact.relation) == _tokens("has relation type")
                and _tokens(fact.object) in {
                    _tokens("transitive"), _tokens("irreflexive"),
                    _tokens("asymmetric"), _tokens("closed-world")}
                and self._scope_is_within(fact.qualifiers, qualifiers)))
        return sorted(relations, key=_tokens)

    def teach_question(self, question: str, *, relation: str,
                       answer_field: str, bound_entity: str,
                       answer: str,
                       qualifiers: Mapping[str, str] | None = None) -> bool:
        """Ground one question to fact or verified inference; return frame state.

        ``answer_field`` is ``subject`` or ``object``. The opposite endpoint
        must be named in the question as ``bound_entity``. An example is
        rejected unless the corresponding fact or verified rule proof exists.
        """
        if answer_field not in ("subject", "object"):
            raise ValueError("answer_field must be 'subject' or 'object'")
        question = _display(question, "question")
        relation = _display(relation, "relation")
        bound_entity = _display(bound_entity, "bound_entity")
        answer = _display(answer, "answer")
        bound_field = "object" if answer_field == "subject" else "subject"
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        direct = self._find_fact(
            relation, bound_field, bound_entity, answer, normalized_qualifiers)
        inferred = None
        if not normalized_qualifiers:
            subject, obj = ((answer, bound_entity) if answer_field == "subject"
                            else (bound_entity, answer))
            inferred = self.infer_relation(subject, relation, obj)
        if not direct and not (inferred and inferred.status == "answered"):
            raise ValueError("question example is not supported by a stored fact or verified rule proof")
        if inferred and inferred.status == "ambiguous":
            raise ValueError("conflicting evidence cannot license a question example")

        words = _tokens(question)
        entity_words = _tokens(bound_entity)
        positions = [index for index in range(len(words) - len(entity_words) + 1)
                     if words[index:index + len(entity_words)] == entity_words]
        if len(positions) != 1:
            raise ValueError("bound entity must occur exactly once in the question")
        start = positions[0]
        end = start + len(entity_words)
        prefix, suffix = words[:start], words[end:]
        key = (json.dumps(list(_tokens(relation)), ensure_ascii=False),
               answer_field, prefix, suffix)
        entities = self._question_examples.setdefault(key, {})
        entities.setdefault(entity_words, set()).add(" ".join(entity_words))
        evidence_record = {
            "answer": answer,
            "conclusion": {"subject": (answer if answer_field == "subject"
                                         else bound_entity),
                           "relation": relation,
                           "object": (bound_entity if answer_field == "subject"
                                      else answer)},
            "qualifiers": list(normalized_qualifiers),
            "direct_facts": [asdict(fact) for fact in direct],
            "proofs": ([copy.deepcopy(proof) for proof in inferred.proofs]
                       if inferred and inferred.status == "answered" else []),
        }
        evidence_by_entity = self._question_example_evidence.setdefault(key, {})
        records = evidence_by_entity.setdefault(entity_words, [])
        encoded_record = json.dumps(evidence_record, sort_keys=True,
                                    ensure_ascii=False)
        if all(json.dumps(item, sort_keys=True, ensure_ascii=False)
               != encoded_record for item in records):
            records.append(evidence_record)
            records.sort(key=lambda item: json.dumps(
                item, sort_keys=True, ensure_ascii=False))
        return self._question_frame_is_licensed(key, entities)

    def _question_frame_is_licensed(
            self, key: tuple[str, str, tuple[str, ...], tuple[str, ...]],
            entities: Mapping[tuple[str, ...], Any]) -> bool:
        """Check exact-frame evidence or transfer from a licensed relation frame."""
        if len(entities) >= 2:
            return True
        if len(entities) != 1:
            return False
        relation_repr, answer_field, _prefix, _suffix = key
        relation = tuple(json.loads(relation_repr))
        return any(
            tuple(json.loads(other_relation)) == relation
            and other_answer_field == answer_field
            and len(other_entities) >= 2
            for (other_relation, other_answer_field, _other_prefix, _other_suffix),
            other_entities in self._question_examples.items()
            if (other_relation, other_answer_field, _other_prefix, _other_suffix) != key
        )

    def teach_subject_pattern_question(
            self, question: str, *, relation: str, answer_field: str,
            bound_entity: str, answer: str) -> bool:
        """Teach a question slot that maps into a fact endpoint pattern.

        Every example must resolve to exactly one accepted direct fact, and the
        question's bound entity must occur once inside the opposite fact
        endpoint. The resulting frame activates only after two distinct
        entity-pattern examples agree on relation, roles, and wording.
        """
        if answer_field not in {"subject", "object"}:
            raise ValueError("answer_field must be 'subject' or 'object'")
        question = _display(question, "question")
        relation = _display(relation, "relation")
        bound_entity = _display(bound_entity, "bound_entity")
        answer = _display(answer, "answer")
        question_words = _tokens(question)
        bound_words = _tokens(bound_entity)
        positions = [index for index in range(
            len(question_words) - len(bound_words) + 1)
            if bound_words and question_words[index:index + len(bound_words)]
            == bound_words]
        if len(positions) != 1:
            raise ValueError("bound entity must occur exactly once in the question")
        question_start = positions[0]
        question_end = question_start + len(bound_words)
        question_prefix = question_words[:question_start]
        question_suffix = question_words[question_end:]

        fact_bound_field = "object" if answer_field == "subject" else "subject"
        relation_key = _tokens(relation)
        answer_key = _tokens(answer)
        matches = []
        for fact in self._facts.values():
            if (_tokens(fact.relation) != relation_key or fact.qualifiers
                    or _tokens(getattr(fact, answer_field)) != answer_key):
                continue
            endpoint = _tokens(getattr(fact, fact_bound_field))
            endpoint_positions = [index for index in range(
                len(endpoint) - len(bound_words) + 1)
                if endpoint[index:index + len(bound_words)] == bound_words]
            if len(endpoint_positions) != 1:
                continue
            fact_start = endpoint_positions[0]
            fact_end = fact_start + len(bound_words)
            matches.append((fact, endpoint[:fact_start], endpoint[fact_end:]))
        if len(matches) != 1:
            raise ValueError(
                "example must match exactly one direct fact whose endpoint "
                "contains the bound entity once")
        fact, fact_prefix, fact_suffix = matches[0]
        if self._fact_key(fact.subject, fact.relation, fact.object,
                          fact.qualifiers) in self._negative_facts:
            raise ValueError("conflicting direct evidence cannot teach a question pattern")
        key = (json.dumps(list(relation_key), ensure_ascii=False), answer_field,
               question_prefix, question_suffix, fact_bound_field,
               fact_prefix, fact_suffix)
        examples = self._subject_pattern_question_examples.setdefault(key, {})
        answers = examples.setdefault(bound_words, set())
        if answers and answer not in answers:
            raise ValueError(
                "the same bound entity has conflicting answers in this frame")
        answers.add(answer)
        return (len(examples) >= 2
                and all(len(values) == 1 for values in examples.values()))

    def _ask_subject_pattern_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Answer only through a licensed frame and an exact direct fact."""
        if not self._subject_pattern_question_examples:
            return None
        matches = []
        recognized = False
        for key, examples in self._subject_pattern_question_examples.items():
            (relation_repr, answer_field, question_prefix, question_suffix,
             fact_bound_field, fact_prefix, fact_suffix) = key
            if any(len(answers) != 1 for answers in examples.values()):
                continue
            relation = tuple(json.loads(relation_repr))
            relation_text = " ".join(relation)
            active_examples = []
            for entity, answers in examples.items():
                endpoint = fact_prefix + entity + fact_suffix
                endpoint_text = " ".join(endpoint)
                support = []
                for answer in answers:
                    direct = self._find_fact(
                        relation_text, fact_bound_field, endpoint_text, answer, ())
                    for fact in direct:
                        if fact.qualifiers:
                            continue
                        fact_key = self._fact_key(
                            fact.subject, fact.relation, fact.object, fact.qualifiers)
                        if fact_key not in self._negative_facts:
                            support.append(fact)
                if support:
                    active_examples.append({
                        "entity": " ".join(entity),
                        "answer": next(iter(answers)),
                        "sources": sorted({source for fact in support
                                           for source in fact.sources}),
                    })
            if len(active_examples) < 2:
                continue
            if (len(words) <= len(question_prefix) + len(question_suffix)
                    or words[:len(question_prefix)] != question_prefix
                    or (question_suffix
                        and words[-len(question_suffix):] != question_suffix)):
                continue
            bound_end = len(words) - len(question_suffix) if question_suffix else len(words)
            bound = words[len(question_prefix):bound_end]
            if not bound:
                continue
            recognized = True
            endpoint = fact_prefix + bound + fact_suffix
            facts = [fact for fact in self._facts.values()
                     if (_tokens(fact.relation) == relation
                         and self._has_qualifiers(fact, qualifiers)
                         and _tokens(getattr(fact, fact_bound_field)) == endpoint)]
            negatives = [fact for fact in self._negative_facts.values()
                         if (_tokens(fact.relation) == relation
                             and self._has_qualifiers(fact, qualifiers)
                             and _tokens(getattr(fact, fact_bound_field)) == endpoint
                             and any(_tokens(getattr(positive, answer_field))
                                     == _tokens(getattr(fact, answer_field))
                                     for positive in facts))]
            answers = {_tokens(getattr(fact, answer_field)): fact
                       for fact in facts}
            frame = {
                "kind": "subject_pattern_question_frame",
                "relation": " ".join(relation),
                "answer_field": answer_field,
                "bound_entity": " ".join(bound),
                "fact_endpoint_pattern": " ".join(
                    fact_prefix + ("{entity}",) + fact_suffix),
                "training_examples": active_examples,
            }
            evidence = [asdict(fact) for fact in facts]
            evidence.extend(asdict(fact) for fact in negatives)
            template = (" ".join(question_prefix + ("{entity}",) + question_suffix)
                        + " [fact endpoint: "
                        + " ".join(fact_prefix + ("{entity}",) + fact_suffix)
                        + "]")
            matches.append((answers, evidence, frame, template, bool(negatives)))

        if not recognized:
            return None
        if len(matches) != 1:
            return QuestionResult(
                "unknown", request=("More than one learned subject-pattern frame "
                                    "matches this wording; please clarify the relation."))
        answers, evidence, frame, template, conflict = matches[0]
        if conflict or len(answers) > 1:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    {str(item.get("object" if frame["answer_field"] == "object"
                                 else "subject")) for item in evidence}),
                evidence=evidence or None, matched_templates=[template],
                language_evidence=[frame],
                request="The learned role frame finds conflicting direct evidence.")
        if not answers:
            return QuestionResult(
                "unknown", evidence=None, matched_templates=[template],
                language_evidence=[frame],
                request=("The learned wording is recognized, but no direct fact "
                         "matches this entity and relation."))
        fact = next(iter(answers.values()))
        answer = getattr(fact, frame["answer_field"])
        return QuestionResult(
            "answered", answer=answer, candidates=[answer],
            evidence=evidence, matched_templates=[template],
            language_evidence=[frame])

    def _optional_question_word_evidence(
            self, qualifiers: tuple[tuple[str, str], ...]
            ) -> dict[tuple[str, str, tuple[str, ...], tuple[str, ...]],
                      list[dict[str, Any]]]:
        """Find short optional-phrase variants with aligned fact evidence.

        Each side must have the same relation and answer direction, differ by
        one contiguous phrase of at most three non-relation tokens, and agree
        on the answer for at least two shared bound entities. Parsing uses the
        phrase only at its observed position and retains its source support.
        """
        records_by_frame: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]],
            dict[str, dict[str, Any]]] = {}
        keys = sorted(self._question_examples)
        shared_frame_signatures: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]], set[Any]
        ] = {}
        for key in keys:
            relation_repr, answer_field, prefix, suffix = key
            relation_tokens = tuple(json.loads(relation_repr))
            shared_frame_signatures.setdefault(key, set()).add(key)
            for side, frame_words in (("prefix", prefix), ("suffix", suffix)):
                for span_length in range(1, min(3, len(frame_words)) + 1):
                    for start in range(len(frame_words) - span_length + 1):
                        phrase = frame_words[start:start + span_length]
                        remaining_length = (len(prefix) + len(suffix)
                                            - span_length)
                        if (set(phrase) & set(relation_tokens)
                                or remaining_length < 1):
                            continue
                        if side == "prefix":
                            signature = (
                                relation_repr, answer_field,
                                prefix[:start] + prefix[start + span_length:],
                                suffix)
                        else:
                            signature = (
                                relation_repr, answer_field, prefix,
                                suffix[:start] + suffix[start + span_length:])
                        shared_frame_signatures.setdefault(signature, set()).add(key)
        candidate_pairs = sorted({
            tuple(sorted((first, second)))
            for members in shared_frame_signatures.values()
            for first in members for second in members if first != second
        })
        if not candidate_pairs:
            return {}
        fact_answers: dict[
            tuple[tuple[str, ...], str, tuple[str, ...]],
            dict[tuple[str, ...], dict[str, Any]]] = {}
        for fact in self._facts.values():
            if not self._qualifiers_equal(fact.qualifiers, qualifiers):
                continue
            relation_tokens = _tokens(fact.relation)
            for answer_field, bound_field in (("subject", "object"),
                                              ("object", "subject")):
                entity_key = _tokens(getattr(fact, bound_field))
                value = fact.subject if answer_field == "subject" else fact.object
                values = fact_answers.setdefault(
                    (relation_tokens, answer_field, entity_key), {})
                entry = values.setdefault(_tokens(value), {
                    "answer": value, "sources": set()})
                entry["sources"].update(fact.sources)

        for first_key, second_key in candidate_pairs:
            relation_repr, answer_field, first_prefix, first_suffix = first_key
            relation_tokens = tuple(json.loads(relation_repr))
            first_entities = self._question_examples[first_key]
            other_relation, other_field, second_prefix, second_suffix = second_key
            if other_relation != relation_repr or other_field != answer_field:
                continue
            if first_suffix == second_suffix:
                difference = ("prefix", first_prefix, second_prefix)
            elif first_prefix == second_prefix:
                difference = ("suffix", first_suffix, second_suffix)
            else:
                continue
            side, left, right = difference
            shorter, longer = sorted((left, right), key=len)
            if len(longer) <= len(shorter) or len(longer) - len(shorter) > 3:
                continue
            insertions = [
                (start, longer[start:end])
                for start in range(len(longer))
                for end in range(start + 1, min(len(longer), start + 3) + 1)
                if longer[:start] + longer[end:] == shorter]
            if len(insertions) != 1:
                continue
            insertion_index, phrase = insertions[0]
            if set(phrase) & set(relation_tokens):
                continue
            if side == "prefix":
                base_key, variant_key = (
                    (first_key, second_key) if first_prefix == shorter
                    else (second_key, first_key))
                base_prefix, base_suffix = base_key[2], base_key[3]
                variant_prefix, variant_suffix = variant_key[2], variant_key[3]
            else:
                base_key, variant_key = (
                    (first_key, second_key) if first_suffix == shorter
                    else (second_key, first_key))
                base_prefix, base_suffix = base_key[2], base_key[3]
                variant_prefix, variant_suffix = variant_key[2], variant_key[3]
            second_entities = self._question_examples[second_key]
            support = []
            for entity_key in sorted(set(first_entities) & set(second_entities)):
                answers = fact_answers.get(
                    (relation_tokens, answer_field, entity_key), {})
                if len(answers) != 1:
                    continue
                answer_key = next(iter(answers))
                support.append({
                    "bound_entity": " ".join(entity_key),
                    "answer": answers[answer_key]["answer"],
                    "sources": sorted(answers[answer_key]["sources"]),
                })
            if len(support) < 2:
                continue

            def template(key: tuple[str, str, tuple[str, ...], tuple[str, ...]]) -> str:
                prefix, suffix = key[2], key[3]
                slot = "object" if answer_field == "subject" else "subject"
                return " ".join(prefix + ("{" + slot + "}",) + suffix)

            record = {
                "kind": ("optional_question_word" if len(phrase) == 1
                         else "optional_question_phrase"),
                "word": phrase[0] if len(phrase) == 1 else " ".join(phrase),
                "words": list(phrase),
                "side": side,
                "position": insertion_index,
                "base_prefix": list(base_prefix),
                "base_suffix": list(base_suffix),
                "variant_prefix": list(variant_prefix),
                "variant_suffix": list(variant_suffix),
                "equivalent_frames": sorted((template(first_key),
                                              template(second_key))),
                "support": support,
            }
            encoded = json.dumps(record, sort_keys=True, ensure_ascii=False)
            records_by_frame.setdefault(first_key, {})[encoded] = record
            records_by_frame.setdefault(second_key, {})[encoded] = record
        return {key: list(records.values())
                for key, records in records_by_frame.items()}

    @staticmethod
    def _optional_question_frame_variants(
            prefix: tuple[str, ...], suffix: tuple[str, ...],
            evidence: Iterable[Mapping[str, Any]], *, max_variants: int = 32
            ) -> list[tuple[tuple[str, ...], tuple[str, ...],
                            list[dict[str, Any]]]]:
        """Compose a bounded set of independently evidenced token options."""
        choices_by_position: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
        for item in evidence:
            if (tuple(item.get("base_prefix", ())) != prefix
                    or tuple(item.get("base_suffix", ())) != suffix):
                continue
            position = (str(item["side"]), int(item["position"]))
            choices_by_position.setdefault(position, {})[
                json.dumps(item.get("words", [item["word"]]),
                           ensure_ascii=False)] = dict(item)
        groups = sorted(choices_by_position.items())
        variants = [(prefix, suffix, [])]
        for (side, position), choices in groups:
            expanded = list(variants)
            for old_prefix, old_suffix, selected in variants:
                for item in choices.values():
                    prefix_words = list(old_prefix)
                    suffix_words = list(old_suffix)
                    tokens = prefix_words if side == "prefix" else suffix_words
                    offset = sum(
                        len(prior.get("words", [prior.get("word", "")]))
                        for prior in selected
                        if prior.get("side") == side
                        and int(prior.get("position", -1)) <= position)
                    insert_at = position + offset
                    if insert_at > len(tokens):
                        continue
                    optional_words = list(item.get("words", [item["word"]]))
                    tokens[insert_at:insert_at] = optional_words
                    expanded.append((tuple(prefix_words), tuple(suffix_words),
                                     selected + [item]))
                    if len(expanded) >= max_variants:
                        break
                if len(expanded) >= max_variants:
                    break
            variants = expanded[:max_variants]
        return variants

    def accept_question_frame_proposal(self, artifact_id: str) -> bool:
        """Retain a current source-separated question-frame proposal.

        The proposal is regenerated and its held-out checks rerun before it is
        accepted. The resulting frame stays outside teacher examples and is
        usable only while its cited lineage remains current.
        """
        if not isinstance(artifact_id, str):
            raise TypeError("artifact_id must be a string")
        from crms_question_induction import (
            propose_analogical_question_frames,
            propose_analogical_qualified_question_frames,
            propose_analogical_multi_qualified_question_frames,
            question_frame_proposal_sources_current)
        from crms_question_role_induction import (
            propose_active_role_alternation_frames)
        current = next((proposal for proposal in (
            propose_analogical_question_frames(self)
            + propose_analogical_qualified_question_frames(self)
            + propose_analogical_multi_qualified_question_frames(self)
            + propose_active_role_alternation_frames(self))
            if proposal.get("artifact_id") == artifact_id), None)
        if current is None or not question_frame_proposal_sources_current(self, current):
            raise ValueError("question-frame proposal is stale or no longer validated")
        if current.get("kind") == "analogical_qualified_question_frame":
            key = (tuple(_tokens(current["target_relation"])),
                   str(current["answer_field"]),
                   tuple(_tokens(current["qualifier_name"])),
                   bool(current["entity_first"]), tuple(current["prefix"]),
                   tuple(current["middle"]), tuple(current["suffix"]))
            if key in self._qualified_question_examples:
                return False
            prior = self._induced_qualified_question_frames.get(key)
            if (prior is not None and
                    question_frame_proposal_sources_current(self, prior)):
                return False
            self._induced_qualified_question_frames[key] = copy.deepcopy(current)
            return True
        if current.get("kind") == "analogical_multi_qualified_question_frame":
            key = (tuple(_tokens(current["target_relation"])),
                   str(current["answer_field"]),
                   tuple(tuple(_tokens(name))
                         for name in current["qualifier_names"]),
                   tuple(current["pattern"]))
            if key in self._multi_qualified_question_examples:
                return False
            prior = self._induced_multi_qualified_question_frames.get(key)
            if (prior is not None and
                    question_frame_proposal_sources_current(self, prior)):
                return False
            self._induced_multi_qualified_question_frames[key] = copy.deepcopy(current)
            return True
        key = (json.dumps(current["target_relation"].split(), ensure_ascii=False),
               str(current["answer_field"]), tuple(current["prefix"]),
               tuple(current["suffix"]))
        if key in self._question_examples:
            return False
        prior = self._induced_question_frames.get(key)
        if (prior is not None and
                question_frame_proposal_sources_current(self, prior)):
            return False
        self._induced_question_frames[key] = copy.deepcopy(current)
        return True

    def _question_frames_for_ask(self) -> tuple[
            dict[tuple[str, str, tuple[str, ...], tuple[str, ...]],
                 dict[tuple[str, ...], set[str]]],
            dict[tuple[str, str, tuple[str, ...], tuple[str, ...]], dict[str, Any]]]:
        frames = {key: copy.deepcopy(examples)
                  for key, examples in self._question_examples.items()}
        active_induced: dict[
            tuple[str, str, tuple[str, ...], tuple[str, ...]], dict[str, Any]
        ] = {}
        from crms_question_induction import question_frame_proposal_sources_current
        for key, proposal in self._induced_question_frames.items():
            if key in frames or not question_frame_proposal_sources_current(self, proposal):
                continue
            examples = {tuple(row["bound_entity"].casefold().split()):
                        {row["bound_entity"]}
                        for row in proposal["lineage"]["training_examples"]}
            if len(examples) < 2:
                continue
            frames[key] = examples
            active_induced[key] = proposal

        # A licensed active fact sentence already supplies a checked mapping
        # from its surface predicate to a canonical relation. Derive the two
        # elementary endpoint questions from that structure instead of making
        # the teacher repeat the same mapping as question/answer examples.
        # These frames are rebuilt from current fact-pattern support on every
        # ask, so retracting a source removes the derived language rule.
        for pattern_key, pair_sources in self._fact_pattern_examples.items():
            template, relation = pattern_key
            active_svo = template == (
                "<subject>", "<predicate>", "<object>")
            passive_svo = template == (
                "<object>", "was", "<predicate>", "by", "<subject>")
            if (not self._fact_pattern_is_licensed(pattern_key, pair_sources)
                    or not self._fact_pattern_polarities.get(pattern_key, True)
                    or not (active_svo or passive_svo)):
                continue
            for predicate in sorted(self._fact_pattern_predicates.get(
                    pattern_key, set())):
                predicate_sources = self._fact_pattern_predicate_sources.get(
                    pattern_key, {}).get(predicate, {})
                supported_pairs = []
                for pair, example_sources in pair_sources.items():
                    aligned_sources = predicate_sources.get(pair, set())
                    sources = sorted(set(example_sources).intersection(aligned_sources))
                    if not sources:
                        continue
                    subject_key, object_key = pair
                    supported_fact = self._facts.get(self._fact_key(
                        " ".join(subject_key), " ".join(relation),
                        " ".join(object_key)))
                    if (supported_fact is None
                            or not set(supported_fact.sources).intersection(sources)):
                        continue
                    supported_pairs.append({
                        "subject": " ".join(subject_key),
                        "object": " ".join(object_key),
                        "sources": sorted(set(supported_fact.sources)
                                          .intersection(sources)),
                    })
                if (len(supported_pairs) < 2
                        or len({item["subject"] for item in supported_pairs}) < 2
                        or len({item["object"] for item in supported_pairs}) < 2):
                    continue

                if active_svo:
                    derived: list[
                        tuple[str, tuple[str, ...], tuple[str, ...], str]
                    ] = [("subject", ("who",) + predicate, (), "object")]
                    lemma = _base_verb_for_surface(predicate)
                    if lemma:
                        derived.append(("object", ("what", "did"), lemma,
                                        "subject"))
                    participle = _past_participle_for_surface(predicate)
                    if participle:
                        derived.extend((
                            ("subject", ("who", "was"),
                             participle + ("by",), "object"),
                            ("object", ("what", "was") + participle + ("by",),
                             (), "subject"),
                        ))
                else:
                    if not _is_past_participle(predicate):
                        continue
                    derived = [
                        ("subject", ("who", "was"), predicate + ("by",),
                         "object"),
                        ("object", ("what", "was") + predicate + ("by",),
                         (), "subject"),
                    ]
                    active_past = _past_tense_for_participle(predicate)
                    if active_past:
                        derived.append(("subject", ("who",) + active_past,
                                        (), "object"))
                    lemma = _base_verb_for_surface(predicate)
                    if lemma:
                        derived.append(("object", ("what", "did"), lemma,
                                        "subject"))

                for answer_field, prefix, suffix, bound_field in derived:
                    active_to_passive = (
                        active_svo and prefix[:2] in {
                            ("who", "was"), ("what", "was")})
                    passive_to_active = (
                        passive_svo and (
                            (prefix[:1] == ("who",)
                             and prefix[1:2] != ("was",))
                            or prefix[:2] == ("what", "did")))
                    frame_key = (json.dumps(list(relation), ensure_ascii=False),
                                 answer_field, prefix, suffix)
                    if frame_key in frames or frame_key in active_induced:
                        continue
                    examples = {}
                    for item in supported_pairs:
                        entity = item[bound_field]
                        examples.setdefault(_tokens(entity), set()).add(entity)
                    if len(examples) < 2:
                        continue
                    lineage_sources = sorted({source for item in supported_pairs
                                              for source in item["sources"]})
                    derivation = {
                        "kind": (
                            "passive_to_active_subject_question"
                            if passive_to_active and answer_field == "subject" else
                            "passive_to_active_object_question"
                            if passive_to_active else
                            "active_to_passive_subject_question"
                            if active_to_passive and answer_field == "subject" else
                            "active_to_passive_object_question"
                            if active_to_passive else
                            "fact_pattern_subject_question"
                            if active_svo and answer_field == "subject" else
                            "fact_pattern_do_support_object_question"
                            if active_svo else
                            "fact_pattern_passive_subject_question"
                            if answer_field == "subject" else
                            "fact_pattern_passive_object_question"),
                        "predicate_form": " ".join(predicate),
                        "rule": (
                            "who + learned active past + object"
                            if passive_to_active and answer_field == "subject" else
                            "what + did + subject + learned verb lemma"
                            if passive_to_active else
                            "who + was + object + learned participle + by"
                            if active_to_passive and answer_field == "subject" else
                            "what + was + learned participle + by + subject"
                            if active_to_passive and answer_field == "object" else
                            "who + active predicate + object"
                            if active_svo and answer_field == "subject" else
                            "what + did + subject + learned verb lemma"
                            if active_svo else
                            "who + was + object + predicate + by"
                            if answer_field == "subject" else
                            "what + was + predicate + by + subject"),
                        "licensed_sentence_pattern": " ".join(template),
                        "derived_question_frame": " ".join(
                            prefix + ("{" + bound_field + "}",) + suffix),
                        "supporting_examples": supported_pairs,
                    }
                    artifact_id = "fact-pattern-question:" + hashlib.sha256(
                        json.dumps([frame_key, lineage_sources], sort_keys=True,
                                   ensure_ascii=False).encode("utf-8")).hexdigest()[:20]
                    frames[frame_key] = examples
                    active_induced[frame_key] = {
                        "artifact_id": artifact_id,
                        "base_relation": " ".join(relation),
                        "target_relation": " ".join(relation),
                        "lineage": {
                            "training_source_documents": sorted({
                                source.split("#", 1)[0] for source in lineage_sources}),
                            "training_sources": lineage_sources,
                            "holdout_source_documents": [],
                        },
                        "derivation": derivation,
                    }
        return frames, active_induced

    def _ask_multi_qualified_question(
            self, words: tuple[str, ...],
            explicit: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Match multi-context frames only when their variable spans are unique."""
        if (not self._multi_qualified_question_examples
                and not self._induced_multi_qualified_question_frames):
            return None
        question_frames = {key: (examples, None)
                           for key, examples in
                           self._multi_qualified_question_examples.items()}
        from crms_question_induction import question_frame_proposal_sources_current
        for proposal in self._induced_multi_qualified_question_frames.values():
            if not question_frame_proposal_sources_current(self, proposal):
                continue
            relation = tuple(_tokens(proposal["target_relation"]))
            answer_field = str(proposal["answer_field"])
            qualifier_names = tuple(tuple(_tokens(name))
                                    for name in proposal["qualifier_names"])
            pattern = tuple(proposal["pattern"])
            frame_key = (relation, answer_field, qualifier_names, pattern)
            if frame_key in self._multi_qualified_question_examples:
                continue
            examples: dict[tuple[tuple[str, ...],
                                 tuple[tuple[str, ...], ...]], set[str]] = {}
            for row in proposal["lineage"]["training_examples"]:
                pair = (_tokens(row["bound_entity"]),
                        tuple(_tokens(value)
                              for value in row["qualifier_values"]))
                examples.setdefault(pair, set()).add(row["answer"])
            question_frames[frame_key] = (examples, proposal)
        induced_language_evidence = []
        known_entities: dict[tuple[str, ...], str] = {}
        for fact in list(self._facts.values()) + list(self._negative_facts.values()):
            known_entities[_tokens(fact.subject)] = fact.subject
            known_entities[_tokens(fact.object)] = fact.object

        for alias_tokens, record in self._entity_alias_records().items():
            known_entities[alias_tokens] = record["entity"]
        recognized = False
        answers: dict[tuple[str, ...], str] = {}
        evidence_by_key: dict[tuple[Any, ...], FactEvidence] = {}
        templates: set[str] = set()
        proofs: dict[str, dict[str, Any]] = {}
        conflict = False
        incomplete = False
        budget = 10_000

        for (relation, answer_field, qualifier_names, pattern), (
                examples, induced_proposal) in question_frames.items():
            entities = {entity for entity, _values in examples}
            if (len(examples) < 2 or len(entities) < 2
                    or any(len({values[index] for _entity, values in examples}) < 2
                           for index in range(len(qualifier_names)))):
                continue
            parses: list[dict[str, tuple[str, ...]]] = []
            match_steps = 0
            match_exhausted = False

            def match(pattern_index: int, word_index: int,
                      bindings: dict[str, tuple[str, ...]]) -> None:
                nonlocal match_steps, match_exhausted
                if len(parses) >= 2:
                    return
                match_steps += 1
                if match_steps > 10_000:
                    match_exhausted = True
                    return
                if pattern_index == len(pattern):
                    if word_index == len(words):
                        parses.append(dict(bindings))
                    return
                token = pattern[pattern_index]
                if token.startswith("\x00"):
                    if token == "\x00entity":
                        for entity_tokens in sorted(
                                known_entities, key=lambda item: (-len(item), item)):
                            end = word_index + len(entity_tokens)
                            if (entity_tokens and words[word_index:end] == entity_tokens):
                                bindings[token] = entity_tokens
                                match(pattern_index + 1, end, bindings)
                                bindings.pop(token, None)
                    else:
                        for end in range(word_index + 1, len(words) + 1):
                            bindings[token] = words[word_index:end]
                            match(pattern_index + 1, end, bindings)
                            bindings.pop(token, None)
                    return
                if word_index < len(words) and words[word_index] == token:
                    match(pattern_index + 1, word_index + 1, bindings)

            match(0, 0, {})
            if not parses:
                if match_exhausted:
                    recognized = True
                    incomplete = True
                continue
            recognized = True
            templates.add(" ".join(
                "{entity}" if token == "\x00entity" else
                "{" + " ".join(qualifier_names[int(token[2:])]) + "}"
                if token.startswith("\x00q") else token for token in pattern))
            if induced_proposal is not None:
                induced_language_evidence.append({
                    "kind": "induced_multi_qualified_question_frame",
                    "artifact_id": induced_proposal["artifact_id"],
                    "base_relation": induced_proposal["base_relation"],
                    "target_relation": induced_proposal["target_relation"],
                    "qualifier_names": induced_proposal["qualifier_names"],
                    "training_source_documents": induced_proposal[
                        "lineage"]["training_source_documents"],
                    "holdout_source_documents": induced_proposal[
                        "lineage"]["holdout_source_documents"],
                })
            if len(parses) != 1 or match_exhausted:
                incomplete = True
                continue
            bindings = parses[0]
            canonical = known_entities.get(bindings["\x00entity"])
            if canonical is None:
                continue
            context = {
                " ".join(name): " ".join(bindings["\x00q" + str(index)])
                for index, name in enumerate(qualifier_names)
            }
            invalid = False
            for name, value in explicit:
                existing = next((key for key in context
                                 if _tokens(key) == _tokens(name)), None)
                if existing is not None:
                    if _tokens(context[existing]) != _tokens(value):
                        invalid = True
                        break
                else:
                    context[name] = value
            if invalid:
                continue
            requested = self._normalize_qualifiers(context)
            scoped_entities = {
                _tokens(value): value
                for fact in self.facts() + self.negative_facts()
                if self._qualifiers_equal(fact.qualifiers, requested)
                and _tokens(fact.relation) != _tokens("has relation type")
                for value in (fact.subject, fact.object)
            }
            bound_field = "object" if answer_field == "subject" else "subject"
            matches = [fact for fact in self._facts.values()
                       if _tokens(fact.relation) == relation
                       and _tokens(fact.object if bound_field == "object" else fact.subject)
                       == _tokens(canonical)
                       and self._has_qualifiers(fact, requested)]
            for fact in matches:
                answer = fact.subject if answer_field == "subject" else fact.object
                answers.setdefault(_tokens(answer), answer)
                evidence_by_key[(fact.subject, fact.relation, fact.object,
                                 fact.qualifiers)] = fact
            if not self._relation_has_inference_schema(" ".join(relation), requested):
                continue
            if len(scoped_entities) > 256:
                incomplete = True
                continue
            for possible_answer in scoped_entities.values():
                if budget < 1:
                    incomplete = True
                    break
                subject, obj = ((possible_answer, canonical)
                                if answer_field == "subject"
                                else (canonical, possible_answer))
                inferred = self.infer_relation(
                    subject, " ".join(relation), obj,
                    qualifiers=dict(requested), max_expansions=budget)
                budget -= inferred.expansions
                if inferred.status == "unknown":
                    incomplete |= not inferred.complete
                elif inferred.status == "ambiguous":
                    conflict = True
                    for proof in inferred.proofs:
                        proofs[repr(proof)] = proof
                else:
                    for proof in inferred.proofs:
                        if _is_derived_proof(proof):
                            answers.setdefault(_tokens(possible_answer), possible_answer)
                            proofs[repr(proof)] = proof

        if not recognized:
            return None
        evidence = [asdict(evidence_by_key[key]) for key in sorted(evidence_by_key)]
        candidates = [answers[key] for key in sorted(answers)]
        proof_list = [proofs[key] for key in sorted(proofs)]
        if conflict:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=sorted(templates), inference_proofs=proof_list,
                request=("A contextual rule proof conflicts with explicit negative "
                         "evidence or a declared relation integrity constraint."),
                language_evidence=induced_language_evidence or None)
        if incomplete:
            return QuestionResult(
                "unknown", evidence=evidence, matched_templates=sorted(templates),
                inference_proofs=proof_list,
                request="Multi-context matching or bounded inference was ambiguous or incomplete.",
                language_evidence=induced_language_evidence or None)
        if not candidates:
            return QuestionResult(
                "unknown", evidence=evidence, matched_templates=sorted(templates),
                inference_proofs=proof_list,
                request="The qualified question frame is learned, but no matching fact or rule proof is stored.",
                language_evidence=induced_language_evidence or None)
        if len(candidates) > 1:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=sorted(templates), inference_proofs=proof_list,
                request="The qualified question has multiple supported answers.",
                language_evidence=induced_language_evidence or None)
        return QuestionResult(
            "answered", answer=candidates[0], candidates=candidates,
            evidence=evidence, matched_templates=sorted(templates),
            inference_proofs=proof_list,
            language_evidence=induced_language_evidence or None)

    def _ask_qualified_question(
            self, words: tuple[str, ...],
            explicit: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        if (not self._qualified_question_examples
                and not self._induced_qualified_question_frames):
            return None
        answers: dict[tuple[str, ...], str] = {}
        evidence_by_key: dict[tuple[Any, ...], FactEvidence] = {}
        templates: set[str] = set()
        recognized = False
        inference_proofs: list[dict[str, Any]] = []
        inference_conflict = False
        inference_incomplete = False
        inference_budget = 10_000
        known_entities: dict[tuple[str, ...], str] = {}
        for fact in self._facts.values():
            known_entities[_tokens(fact.subject)] = fact.subject
            known_entities[_tokens(fact.object)] = fact.object
        for alias_tokens, record in self._entity_alias_records().items():
            known_entities[alias_tokens] = record["entity"]
        question_frames = {key: (examples, None)
                           for key, examples
                           in self._qualified_question_examples.items()}
        from crms_question_induction import question_frame_proposal_sources_current
        for proposal in self._induced_qualified_question_frames.values():
            if not question_frame_proposal_sources_current(self, proposal):
                continue
            relation = tuple(_tokens(proposal["target_relation"]))
            answer_field = str(proposal["answer_field"])
            qualifier_name = tuple(_tokens(proposal["qualifier_name"]))
            frame_key = (relation, answer_field, qualifier_name,
                         bool(proposal["entity_first"]),
                         tuple(proposal["prefix"]), tuple(proposal["middle"]),
                         tuple(proposal["suffix"]))
            if frame_key in self._qualified_question_examples:
                continue
            examples: dict[tuple[tuple[str, ...], tuple[str, ...]], set[str]] = {}
            for row in proposal["lineage"]["training_examples"]:
                pair = (_tokens(row["bound_entity"]),
                        _tokens(row["qualifier_value"]))
                examples.setdefault(pair, set()).add(row["answer"])
            question_frames[frame_key] = (examples, proposal)

        induced_language_evidence = []
        for (relation_tokens, answer_field, qualifier_name, entity_first,
             prefix, middle, suffix), (examples, induced_proposal) in question_frames.items():
            entities = {entity for entity, _value in examples}
            values = {value for _entity, value in examples}
            if len(examples) < 2 or len(entities) < 2 or len(values) < 2:
                continue
            if len(words) <= len(prefix) + len(middle) + len(suffix):
                continue
            if words[:len(prefix)] != prefix:
                continue
            if suffix and words[-len(suffix):] != suffix:
                continue
            qualifier_end = len(words) - len(suffix) if suffix else len(words)
            qualifier_marker = "{" + " ".join(qualifier_name) + "}"
            template = " ".join(
                prefix + (("{entity}",) + middle + (qualifier_marker,)
                          if entity_first else
                          (qualifier_marker,) + middle + ("{entity}",)) + suffix)
            possible: set[tuple[tuple[str, ...], tuple[str, ...], str]] = set()
            for entity_tokens, canonical in known_entities.items():
                if not entity_tokens:
                    continue
                if entity_first:
                    entity_start = len(prefix)
                    entity_end = entity_start + len(entity_tokens)
                    if (words[entity_start:entity_end] != entity_tokens
                            or words[entity_end:entity_end + len(middle)] != middle):
                        continue
                    value_start = entity_end + len(middle)
                    value_tokens = words[value_start:qualifier_end]
                else:
                    entity_end = qualifier_end
                    entity_start = entity_end - len(entity_tokens)
                    value_end = entity_start - len(middle)
                    if (entity_start < len(prefix)
                            or words[entity_start:entity_end] != entity_tokens
                            or words[value_end:entity_start] != middle):
                        continue
                    value_tokens = words[len(prefix):value_end]
                if value_tokens:
                    possible.add((entity_tokens, value_tokens, canonical))
            if len(possible) != 1:
                continue
            _entity_tokens, value_tokens, canonical = next(iter(possible))
            qualifier_value = " ".join(value_tokens)
            context = {" ".join(qualifier_name): qualifier_value}
            for name, value in explicit:
                existing = next((v for k, v in context.items()
                                 if _tokens(k) == _tokens(name)), None)
                if existing is not None and _tokens(existing) != _tokens(value):
                    context = {}
                    break
                if existing is None:
                    context[name] = value
            if not context:
                continue
            requested = self._normalize_qualifiers(context)
            scoped_entities = {
                _tokens(value): value
                for fact in self.facts() + self.negative_facts()
                if self._qualifiers_equal(fact.qualifiers, requested)
                and _tokens(fact.relation) != _tokens("has relation type")
                for value in (fact.subject, fact.object)
            }
            bound_field = "object" if answer_field == "subject" else "subject"
            matches = [fact for fact in self._facts.values()
                       if _tokens(fact.relation) == relation_tokens
                       and _tokens(fact.object if bound_field == "object" else fact.subject)
                       == _tokens(canonical)
                       and self._has_qualifiers(fact, requested)]
            recognized = True
            templates.add(template)
            if induced_proposal is not None:
                induced_language_evidence.append({
                    "kind": "induced_qualified_question_frame",
                    "artifact_id": induced_proposal["artifact_id"],
                    "base_relation": induced_proposal["base_relation"],
                    "target_relation": induced_proposal["target_relation"],
                    "qualifier_name": induced_proposal["qualifier_name"],
                    "training_source_documents": induced_proposal[
                        "lineage"]["training_source_documents"],
                    "holdout_source_documents": induced_proposal[
                        "lineage"]["holdout_source_documents"],
                })
            for fact in matches:
                answer = fact.subject if answer_field == "subject" else fact.object
                answers.setdefault(_tokens(answer), answer)
                evidence_by_key[(fact.subject, fact.relation, fact.object,
                                 fact.qualifiers)] = fact
            if not self._relation_has_inference_schema(
                    " ".join(relation_tokens), requested):
                continue
            if len(scoped_entities) > 256:
                inference_incomplete = True
                continue
            for possible_answer in scoped_entities.values():
                if inference_budget < 1:
                    inference_incomplete = True
                    break
                subject, obj = (
                    (possible_answer, canonical) if answer_field == "subject"
                    else (canonical, possible_answer))
                inferred = self.infer_relation(
                    subject, " ".join(relation_tokens), obj,
                    qualifiers=dict(requested),
                    max_expansions=inference_budget)
                inference_budget -= inferred.expansions
                if inferred.status == "unknown":
                    inference_incomplete |= not inferred.complete
                    continue
                if inferred.status == "ambiguous":
                    inference_conflict = True
                    inference_proofs.extend(inferred.proofs)
                    continue
                rule_proofs = [proof for proof in inferred.proofs
                               if _is_derived_proof(proof)]
                if rule_proofs:
                    answers.setdefault(_tokens(possible_answer), possible_answer)
                    inference_proofs.extend(rule_proofs)

        if not recognized:
            return None
        evidence = [asdict(evidence_by_key[key])
                    for key in sorted(evidence_by_key)]
        candidates = [answers[key] for key in sorted(answers)]
        proof_by_key = {repr(proof): proof for proof in inference_proofs}
        inference_proofs = [proof_by_key[key] for key in sorted(proof_by_key)]
        if inference_conflict:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=sorted(templates),
                inference_proofs=inference_proofs,
                request=("A contextual rule proof conflicts with explicit negative "
                         "evidence or a declared relation integrity constraint."),
                language_evidence=induced_language_evidence or None)
        if inference_incomplete:
            return QuestionResult(
                "unknown", evidence=evidence, matched_templates=sorted(templates),
                inference_proofs=inference_proofs,
                request="Bounded contextual inference did not establish a complete answer set.",
                language_evidence=induced_language_evidence or None)
        if not candidates:
            return QuestionResult(
                "unknown", evidence=evidence,
                matched_templates=sorted(templates),
                inference_proofs=inference_proofs,
                request="The qualified question frame is learned, but no matching fact or rule proof is stored.",
                language_evidence=induced_language_evidence or None)
        if len(candidates) > 1:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=sorted(templates),
                inference_proofs=inference_proofs,
                request="The qualified question has multiple supported answers.",
                language_evidence=induced_language_evidence or None)
        return QuestionResult("answered", answer=candidates[0],
                              candidates=candidates, evidence=evidence,
                              matched_templates=sorted(templates),
                              inference_proofs=inference_proofs,
                              language_evidence=induced_language_evidence or None)

    def teach_qualified_question(
            self, question: str, *, relation: str, answer_field: str,
            bound_entity: str, answer: str,
            qualifier: Mapping[str, str]) -> bool:
        """Learn a question frame with one entity and one or more qualifier slots.

        Evidence must vary the bound entity and each qualifier value. Every
        example must match a fact or complete verified rule proof in that scope.
        """
        if answer_field not in {"subject", "object"}:
            raise ValueError("answer_field must be 'subject' or 'object'")
        normalized = self._normalize_qualifiers(qualifier)
        if len(normalized) > 1:
            return self._teach_multi_qualified_question(
                question, relation=relation, answer_field=answer_field,
                bound_entity=bound_entity, answer=answer,
                normalized=normalized)
        if len(normalized) != 1:
            raise ValueError("a qualified question requires at least one qualifier")
        question = _display(question, "question")
        relation = _display(relation, "relation")
        bound_entity = _display(bound_entity, "bound_entity")
        answer = _display(answer, "answer")
        bound_field = "object" if answer_field == "subject" else "subject"
        supported = self._find_fact(
            relation, bound_field, bound_entity, answer, normalized)
        if not supported:
            inferred_subject, inferred_object = (
                (answer, bound_entity) if answer_field == "subject"
                else (bound_entity, answer))
            inferred = self.infer_relation(
                inferred_subject, relation, inferred_object,
                qualifiers=dict(normalized))
            supported = (inferred.status == "answered" and inferred.complete
                         and any(_is_derived_proof(proof)
                                 for proof in inferred.proofs))
        if not supported:
            raise ValueError("qualified question example requires a matching fact or verified rule proof")

        words = _tokens(question)
        entity_words = _tokens(bound_entity)
        qualifier_value_words = _tokens(normalized[0][1])

        def spans(needle: tuple[str, ...]) -> list[tuple[int, int]]:
            return [(i, i + len(needle))
                    for i in range(len(words) - len(needle) + 1)
                    if needle and words[i:i + len(needle)] == needle]

        entity_spans = spans(entity_words)
        value_spans = spans(qualifier_value_words)
        if len(entity_spans) != 1 or len(value_spans) != 1:
            raise ValueError("bound entity and qualifier value must each occur once")
        entity_start, entity_end = entity_spans[0]
        value_start, value_end = value_spans[0]
        if entity_start < value_end and entity_end > value_start:
            raise ValueError("entity and qualifier question spans may not overlap")
        entity_first = entity_start < value_start
        if entity_first:
            prefix, middle, suffix = (words[:entity_start],
                                      words[entity_end:value_start],
                                      words[value_end:])
        else:
            prefix, middle, suffix = (words[:value_start],
                                      words[value_end:entity_start],
                                      words[entity_end:])
        qualifier_name = _tokens(normalized[0][0])
        key = (_tokens(relation), answer_field, qualifier_name, entity_first,
               prefix, middle, suffix)
        examples = self._qualified_question_examples.setdefault(key, {})
        pair = (entity_words, qualifier_value_words)
        answers = examples.setdefault(pair, set())
        answers.add(answer)
        entities = {entity for entity, _value in examples}
        values = {value for _entity, value in examples}
        return len(examples) >= 2 and len(entities) >= 2 and len(values) >= 2

    def _teach_multi_qualified_question(
            self, question: str, *, relation: str, answer_field: str,
            bound_entity: str, answer: str,
            normalized: tuple[tuple[str, str], ...]) -> bool:
        """Learn a grounded question frame with two or more context slots."""
        question = _display(question, "question")
        relation = _display(relation, "relation")
        bound_entity = _display(bound_entity, "bound_entity")
        answer = _display(answer, "answer")
        bound_field = "object" if answer_field == "subject" else "subject"
        supported = self._find_fact(
            relation, bound_field, bound_entity, answer, normalized)
        if not supported:
            subject, obj = ((answer, bound_entity) if answer_field == "subject"
                            else (bound_entity, answer))
            inferred = self.infer_relation(
                subject, relation, obj, qualifiers=dict(normalized))
            supported = (inferred.status == "answered" and inferred.complete
                         and any(_is_derived_proof(proof)
                                 for proof in inferred.proofs))
        if not supported:
            raise ValueError(
                "qualified question example requires a matching fact or verified rule proof")

        words = _tokens(question)
        slots: list[tuple[tuple[str, ...], tuple[int, int]]] = []
        for name, value in (("\x00entity", bound_entity),) + tuple(
                ("\x00q" + str(index), value)
                for index, (_qualifier, value) in enumerate(normalized)):
            needle = _tokens(value)
            spans = [(i, i + len(needle)) for i in range(len(words) - len(needle) + 1)
                     if needle and words[i:i + len(needle)] == needle]
            if len(spans) != 1:
                label = "bound entity" if name == "\x00entity" else "qualifier value"
                raise ValueError(f"{label} must occur exactly once in the question")
            slots.append(((name,), spans[0]))
        for index, (_name, (start, end)) in enumerate(slots):
            if any(start < other_end and end > other_start
                   for _other_name, (other_start, other_end) in slots[index + 1:]):
                raise ValueError("entity and qualifier spans may not overlap")

        template = list(words)
        values_by_slot: list[tuple[str, ...]] = [()] * (len(normalized) + 1)
        ordered_slots = sorted(slots, key=lambda item: item[1][0])
        for marker, (start, end) in reversed(ordered_slots):
            if marker[0] == "\x00entity":
                values_by_slot[0] = _tokens(bound_entity)
            else:
                values_by_slot[int(marker[0][2:]) + 1] = _tokens(
                    normalized[int(marker[0][2:])][1])
            template[start:end] = [marker[0]]
        template_tokens = tuple(template)
        names = tuple(_tokens(name) for name, _value in normalized)
        key = (_tokens(relation), answer_field, names, template_tokens)
        pair = (values_by_slot[0], tuple(values_by_slot[1:]))
        examples = self._multi_qualified_question_examples.setdefault(key, {})
        examples.setdefault(pair, set()).add(answer)
        entities = {entity for entity, _values in examples}
        distinct_values = [
            {values[index] for _entity, values in examples}
            for index in range(len(normalized))
        ]
        return (len(examples) >= 2 and len(entities) >= 2
                and all(len(values) >= 2 for values in distinct_values))

    def teach_polar_question(self, question: str, *, subject: str,
                             relation: str, obj: str, answer: bool,
                             qualifiers: Mapping[str, str] | None = None) -> bool:
        """Ground a yes/no question frame to explicit positive/negative facts."""
        if type(answer) is not bool:
            raise ValueError("answer must be a bool")
        question = _display(question, "question")
        subject = _display(subject, "subject")
        relation = _display(relation, "relation")
        obj = _display(obj, "object")
        subject_entity = self._canonicalize_entity(subject)
        object_entity = self._canonicalize_entity(obj)
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        key_fact = self._fact_key(subject_entity, relation, object_entity,
                                  normalized_qualifiers)
        positive = self._facts.get(key_fact)
        negative = self._negative_facts.get(key_fact)
        inferred = self.infer_relation(
            subject_entity, relation, object_entity,
            qualifiers=dict(normalized_qualifiers))
        if answer:
            if positive is None and not (inferred and inferred.status == "answered"):
                raise ValueError("yes example requires a matching fact or verified rule proof")
            if negative is not None:
                raise ValueError("conflicting positive and negative evidence cannot teach a truth label")
        else:
            if negative is None:
                raise ValueError("no example requires matching explicit negative fact evidence")
            if positive is not None or (inferred and inferred.status in {"answered", "ambiguous"}):
                raise ValueError("conflicting positive and negative evidence cannot teach a truth label")

        if normalized_qualifiers:
            qualified = self._teach_qualified_polar_question(
                question, subject=subject_entity, relation=relation,
                obj=object_entity, subject_surface=subject,
                object_surface=obj, answer=answer,
                qualifiers=normalized_qualifiers)
            if qualified is not None:
                return qualified

        words = _tokens(question)
        subject_words, object_words = _tokens(subject), _tokens(obj)

        def find_spans(needle: tuple[str, ...]) -> list[tuple[int, int]]:
            return [(i, i + len(needle))
                    for i in range(len(words) - len(needle) + 1)
                    if words[i:i + len(needle)] == needle]

        subject_spans, object_spans = find_spans(subject_words), find_spans(object_words)
        if len(subject_spans) != 1 or len(object_spans) != 1:
            raise ValueError("subject and object must each occur once in the question")
        s_span, o_span = subject_spans[0], object_spans[0]
        if s_span[0] < o_span[1] and s_span[1] > o_span[0]:
            raise ValueError("subject and object question spans may not overlap")
        replacements = [(s_span[0], s_span[1], "<subject>"),
                        (o_span[0], o_span[1], "<object>")]
        template: list[str] = []
        cursor = 0
        for start, end, marker in sorted(replacements):
            template.extend(words[cursor:start])
            template.append(marker)
            cursor = end
        template.extend(words[cursor:])
        key = (tuple(template), _tokens(relation))
        pair = (_tokens(subject_entity), _tokens(object_entity))
        examples = self._polar_question_examples.setdefault(key, {})
        if pair in examples and examples[pair] != answer:
            raise ValueError("the same question example has conflicting truth labels")
        examples[pair] = answer
        return self._polar_frame_is_licensed(key, examples)

    def _teach_qualified_polar_question(
            self, question: str, *, subject: str, relation: str, obj: str,
            subject_surface: str, object_surface: str, answer: bool,
            qualifiers: tuple[tuple[str, str], ...]) -> bool | None:
        """Learn a polar question whose wording exposes qualifier values."""
        words = _tokens(question)
        spans: list[tuple[str, tuple[int, int]]] = []
        values = (("\x00subject", subject_surface),
                  ("\x00object", object_surface)) + tuple(
            ("\x00q" + str(index), value)
            for index, (_name, value) in enumerate(qualifiers))
        for marker, value in values:
            needle = _tokens(value)
            found = [(i, i + len(needle))
                     for i in range(len(words) - len(needle) + 1)
                     if needle and words[i:i + len(needle)] == needle]
            if len(found) != 1:
                if marker.startswith("\x00q"):
                    # Preserve the explicit-context-only API: when context is
                    # not expressed in the wording, store the legacy frame.
                    return None
                raise ValueError("entities and qualifier values must each occur once in the question")
            spans.append((marker, found[0]))
        for index, (_marker, (start, end)) in enumerate(spans):
            if any(start < other_end and end > other_start
                   for _other, (other_start, other_end) in spans[index + 1:]):
                raise ValueError("entity and qualifier question spans may not overlap")

        template = list(words)
        for marker, (start, end) in reversed(
                sorted(spans, key=lambda item: item[1][0])):
            template[start:end] = [marker]
        relation_tokens = _tokens(relation)
        qualifier_names = tuple(_tokens(name) for name, _value in qualifiers)
        key = (relation_tokens, qualifier_names, tuple(template))
        pair = (_tokens(subject), _tokens(obj),
                tuple(_tokens(value) for _name, value in qualifiers))
        examples = self._qualified_polar_question_examples.setdefault(key, {})
        existing = examples.get(pair)
        if existing is not None and existing != answer:
            raise ValueError("the same qualified question example has conflicting truth labels")
        examples[pair] = answer
        subjects = {item[0] for item in examples}
        objects = {item[1] for item in examples}
        varying_values = [
            {item[2][index] for item in examples}
            for index in range(len(qualifier_names))
        ]
        return (len(examples) >= 2 and len(subjects) >= 2
                and len(objects) >= 2
                and all(len(values) >= 2 for values in varying_values))

    def _polar_frame_is_licensed(
            self, key: tuple[tuple[str, ...], tuple[str, ...]],
            examples: Mapping[tuple[tuple[str, ...], tuple[str, ...]], bool]
            ) -> bool:
        """Check exact-frame evidence or transfer from a licensed relation frame."""
        subjects = {subject for subject, _object in examples}
        objects = {obj for _subject, obj in examples}
        if len(examples) >= 2 and len(subjects) >= 2 and len(objects) >= 2:
            return True
        if len(examples) != 1:
            return False
        relation = key[1]
        return any(
            other_relation == relation
            and len(other_examples) >= 2
            and len({subject for subject, _object in other_examples}) >= 2
            and len({obj for _subject, obj in other_examples}) >= 2
            for (other_template, other_relation), other_examples
            in self._polar_question_examples.items()
            if (other_template, other_relation) != key
        )

    def _ask_qualified_polar_question(
            self, words: tuple[str, ...],
            explicit: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Answer a learned contextual yes/no frame using scoped evidence."""
        if not self._qualified_polar_question_examples:
            return None
        known_entities: dict[tuple[str, ...], str] = {}
        for fact in list(self._facts.values()) + list(self._negative_facts.values()):
            known_entities[_tokens(fact.subject)] = fact.subject
            known_entities[_tokens(fact.object)] = fact.object
        for alias, record in self._entity_alias_records().items():
            known_entities[alias] = record["entity"]

        matches: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...],
                            tuple[tuple[str, ...], ...], str]] = []
        ambiguous_templates: set[str] = set()
        recognized_templates: set[str] = set()
        for (relation, qualifier_names, pattern), examples in \
                self._qualified_polar_question_examples.items():
            subjects = {item[0] for item in examples}
            objects = {item[1] for item in examples}
            if (len(examples) < 2 or len(subjects) < 2 or len(objects) < 2
                    or any(len({item[2][index] for item in examples}) < 2
                           for index in range(len(qualifier_names)))):
                continue
            template_text = " ".join(
                "{subject}" if token == "\x00subject" else
                "{object}" if token == "\x00object" else
                "{" + " ".join(qualifier_names[int(token[2:])]) + "}"
                if token.startswith("\x00q") else token for token in pattern)
            parses: list[dict[str, tuple[str, ...]]] = []
            steps = 0
            exhausted = False

            def match(pattern_index: int, word_index: int,
                      bindings: dict[str, tuple[str, ...]]) -> None:
                nonlocal steps, exhausted
                if len(parses) >= 2:
                    return
                steps += 1
                if steps > 10_000:
                    exhausted = True
                    return
                if pattern_index == len(pattern):
                    if word_index == len(words):
                        parses.append(dict(bindings))
                    return
                token = pattern[pattern_index]
                if token.startswith("\x00"):
                    if token in {"\x00subject", "\x00object"}:
                        for entity_tokens in sorted(
                                known_entities, key=lambda item: (-len(item), item)):
                            end = word_index + len(entity_tokens)
                            if entity_tokens and words[word_index:end] == entity_tokens:
                                bindings[token] = entity_tokens
                                match(pattern_index + 1, end, bindings)
                                bindings.pop(token, None)
                    else:
                        for end in range(word_index + 1, len(words) + 1):
                            bindings[token] = words[word_index:end]
                            match(pattern_index + 1, end, bindings)
                            bindings.pop(token, None)
                    return
                if word_index < len(words) and words[word_index] == token:
                    match(pattern_index + 1, word_index + 1, bindings)

            match(0, 0, {})
            if not parses:
                if exhausted:
                    ambiguous_templates.add(template_text)
                continue
            if len(parses) != 1 or exhausted:
                ambiguous_templates.add(template_text)
                continue
            recognized_templates.add(template_text)
            bindings = parses[0]
            context = {
                " ".join(name): " ".join(bindings["\x00q" + str(index)])
                for index, name in enumerate(qualifier_names)
            }
            invalid = False
            for name, value in explicit:
                existing = next((key for key in context
                                 if _tokens(key) == _tokens(name)), None)
                if existing is not None:
                    if _tokens(context[existing]) != _tokens(value):
                        invalid = True
                        break
                else:
                    context[name] = value
            if invalid:
                continue
            subject = _tokens(self._canonicalize_entity(
                " ".join(bindings["\x00subject"])))
            obj = _tokens(self._canonicalize_entity(
                " ".join(bindings["\x00object"])))
            matches.append((subject, relation, obj,
                            self._normalize_qualifiers(context), template_text))

        if ambiguous_templates:
            return QuestionResult(
                "unknown", matched_templates=sorted(ambiguous_templates),
                request="The contextual yes/no frame has an ambiguous or over-budget variable-span parse.")
        if not matches:
            if recognized_templates:
                return QuestionResult(
                    "unknown", matched_templates=sorted(recognized_templates),
                    request="Explicit context conflicts with the learned question wording.")
            return None
        if len(matches) > 1:
            return QuestionResult(
                "ambiguous", matched_templates=sorted({m[4] for m in matches}),
                request="The contextual yes/no wording matches multiple learned frames.")
        subject, relation, obj, requested, template = matches[0]
        key = (subject, relation, obj)
        positive = next((fact for fact in self._facts.values()
                         if self._fact_key(fact.subject, fact.relation, fact.object) == key
                         and self._has_qualifiers(fact, requested)), None)
        negative = next((fact for fact in self._negative_facts.values()
                         if self._fact_key(fact.subject, fact.relation, fact.object) == key
                         and self._has_qualifiers(fact, requested)), None)
        inferred = self.infer_relation(
            " ".join(subject), " ".join(relation), " ".join(obj),
            qualifiers=dict(requested))
        proofs = (list(inferred.proofs)
                  if inferred.status in {"answered", "ambiguous"} and positive is None
                  else [])
        evidence: list[dict[str, Any]] = []
        if positive is not None:
            item = asdict(positive)
            if negative is not None:
                item["contradictory_sources"] = list(negative.sources)
            evidence.append(item)
        elif negative is not None:
            evidence.append(asdict(negative))
        if positive is not None and negative is not None:
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=[template],
                inference_proofs=proofs,
                request="Positive and negative sources conflict; inspect the cited evidence.",
                complete=inferred.complete, expansions=inferred.expansions)
        if negative is not None and inferred.status in {"answered", "ambiguous"}:
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=[template],
                inference_proofs=proofs,
                request="Negative evidence conflicts with a verified rule proof.",
                complete=inferred.complete, expansions=inferred.expansions)
        if positive is not None or inferred.status == "answered":
            return QuestionResult(
                "answered", answer="Yes", candidates=["Yes"], evidence=evidence,
                matched_templates=[template], truth=True,
                inference_proofs=proofs, complete=inferred.complete,
                expansions=inferred.expansions)
        if inferred.status == "ambiguous":
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=[template],
                inference_proofs=proofs,
                request="The contextual rule proof has conflicting support.",
                complete=inferred.complete, expansions=inferred.expansions)
        if negative is not None:
            return QuestionResult(
                "answered", answer="No", candidates=["No"], evidence=evidence,
                matched_templates=[template], truth=False)
        if inferred.failure_kind == "closed_world_absence":
            schema = self._relation_type_fact(
                " ".join(relation), "closed-world", requested)
            return QuestionResult(
                "answered", answer="No", candidates=["No"],
                evidence=[asdict(schema)] if schema is not None else evidence,
                matched_templates=[template], truth=False,
                language_evidence=[{"kind": "closed_world_absence",
                                    "relation": " ".join(relation)}])
        return QuestionResult(
            "unknown", matched_templates=[template],
            request="The contextual question frame is learned, but this proposition has no explicit truth evidence.")

    def _ask_source_licensed_object_wh_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Answer ``What did/does SUBJECT VERB?`` from grounded predicates.

        A predicate can be licensed by a varied sentence frame or directly by
        an accepted fact's single-token relation. The latter uses only bounded
        regular verb morphology; relation meaning and answers still come from
        the fact store.
        """
        if (len(words) < 4 or words[0] != "what"
                or words[1] not in {"did", "do", "does"}):
            return None
        auxiliary = words[1]
        observed = self._observed_predicates_by_relation()
        relations: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        for key, examples in self._fact_pattern_examples.items():
            if not self._fact_pattern_is_licensed(key, examples):
                continue
            relation = key[1]
            forms = self._predicate_forms_for_relation(
                relation, observed.get(relation, set()))[0]
            if auxiliary in {"do", "does"}:
                bare_forms = {relation}
                for form in forms:
                    if len(form) != len(relation) or not form:
                        continue
                    surface = form[0]
                    if (form in observed.get(relation, set())
                            and all(_analyze_predicate_spelling(base, word)
                                    is None
                                    for base, word in zip(relation, form))):
                        bare_forms.add(form)
                    bases = set()
                    if len(surface) >= 4 and surface.endswith("ies"):
                        bases.add(surface[:-3] + "y")
                    if len(surface) >= 4 and surface.endswith("es"):
                        bases.add(surface[:-2])
                    if len(surface) >= 3 and surface.endswith("s"):
                        bases.add(surface[:-1])
                    for base in bases:
                        alignment = _analyze_predicate_spelling(base, surface)
                        if alignment is not None and alignment[2] in {"s", "es"}:
                            bare_forms.add((base, *form[1:]))
                forms = bare_forms
            elif auxiliary == "did":
                # An accepted source frame may license a different lexical
                # surface for the same canonical relation, for example the
                # teacher-reviewed `investigated` phrase under `study`. A
                # do-support question uses that phrase's bare spelling, so
                # derive only regular past-to-bare alternations from those
                # already licensed observations.
                bare_forms = {relation}
                for form in forms:
                    if len(form) != 1:
                        continue
                    surface = form[0]
                    bases = set()
                    if surface.endswith("ied") and len(surface) > 3:
                        bases.add(surface[:-3] + "y")
                    elif surface.endswith("ed") and len(surface) > 2:
                        bases.add(surface[:-2])
                        bases.add(surface[:-2] + "e")
                        if (len(surface) > 4
                                and surface[-3] == surface[-4]
                                and surface[-3].isalpha()):
                            bases.add(surface[:-3])
                    for base in bases:
                        if _analyze_predicate_spelling(base, surface) is not None:
                            bare_forms.add((base,))
                forms = bare_forms
            relations.setdefault(relation, set()).update(forms)

        # A stored relation is already explicit language evidence. Let the
        # ordinary do-support construction query it without requiring a
        # separately taught question frame. Multiword relations remain on the
        # learned-frame path because their syntax cannot be safely guessed.
        stored_relations: set[tuple[str, ...]] = set()
        for store in (self._facts, self._negative_facts):
            if hasattr(store, "relation_keys"):
                stored_relations.update(store.relation_keys())
            else:
                stored_relations.update(tuple(key[1]) for key in store)
        for relation in stored_relations:
            if len(relation) != 1:
                continue
            surface = relation[0]
            bare_forms = {surface}
            if surface.endswith("ied") and len(surface) > 3:
                bare_forms.add(surface[:-3] + "y")
            if surface.endswith("ed") and len(surface) > 2:
                bare_forms.add(surface[:-2])
                bare_forms.add(surface[:-2] + "e")
                # Regular past forms double a final consonant ("stopped" ->
                # "stop"); retain this spelling path alongside the plain
                # suffix candidates so only an exact query form can select it.
                if (len(surface) > 4 and surface[-3] == surface[-4]
                        and surface[-3].isalpha()):
                    bare_forms.add(surface[:-3])
            if surface.endswith("ies") and len(surface) > 3:
                bare_forms.add(surface[:-3] + "y")
            if surface.endswith("es") and len(surface) > 2:
                bare_forms.add(surface[:-2])
            if surface.endswith("s") and len(surface) > 1:
                bare_forms.add(surface[:-1])
            relations.setdefault(relation, set()).update(
                (form,) for form in bare_forms if form)

        parses: dict[tuple[Any, ...], dict[str, Any]] = {}
        for predicate_start in range(3, len(words)):
            subject_tokens = words[2:predicate_start]
            if not subject_tokens:
                continue
            for relation, forms in relations.items():
                for predicate in forms:
                    if (predicate and words[predicate_start:] == predicate):
                        signature = (auxiliary, subject_tokens, relation, predicate)
                        parses[signature] = {
                            "auxiliary": auxiliary,
                            "subject": self._canonicalize_query_entity(
                                " ".join(subject_tokens)),
                            "relation": relation,
                            "predicate": predicate,
                        }
        if not parses:
            return None
        templates = sorted({
            f"what {frame['auxiliary']} <subject> "
            + " ".join(frame["predicate"])
            for frame in parses.values()
        })
        if len(parses) != 1:
            return QuestionResult(
                "ambiguous", matched_templates=templates,
                request=("The grounded relation wording has multiple parses; "
                         "please restate the question with a taught frame."))
        frame = next(iter(parses.values()))

        def lookup(store: Any) -> list[FactEvidence]:
            if isinstance(store, SQLiteFactMap):
                rows = store.lookup(frame["relation"],
                                    _tokens(frame["subject"]), "subject")
            elif store is self._facts:
                subject_key = _tokens(frame["subject"])
                fact_keys = self._facts_by_relation_subject.get(
                    (frame["relation"], subject_key), ())
                rows = (store[key] for key in fact_keys)
            elif not store:
                rows = ()
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.subject) == _tokens(frame["subject"])
                        and _tokens(fact.relation) == frame["relation"])
            return [fact for fact in rows
                    if self._qualifiers_equal(fact.qualifiers, qualifiers)]

        positive = lookup(self._facts)
        negative = lookup(self._negative_facts)
        by_object: dict[tuple[str, ...], FactEvidence] = {}
        for fact in positive:
            by_object.setdefault(_tokens(fact.object), fact)
        negative_objects = {_tokens(fact.object) for fact in negative}
        conflicts = set(by_object) & negative_objects
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        language_evidence = [{
            "kind": "source_licensed_object_wh_question",
            "relation": " ".join(frame["relation"]),
            "predicate": " ".join(frame["predicate"]),
            "grammar": (f"what {frame['auxiliary']} + subject + "
                        "licensed predicate"),
        }]
        template = templates[0]
        if conflicts:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    {by_object[key].object for key in conflicts}),
                evidence=evidence, matched_templates=[template],
                language_evidence=language_evidence,
                request=("Positive and negative sources conflict for an "
                         "object matching this question."))
        if len(by_object) > 1:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    (fact.object for fact in by_object.values()),
                    key=str.casefold), evidence=evidence,
                matched_templates=[template],
                language_evidence=language_evidence,
                request="Multiple source-backed objects match this question.")
        if by_object:
            fact = next(iter(by_object.values()))
            return QuestionResult(
                "answered", answer=fact.object, candidates=[fact.object],
                evidence=[asdict(fact)], matched_templates=[template],
                language_evidence=language_evidence)
        return QuestionResult(
            "unknown", evidence=evidence or None,
            matched_templates=[template], language_evidence=language_evidence,
            request=(f"I understand the '{' '.join(relation)}' question frame, "
                     f"but have no accepted fact for '{frame['subject']}'. "
                     "Tell me the fact or point me to a source."),
            reason_code="missing_subject_relation_fact")

    def _lookup_relation_object(
            self, store: Any, relation: tuple[str, ...],
            obj: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> list[FactEvidence]:
        if hasattr(store, "lookup"):
            rows = store.lookup(relation, obj, "object")
        else:
            rows = (fact for fact in store.values()
                    if _tokens(fact.relation) == relation
                    and _tokens(fact.object) == obj)
        return [fact for fact in rows
                if self._qualifiers_equal(fact.qualifiers, qualifiers)]

    def _ask_stored_relation_subject_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Resolve ``Who PREDICATE OBJECT?`` from grounded relation facts.

        Predicate wording must be the stored relation itself or a surface form
        licensed by the relation's sentence examples. The object must match a
        stored entity exactly; conflicting or multiple subjects remain
        ambiguous instead of being guessed.
        """
        if len(words) < 3 or words[0] != "who":
            return None
        relations = {
            tuple(relation)
            for store in (self._facts, self._negative_facts)
            for relation in (store.relation_keys() if hasattr(
                store, "relation_keys") else
                (key[1] for key in store))
            if len(relation) == 1
        }
        observed = self._observed_predicates_by_relation()
        parses: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        for relation in relations:
            predicate_forms = self._predicate_forms_for_relation(
                relation, observed.get(relation, set()))[0]
            predicate_forms.add(relation)
            for predicate in predicate_forms:
                if not predicate or words[1:1 + len(predicate)] != predicate:
                    continue
                object_words = words[1 + len(predicate):]
                if not object_words:
                    continue
                object_options = [object_words]
                if object_words[0] in {"a", "an", "the"}:
                    object_options.append(object_words[1:])
                for object_option in object_options:
                    if not object_option:
                        continue
                    obj = _tokens(self._canonicalize_entity(
                        " ".join(object_option)))
                    positive = self._lookup_relation_object(
                        self._facts, relation, obj, qualifiers)
                    negative = self._lookup_relation_object(
                        self._negative_facts, relation, obj, qualifiers)
                    if positive or negative:
                        signature = (relation, obj, predicate)
                        parses[signature] = (
                            relation, obj, predicate, positive, negative)
        if not parses:
            return None
        if len(parses) != 1:
            return QuestionResult(
                "ambiguous", matched_templates=["Who <predicate> <object>"],
                request=("The stored predicates allow multiple parses; please "
                         "restate the question with a taught frame."))
        relation, obj, predicate, positive, negative = next(
            iter(parses.values()))
        positive_subjects = {_tokens(fact.subject) for fact in positive}
        negative_subjects = {_tokens(fact.subject) for fact in negative}
        conflict_subjects = positive_subjects & negative_subjects
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        template = "Who " + " ".join(predicate) + " <object>"
        language_evidence = [{
            "kind": "stored_relation_subject_question",
            "relation": " ".join(relation),
            "predicate": " ".join(predicate),
            "grammar": "who + grounded predicate + exact stored object",
        }]
        if conflict_subjects:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    {fact.subject for fact in (*positive, *negative)
                     if _tokens(fact.subject) in conflict_subjects},
                    key=str.casefold), evidence=evidence,
                matched_templates=[template], language_evidence=language_evidence,
                request="Positive and negative sources conflict for this relation.")
        if len(positive_subjects) > 1:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    (fact.subject for fact in positive), key=str.casefold),
                evidence=evidence, matched_templates=[template],
                language_evidence=language_evidence,
                request="Multiple stored subjects match this relation and object.")
        if len(positive_subjects) == 1:
            fact = positive[0]
            return QuestionResult(
                "answered", answer=fact.subject, candidates=[fact.subject],
                evidence=[asdict(item) for item in positive],
                matched_templates=[template],
                language_evidence=language_evidence)
        return QuestionResult(
            "unknown", evidence=evidence or None, matched_templates=[template],
            language_evidence=language_evidence,
            request="No positive stored fact supports this relation and object.")

    def _ask_source_licensed_location_wh_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Answer a bounded ``Where does SUBJECT VERB?`` from licensed
        locative fact frames and regular predicate spelling evidence."""
        if (len(words) < 4 or words[0] != "where"
                or words[1] not in {"do", "does", "did"}):
            return None
        subject = self._canonicalize_query_entity(" ".join(words[2:-1]))
        base_verb = words[-1]
        if not subject or not base_verb:
            return None
        relations: dict[tuple[str, ...], dict[str, Any]] = {}
        observed = self._observed_predicates_by_relation()
        for key, examples in self._fact_pattern_examples.items():
            if not self._fact_pattern_is_licensed(key, examples):
                continue
            relation = key[1]
            if len(relation) < 2 or relation[-1] not in {"at", "in", "near"}:
                continue
            forms = self._predicate_forms_for_relation(
                relation, observed.get(relation, set()))[0]
            matched = []
            for form in forms:
                if len(form) != len(relation) or form[-1] != relation[-1]:
                    continue
                surface_verb = form[0]
                if (surface_verb == base_verb
                        or _analyze_predicate_spelling(
                            base_verb, surface_verb) is not None):
                    matched.append(form)
            if matched:
                relations[relation] = {
                    "predicate": sorted(matched)[0],
                    "template": f"where {words[1]} <subject> {base_verb}",
                }
        if not relations:
            return None
        templates = sorted({record["template"]
                            for record in relations.values()})
        if len(relations) != 1:
            return QuestionResult(
                "ambiguous", matched_templates=templates,
                request=("Several accepted locative frames match this verb; "
                         "teach a contrastive question example."))
        relation, frame = next(iter(relations.items()))

        def lookup(store: Any) -> list[FactEvidence]:
            if isinstance(store, SQLiteFactMap):
                rows = store.lookup(relation, _tokens(subject), "subject")
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.relation) == relation
                        and _tokens(fact.subject) == _tokens(subject))
            return [fact for fact in rows
                    if self._qualifiers_equal(fact.qualifiers, qualifiers)]

        positive = lookup(self._facts)
        negative = lookup(self._negative_facts)
        positives_by_place = {_tokens(fact.object): fact for fact in positive}
        negatives_by_place = {_tokens(fact.object): fact for fact in negative}
        conflict = set(positives_by_place) & set(negatives_by_place)
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        language_evidence = [{
            "kind": "source_licensed_location_wh_question",
            "relation": " ".join(relation),
            "predicate": " ".join(frame["predicate"]),
            "grammar": (f"where {words[1]} + subject + regular "
                        "predicate form"),
        }]
        template = frame["template"]
        if conflict:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    {positives_by_place[key].object for key in conflict}),
                evidence=evidence, matched_templates=[template],
                language_evidence=language_evidence,
                request="Positive and negative location facts conflict.")
        if len(positives_by_place) > 1:
            return QuestionResult(
                "ambiguous", candidates=sorted(
                    (fact.object for fact in positives_by_place.values()),
                    key=str.casefold), evidence=evidence,
                matched_templates=[template],
                language_evidence=language_evidence,
                request="Multiple accepted locations match this question.")
        if positives_by_place:
            fact = next(iter(positives_by_place.values()))
            return QuestionResult(
                "answered", answer=fact.object, candidates=[fact.object],
                evidence=[asdict(fact)], matched_templates=[template],
                language_evidence=language_evidence)
        return QuestionResult(
            "unknown", evidence=evidence or None, matched_templates=[template],
            language_evidence=language_evidence,
            request=("This verb matches an accepted locative frame, but no "
                     "positive location is stored for this subject."))

    def _ask_zero_frame_polar_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Answer bounded do-support and copular questions from exact relations.

        A stored canonical relation can ground this narrow surface syntax even
        without a separately taught sentence frame. Observed predicate forms
        still require a licensed source alignment. This route does not infer
        truth from absence: only explicit negative evidence yields ``No``.
        """
        if len(words) < 4:
            return None
        mode = (words[0] if words[0] in {"did", "do", "does"} else
                "copular" if words[0] in {"is", "are", "was", "were"}
                else None)
        if mode is None:
            return None
        relations: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        observed = self._observed_predicates_by_relation()
        stored_relations = {
            tuple(relation)
            for store in (self._facts, self._negative_facts)
            for relation in (store.relation_keys() if hasattr(
                store, "relation_keys") else
                (key[1] for key in store))
        }
        closed_world_facts = (
            self._facts.lookup(
                _tokens("has relation type"), _tokens("closed-world"), "object")
            if isinstance(self._facts, SQLiteFactMap)
            else self._facts.values())
        stored_relations.update(
            _tokens(fact.subject) for fact in closed_world_facts
            if (_tokens(fact.relation) == _tokens("has relation type")
                and _tokens(fact.object) == _tokens("closed-world")
                and self._qualifiers_equal(fact.qualifiers, qualifiers)))
        licensed_relations = {
            key[1] for key, examples in self._fact_pattern_examples.items()
            if self._fact_pattern_is_licensed(key, examples)
        }
        for relation in stored_relations:
            forms = self._predicate_forms_for_relation(
                relation, observed.get(relation, set()))[0]
            # Canonical relation words are explicit data. Surface variants
            # remain gated on a licensed sentence pattern or alignment.
            forms.add(relation)
            if relation not in licensed_relations:
                forms.intersection_update({relation})
            if mode in {"do", "does"}:
                # With do-support, the lexical verb is bare. Retain the
                # canonical form and invert only regular third-person endings
                # from a source-licensed predicate form.
                bare_forms = {relation}
                for form in forms:
                    if not form:
                        continue
                    surface = form[0]
                    if (len(form) == len(relation)
                            and form in observed.get(relation, set())
                            and all(_analyze_predicate_spelling(base, word)
                                    is None
                                    for base, word in zip(relation, form))):
                        # A source-aligned form with no regular spelling
                        # alignment is a reviewed lexical variant.
                        bare_forms.add(form)
                    bases = set()
                    if len(surface) >= 4 and surface.endswith("ies"):
                        bases.add(surface[:-3] + "y")
                    if len(surface) >= 4 and surface.endswith("es"):
                        bases.add(surface[:-2])
                    if len(surface) >= 3 and surface.endswith("s"):
                        bases.add(surface[:-1])
                    for base in bases:
                        alignment = _analyze_predicate_spelling(base, surface)
                        if alignment is not None and alignment[2] in {"s", "es"}:
                            bare_forms.add((base, *form[1:]))
                forms = bare_forms
            relations.setdefault(relation, set()).update(forms)

        parses: dict[tuple[Any, ...], dict[str, Any]] = {}
        for subject_end in range(2, len(words) - 1):
            if (mode == "copular"
                    and words[subject_end - 1] in {"a", "an", "the"}):
                continue
            subject_tokens = words[1:subject_end]
            predicate_start = subject_end
            if mode == "copular" and words[predicate_start] in {"a", "an", "the"}:
                predicate_start += 1
            if predicate_start >= len(words) - 1:
                continue
            for relation, forms in relations.items():
                for predicate in forms:
                    predicate_end = predicate_start + len(predicate)
                    if (not predicate or predicate_end >= len(words)
                            or words[predicate_start:predicate_end] != predicate):
                        continue
                    object_tokens = words[predicate_end:]
                    if not object_tokens:
                        continue
                    signature = (mode, subject_tokens, relation, predicate,
                                 object_tokens)
                    parses[signature] = {
                        "subject": self._canonicalize_query_entity(
                            " ".join(subject_tokens)),
                        "relation": relation,
                        "predicate": predicate,
                        "object": " ".join(object_tokens),
                        "mode": mode,
                    }
        if not parses:
            return None
        template_names = sorted({
            frame["mode"] + " <subject> "
            + " ".join(frame["predicate"]) + " <object>"
            for frame in parses.values()
        })
        if len(parses) != 1:
            return QuestionResult(
                "ambiguous", matched_templates=template_names,
                request=("The source-licensed predicate has multiple parses; "
                         "please restate the question with a taught frame."))
        frame = next(iter(parses.values()))
        language_evidence = [{
            "kind": "stored_relation_polar_question",
            "relation": " ".join(frame["relation"]),
            "predicate": " ".join(frame["predicate"]),
            "grammar": (f"{frame['mode']} + subject + grounded predicate + object"
                        if frame["mode"] in {"did", "do", "does"} else
                        "copula + subject + optional article + grounded predicate + object"),
        }]

        def lookup(store: Any) -> list[FactEvidence]:
            if isinstance(store, SQLiteFactMap):
                rows = store.lookup(frame["relation"],
                                    _tokens(frame["subject"]), "subject")
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.subject) == _tokens(frame["subject"])
                        and _tokens(fact.relation) == frame["relation"])
            return [fact for fact in rows
                    if _tokens(fact.object) == _tokens(frame["object"])
                    and self._qualifiers_equal(fact.qualifiers, qualifiers)]

        positive = lookup(self._facts)
        negative = lookup(self._negative_facts)
        matched_template = template_names[0]
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        if positive and negative:
            return QuestionResult(
                "ambiguous", evidence=evidence,
                matched_templates=[matched_template],
                language_evidence=language_evidence,
                request="Positive and negative sources conflict for this proposition.")
        if negative:
            return QuestionResult(
                "answered", answer="No", candidates=["No"], truth=False,
                evidence=evidence, matched_templates=[matched_template],
                language_evidence=language_evidence)
        if positive:
            return QuestionResult(
                "answered", answer="Yes", candidates=["Yes"], truth=True,
                evidence=evidence, matched_templates=[matched_template],
                language_evidence=language_evidence)
        inferred = self.infer_relation(
            frame["subject"], " ".join(frame["relation"]), frame["object"],
            qualifiers=dict(qualifiers))
        if inferred.status == "answered":
            return QuestionResult(
                "answered", answer="Yes", candidates=["Yes"], truth=True,
                inference_proofs=list(inferred.proofs),
                matched_templates=[matched_template],
                language_evidence=language_evidence,
                complete=inferred.complete, expansions=inferred.expansions)
        if inferred.status == "ambiguous":
            return QuestionResult(
                "ambiguous", evidence=evidence or None,
                inference_proofs=list(inferred.proofs),
                matched_templates=[matched_template],
                language_evidence=language_evidence,
                request=inferred.request, complete=inferred.complete,
                expansions=inferred.expansions)
        if inferred.failure_kind == "closed_world_absence":
            schema = self._relation_type_fact(
                " ".join(frame["relation"]), "closed-world", qualifiers)
            return QuestionResult(
                "answered", answer="No", candidates=["No"], truth=False,
                evidence=[asdict(schema)] if schema is not None else evidence,
                matched_templates=[matched_template],
                language_evidence=language_evidence + [{
                    "kind": "closed_world_absence",
                    "relation": " ".join(frame["relation"])}])
        return QuestionResult(
            "unknown", matched_templates=[matched_template],
            language_evidence=language_evidence,
            request=("The question matches a stored relation, but "
                     "there is no explicit positive or negative evidence for "
                     "this proposition."))

    def ask_polar_question(self, question: str, *,
                           qualifiers: Mapping[str, str] | None = None
                           ) -> QuestionResult:
        """Answer from explicit truth evidence or a verified scoped rule proof."""
        requested_qualifiers = self._normalize_qualifiers(qualifiers)
        words = _tokens(_display(question, "question"))
        qualified = self._ask_qualified_polar_question(
            words, requested_qualifiers)
        if qualified is not None:
            return qualified
        class_polar = self._ask_is_a_polar_question(words, requested_qualifiers)
        if class_polar is not None:
            return self._attach_query_alias_evidence(question, class_polar)
        results: list[tuple[bool | None, dict[str, Any] | None, str,
                            tuple[str, ...], list[dict[str, Any]], bool]] = []
        for (template, relation_tokens), examples in self._polar_question_examples.items():
            if not self._polar_frame_is_licensed(
                    (template, relation_tokens), examples):
                continue
            matches = self._match_fact_template(template, words)
            if len(matches) != 1:
                continue
            (subject_words, object_words, *_spans) = matches[0]
            subject_entity = _tokens(self._canonicalize_entity(" ".join(subject_words)))
            object_entity = _tokens(self._canonicalize_entity(" ".join(object_words)))
            positive_facts = [
                fact for fact in self._matching_fact_rows(
                    self._facts, " ".join(subject_entity),
                    " ".join(relation_tokens), " ".join(object_entity))
                if self._has_qualifiers(fact, requested_qualifiers)]
            negative_facts = [
                fact for fact in self._matching_fact_rows(
                    self._negative_facts, " ".join(subject_entity),
                    " ".join(relation_tokens), " ".join(object_entity))
                if self._has_qualifiers(fact, requested_qualifiers)]
            positive = positive_facts[0] if positive_facts else None
            negative = negative_facts[0] if negative_facts else None
            template_text = " ".join(template)
            inferred = self.infer_relation(
                " ".join(subject_entity), " ".join(relation_tokens),
                " ".join(object_entity),
                qualifiers=dict(requested_qualifiers))
            inference_proofs = (list(inferred.proofs)
                                if inferred and inferred.status in {"answered", "ambiguous"}
                                and positive is None else [])
            if positive is not None and negative is not None:
                results.append((None, asdict(positive) | {
                    "contradictory_sources": list(negative.sources)}, template_text,
                    relation_tokens, inference_proofs, True))
            elif negative is not None and inferred and inferred.status in {"answered", "ambiguous"}:
                results.append((None, asdict(negative), template_text,
                                relation_tokens, inference_proofs, True))
            elif positive is not None:
                results.append((True, asdict(positive), template_text,
                                relation_tokens, [], False))
            elif inferred and inferred.status == "answered":
                results.append((True, None, template_text, relation_tokens,
                                inference_proofs, False))
            elif inferred and inferred.status == "ambiguous":
                results.append((None, None, template_text, relation_tokens,
                                inference_proofs, True))
            elif negative is not None:
                results.append((False, asdict(negative), template_text,
                                relation_tokens, [], False))
            elif inferred and inferred.failure_kind == "closed_world_absence":
                schema = self._relation_type_fact(
                    " ".join(relation_tokens), "closed-world",
                    requested_qualifiers)
                results.append((False, asdict(schema) if schema else None,
                                template_text, relation_tokens, [], False))
            else:
                results.append((None, None, template_text, relation_tokens, [], False))
        if not results:
            source_licensed = self._ask_zero_frame_polar_question(
                words, requested_qualifiers)
            return source_licensed or QuestionResult("unknown")
        templates = sorted({template for _, _, template, _, _, _ in results})
        matched_relations = {relation for _, _, _, relation, _, _ in results}
        known_truths = {truth for truth, evidence, _, _, proofs, _ in results
                        if truth is not None and (evidence is not None or proofs)}
        evidence = [item for _, item, _, _, _, _ in results if item is not None]
        inference_proofs = [proof for _, _, _, _, proofs, _ in results for proof in proofs]
        if len(matched_relations) > 1:
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs,
                request="The learned wording maps to multiple relations; clarify the intended meaning.")
        if (len(known_truths) > 1
                or any(ambiguous for *_, ambiguous in results)):
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs,
                request="Positive and negative sources conflict; inspect the cited evidence.")
        if not known_truths:
            return QuestionResult(
                "unknown", matched_templates=templates,
                inference_proofs=inference_proofs,
                request="The question frame is learned, but this proposition has no explicit truth evidence.")
        truth = next(iter(known_truths))
        return QuestionResult("answered", answer="Yes" if truth else "No",
                              candidates=["Yes" if truth else "No"],
                              evidence=evidence, matched_templates=templates,
                              truth=truth, inference_proofs=inference_proofs)

    def _ask_distributive_subject_question(
            self, question: str, *,
            qualifiers: Mapping[str, str] | None = None
            ) -> QuestionResult | None:
        """Evaluate a grounded question once per subject in an explicit pair."""
        each_matches = list(re.finditer(r"\beach\b", question,
                                        flags=re.IGNORECASE))
        if len(each_matches) != 1:
            return None
        token_matches = word_matches(question)
        each_index = next((index for index, match in enumerate(token_matches)
                           if match.start() == each_matches[0].start()), None)
        if each_index is None or each_index < 3:
            return None
        group_spans: list[tuple[int, int, tuple[str, ...]]] = []
        for start_index in range(each_index - 2):
            surface = question[token_matches[start_index].start():
                               token_matches[each_index - 1].end()]
            group = self._resolve_subject_group(surface)
            if group is not None:
                group_spans.append((token_matches[start_index].start(),
                                    each_matches[0].end(), group))
        if not group_spans:
            return None
        group_signatures = {group for _, _, group in group_spans}
        if len(group_signatures) != 1:
            return QuestionResult(
                "unknown",
                request="The 'each' question has multiple entity-pair parses; name the entities separately.")
        group_start, group_end, subjects = min(
            group_spans, key=lambda span: (span[0], -(span[1] - span[0])))
        results: list[tuple[str, QuestionResult]] = []
        for subject in subjects:
            individual_question = " ".join((
                question[:group_start] + subject + question[group_end:]).split())
            results.append((subject, self.ask(
                individual_question, qualifiers=qualifiers)))

        evidence = [item for _, result in results
                    for item in (result.evidence or [])]
        inference_proofs = [proof for _, result in results
                            for proof in (result.inference_proofs or [])]
        proofs = [proof for _, result in results
                  for proof in (result.proofs or [])]
        templates = sorted({template for _, result in results
                            for template in (result.matched_templates or [])})
        language_evidence = {
            json.dumps(item, sort_keys=True, ensure_ascii=False): item
            for _, result in results for item in
            (result.language_evidence or [])}
        if any(result.status == "ambiguous" for _, result in results):
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs, proofs=proofs,
                language_evidence=list(language_evidence.values()),
                request="At least one entity has multiple supported answers; no partial 'each' answer is returned.")
        if any(result.status != "answered" for _, result in results):
            return QuestionResult(
                "unknown", evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs, proofs=proofs,
                language_evidence=list(language_evidence.values()),
                request="Every named subject needs a grounded answer for this 'each' question.")

        if any(result.truth is not None for _, result in results):
            if not all(result.truth is not None for _, result in results):
                return QuestionResult(
                    "unknown", evidence=evidence, matched_templates=templates,
                    inference_proofs=inference_proofs,
                    request="The subject queries produced different answer types.")
            truth = all(result.truth is True for _, result in results)
            answer = "Yes" if truth else "No"
            return QuestionResult(
                "answered", answer=answer, candidates=[answer],
                evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs, proofs=proofs,
                truth=truth,
                language_evidence=list(language_evidence.values()),
                request="The answer is true only when both subject-specific questions are true.")

        if any(result.answer is None for _, result in results):
            return QuestionResult(
                "unknown", evidence=evidence, matched_templates=templates,
                inference_proofs=inference_proofs, proofs=proofs,
                request="Every named subject needs one explicit answer for this 'each' question.")
        answer = "; ".join(
            f"{subject}: {result.answer}" for subject, result in results)
        return QuestionResult(
            "answered", answer=answer, candidates=[answer],
            evidence=evidence, matched_templates=templates,
            inference_proofs=inference_proofs, proofs=proofs,
            language_evidence=list(language_evidence.values()),
            request="Each entity was answered separately from grounded evidence.")

    def _ask_composed_question(
            self, question: str, *,
            qualifiers: Mapping[str, str] | None = None
            ) -> QuestionResult | None:
        """Compose up to three learned clauses with one logical connector.

        Atomic clauses are answered through learned question frames. A unique
        supported reconstruction is required; this method does not infer
        missing clause answers or learn new predicates.
        """
        phrase = question.strip().rstrip("?.!")
        has_or = re.search(r"\bor\b", phrase, flags=re.IGNORECASE) is not None
        explicit_and = re.search(r"\band\b", phrase,
                                 flags=re.IGNORECASE) is not None
        has_and = re.search(r"\band\b|,", phrase, flags=re.IGNORECASE) is not None
        if has_or and has_and:
            return QuestionResult(
                "unknown",
                request="Mixed logical operators need explicit grouping or separate questions.")
        operator = "or" if has_or else "and"
        clauses = (re.split(r"\s+or\s+", phrase, flags=re.IGNORECASE)
                   if operator == "or" else
                   re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", phrase,
                            flags=re.IGNORECASE))
        if len(clauses) < 2 or len(clauses) > 3:
            return None
        if any(len(_tokens(clause)) > 32 for clause in clauses):
            return QuestionResult(
                "unknown",
                request="This composed question exceeds the bounded clause length.")
        question_words = _tokens(question)
        connector_positions = [index for index, word in enumerate(question_words)
                               if word == operator]
        connector_phrases = {
            question_words[start:end]
            for connector in connector_positions
            for start in range(connector + 1)
            for end in range(connector + 1, len(question_words) + 1)
        }
        if any(isinstance(store, SQLiteFactMap)
               and store.contains_any_phrase(connector_phrases)
               for store in (self._facts, self._negative_facts)):
            # Do not reinterpret a known multiword entity or predicate
            # containing the connector as a clause boundary.
            return None
        if not all(isinstance(store, SQLiteFactMap)
                   for store in (self._facts, self._negative_facts)):
            if any(
                    value in connector_phrases
                    for store in (self._facts, self._negative_facts)
                    if not isinstance(store, SQLiteFactMap)
                    for key in store
                    for value in key[:3]):
                return None
        first = clauses[0].strip()
        if not first:
            return None
        prefixes = [first[:match.end()].rstrip() + " "
                    for match in re.finditer(r"\S+", first)
                    if match.end() < len(first)]
        if not prefixes:
            return None
        viable: list[tuple[int, list[QuestionResult]]] = []
        conflicted: list[QuestionResult] = []
        conflict_markers = (
            "positive and negative sources conflict",
            "negative evidence conflicts",
            "conflicts with explicit negative evidence",
            "conflicting support",
        )
        # The first clause is invariant across every candidate reconstruction.
        # Evaluate it once; only the suffix clause changes with the prefix.
        first_result = self.ask(first + "?", qualifiers=qualifiers)
        for prefix in prefixes:
            standalone = [first] + [prefix + clause.strip()
                                    for clause in clauses[1:]]
            results = [first_result] + [
                self.ask(clause + "?", qualifiers=qualifiers)
                for clause in standalone[1:]]
            if any(result.status == "ambiguous" and any(
                    marker in (result.request or "").casefold()
                    for marker in conflict_markers) for result in results):
                conflicted.extend(results)
                continue
            if all(result.status in {"answered", "ambiguous"}
                   and result.candidates is not None for result in results):
                viable.append((len(_tokens(prefix)), results))
        if conflicted and not viable:
            return QuestionResult(
                "ambiguous",
                evidence=[item for result in conflicted
                          for item in (result.evidence or [])],
                matched_templates=sorted({template for result in conflicted
                    for template in (result.matched_templates or [])}),
                inference_proofs=[proof for result in conflicted
                                  for proof in (result.inference_proofs or [])],
                request="A clause conflicts with explicit negative evidence; the composed question is unresolved.")
        if not viable:
            if has_or or explicit_and:
                return QuestionResult(
                    "unknown",
                    request="Every clause in this composed question needs a grounded answer.")
            # A comma can introduce a qualifier-led atomic question
            # ("In 2024, who ...?"). Do not claim a composed parse unless
            # at least one clause reconstruction is independently grounded.
            return None
        if len(viable) > 1:
            # Prefer the shortest grounded shared prefix. Longer prefixes can
            # repeat material from the first predicate ("Did Ada design
            # build ...?") and create false ambiguity.
            viable = [min(viable, key=lambda item: item[0])]
        results = viable[0][1]
        if all(result.status == "answered" and result.truth is not None
               for result in results):
            truth = (any(result.truth is True for result in results)
                     if operator == "or" else
                     all(result.truth is True for result in results))
            evidence = {
                json.dumps(item, sort_keys=True, ensure_ascii=False): item
                for result in results for item in (result.evidence or [])}
            proofs = {
                json.dumps(proof, sort_keys=True, ensure_ascii=False): proof
                for result in results
                for proof in (result.inference_proofs or [])}
            templates = sorted({template for result in results
                                for template in (result.matched_templates or [])})
            return QuestionResult(
                "answered", answer="Yes" if truth else "No",
                candidates=["Yes" if truth else "No"],
                evidence=list(evidence.values()), matched_templates=templates,
                inference_proofs=list(proofs.values()), truth=truth,
                request=(
                    "At least one disjunct has explicit positive truth evidence."
                    if operator == "or" and truth else
                    "Every disjunct has explicit negative truth evidence."
                    if operator == "or" else
                    "Every conjunct has explicit positive truth evidence."
                    if truth else
                    "At least one conjunct has explicit negative truth evidence."))
        if any(result.truth is not None for result in results):
            return QuestionResult(
                "unknown", matched_templates=sorted({template
                    for result in results for template in
                    (result.matched_templates or [])}),
                request="Composed questions must use one consistently grounded answer type.")
        candidate_sets = [
            {_tokens(candidate): candidate for candidate in result.candidates or []}
            for result in results]
        common = (set.union(*(set(candidates) for candidates in candidate_sets))
                  if operator == "or" else
                  set.intersection(*(set(candidates) for candidates in candidate_sets)))

        def answer_field_for(result: QuestionResult) -> str | None:
            fields = {
                "object" if "{subject}" in template else "subject"
                for template in (result.matched_templates or [])
                if "{subject}" in template or "{object}" in template}
            return next(iter(fields)) if len(fields) == 1 else None

        evidence_by_key: dict[str, dict[str, Any]] = {}
        for result in results:
            answer_field = answer_field_for(result)
            for item in result.evidence or []:
                if (not common or answer_field is None
                        or _tokens(str(item.get(answer_field, ""))) in common):
                    evidence_by_key[json.dumps(
                        item, sort_keys=True, ensure_ascii=False)] = item
        proofs_by_key = {}
        for result in results:
            answer_field = answer_field_for(result)
            for proof in result.inference_proofs or []:
                answer = proof.get("conclusion", {}).get(answer_field, "")
                if (not common or answer_field is None
                        or _tokens(str(answer)) in common):
                    proofs_by_key[json.dumps(
                        proof, sort_keys=True, ensure_ascii=False)] = proof
        language_by_key = {
            json.dumps(item, sort_keys=True, ensure_ascii=False): item
            for result in results for item in (result.language_evidence or [])}
        templates = sorted({template for result in results
                            for template in (result.matched_templates or [])})
        if not common:
            return QuestionResult(
                "unknown", evidence=list(evidence_by_key.values()),
                matched_templates=templates,
                inference_proofs=list(proofs_by_key.values()),
                language_evidence=list(language_by_key.values()),
                request="No answer is supported by any clause." if operator == "or"
                        else "No answer is supported by every clause.")
        candidates = [candidate_sets[0][key] for key in sorted(common)]
        status = "answered" if len(candidates) == 1 else "ambiguous"
        return QuestionResult(
            status, answer=candidates[0] if status == "answered" else None,
            candidates=candidates, evidence=list(evidence_by_key.values()),
            matched_templates=templates,
            inference_proofs=list(proofs_by_key.values()),
            language_evidence=list(language_by_key.values()),
            request=("At least one clause supports this answer."
                     if operator == "or" and status == "answered" else
                     "The shared answer is supported by every clause."
                     if status == "answered" else
                     "Multiple answers satisfy the composed question."))

    def _ask_typed_subject_question(
            self, question_words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Answer a narrow `Which TYPE ... OBJECT?` from licensed facts.

        The predicate phrase must come from a licensed positive fact frame, and
        each returned subject must have explicit positive `is-a` evidence for
        TYPE. Relation facts alone never establish the requested class.
        """
        if (len(question_words) < 3
                or question_words[0] not in {"which", "what"}):
            return None
        wh_word = question_words[0]
        frames: dict[tuple[Any, ...], dict[str, Any]] = {}
        observed_predicates = self._observed_predicates_by_relation()
        forms_by_relation: dict[
            tuple[str, ...],
            tuple[set[tuple[str, ...]], dict[tuple[str, ...], dict[str, Any]]]
        ] = {}
        for key, examples in self._fact_pattern_examples.items():
            if (not self._fact_pattern_is_licensed(key, examples)
                    or not self._fact_pattern_polarities.get(key, True)):
                continue
            relation = key[1]
            if relation not in forms_by_relation:
                forms_by_relation[relation] = self._predicate_forms_for_relation(
                    relation, observed_predicates.get(relation, set()))
            predicates, morphology = forms_by_relation[relation]
            for predicate in predicates:
                forms = tuple(predicate)
                if not forms:
                    continue
                first_predicate_start = 1 if wh_word == "what" else 2
                for start in range(first_predicate_start,
                                   len(question_words) - len(forms)):
                    if question_words[start:start + len(forms)] != forms:
                        continue
                    type_words = question_words[1:start]
                    object_words = question_words[start + len(forms):]
                    # Do not absorb copulas or determiners as a requested
                    # class. In particular, "What is the capital of France?"
                    # must reach its learned nominal question frame instead
                    # of being parsed as type="is the" plus relation.
                    if any(word in {"a", "an", "are", "did", "do",
                                    "does", "is", "the", "was", "were"}
                           for word in type_words):
                        continue
                    if ((wh_word == "which" and not type_words)
                            or not object_words):
                        continue
                    signature = (wh_word, relation, forms, type_words,
                                 object_words)
                    frames[signature] = {
                        "wh": wh_word,
                        "relation": relation,
                        "predicate": forms,
                        "type": type_words,
                        "object": object_words,
                        "morphology": morphology.get(forms),
                    }
        if len(frames) != 1:
            return None
        frame = next(iter(frames.values()))
        relation_tokens = frame["relation"]
        expected_type = frame["type"]
        expected_object = frame["object"]
        def lookup_object(store: Any) -> list[FactEvidence]:
            if hasattr(store, "lookup"):
                rows = store.lookup(relation_tokens, expected_object, "object")
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.relation) == relation_tokens
                        and _tokens(fact.object) == expected_object)
            return [fact for fact in rows
                    if self._qualifiers_equal(fact.qualifiers, qualifiers)]

        relation_facts = (
            [(fact, True) for fact in lookup_object(self._facts)]
            + [(fact, False) for fact in lookup_object(self._negative_facts)])
        # Let ordinary learned question frames and backward chaining handle a
        # relation with no direct fact for this bound object.
        if not relation_facts:
            return None
        candidate_subjects = {_tokens(fact.subject)
                              for fact, _polarity in relation_facts}

        def lookup_types(store: Any) -> list[FactEvidence]:
            if not expected_type:
                return []
            if hasattr(store, "select_relation_subjects"):
                rows = store.select_relation_subjects(
                    _tokens("is-a"), candidate_subjects)
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.relation) == _tokens("is-a")
                        and _tokens(fact.subject) in candidate_subjects)
            return [fact for fact in rows
                    if _tokens(fact.object) == expected_type
                    and self._qualifiers_equal(fact.qualifiers, qualifiers)]

        positive_types: dict[tuple[str, ...], list[FactEvidence]] = {}
        negative_types: dict[tuple[str, ...], list[FactEvidence]] = {}
        for polarity, store, target in (
                (True, self._facts, positive_types),
                (False, self._negative_facts, negative_types)):
            for fact in lookup_types(store):
                target.setdefault(_tokens(fact.subject), []).append(fact)

        answers: dict[tuple[str, ...], str] = {}
        evidence: dict[str, dict[str, Any]] = {}
        conflicting: set[tuple[str, ...]] = set()
        for fact, polarity in relation_facts:
            subject_key = _tokens(fact.subject)
            if expected_type and subject_key not in positive_types:
                continue
            counterpart = (self._negative_facts.get(self._fact_key(
                fact.subject, fact.relation, fact.object, fact.qualifiers))
                if polarity else self._facts.get(self._fact_key(
                    fact.subject, fact.relation, fact.object, fact.qualifiers)))
            if ((expected_type and subject_key in negative_types)
                    or counterpart is not None):
                conflicting.add(subject_key)
                evidence[json.dumps(asdict(fact), sort_keys=True,
                                    ensure_ascii=False)] = asdict(fact)
                for type_fact in (*positive_types.get(subject_key, []),
                                  *negative_types.get(subject_key, [])):
                    evidence[json.dumps(asdict(type_fact), sort_keys=True,
                                        ensure_ascii=False)] = asdict(type_fact)
                if counterpart is not None:
                    evidence[json.dumps(asdict(counterpart), sort_keys=True,
                                        ensure_ascii=False)] = asdict(counterpart)
                continue
            if not polarity:
                continue
            answers[subject_key] = fact.subject
            evidence[json.dumps(asdict(fact), sort_keys=True,
                                ensure_ascii=False)] = asdict(fact)
            for type_fact in positive_types.get(subject_key, []):
                evidence[json.dumps(asdict(type_fact), sort_keys=True,
                                    ensure_ascii=False)] = asdict(type_fact)

        template = (wh_word + (" <type>" if expected_type else "") + " "
                    + " ".join(frame["predicate"]) + " <object>")
        language_evidence = [{
            "kind": ("typed_subject_question" if expected_type
                     else "subject_question"),
            "wh": wh_word,
            **({"type": " ".join(expected_type)} if expected_type else {}),
            "predicate": " ".join(frame["predicate"]),
            "relation": " ".join(relation_tokens),
            "evidence": ("licensed positive fact frame and explicit is-a facts"
                         if expected_type else "licensed positive fact frame"),
            **({"morphology": frame["morphology"]}
               if frame["morphology"] else {}),
        }]
        candidate_names = [answers[key] for key in sorted(answers)]
        if conflicting:
            candidate_names.extend(
                next((fact.subject for fact, _polarity in relation_facts
                      if _tokens(fact.subject) == key), " ".join(key))
                for key in sorted(conflicting) if key not in answers)
            candidate_names = sorted(set(candidate_names), key=_tokens)
            return QuestionResult(
                "ambiguous", candidates=candidate_names or None,
                evidence=list(evidence.values()), matched_templates=[template],
                language_evidence=language_evidence,
                request="Relation or type evidence conflicts for this typed question.")
        if len(candidate_names) > 1:
            return QuestionResult(
                "ambiguous", candidates=candidate_names,
                evidence=list(evidence.values()), matched_templates=[template],
                language_evidence=language_evidence,
                request="Multiple source-backed entities satisfy this question.")
        if not candidate_names:
            return QuestionResult(
                "unknown", evidence=list(evidence.values()) or None,
                matched_templates=[template], language_evidence=language_evidence,
                request=("No matching relation has explicit positive evidence for "
                         "the requested type." if expected_type else
                         "No positive fact matches this source-grounded relation "
                         "and bound object."))
        return QuestionResult(
            "answered", answer=candidate_names[0], candidates=candidate_names,
            evidence=list(evidence.values()), matched_templates=[template],
            language_evidence=language_evidence)

    def _ask_typed_object_did_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]) -> QuestionResult | None:
        """Answer ``Which TYPE did SUBJECT VERB?`` from typed stored facts.

        The object must have explicit positive ``is-a`` evidence for TYPE.
        Relation meaning comes from a stored fact; regular past-to-base
        spelling only aligns the ``did`` construction and does not license a
        new relation or object type.
        """
        if len(words) < 5 or words[0] != "which":
            return None
        did_positions = [index for index, token in enumerate(words)
                         if token == "did"]
        if len(did_positions) != 1:
            return None
        did = did_positions[0]
        requested_type = words[1:did]
        remaining = words[did + 1:]
        if not requested_type or not remaining:
            return None

        facts = [fact for fact in self._facts.values()
                 if self._qualifiers_equal(fact.qualifiers, qualifiers)]
        type_relation = _tokens("is-a")
        typed_objects = {
            _tokens(fact.subject) for fact in facts
            if (_tokens(fact.relation) == type_relation
                and _tokens(fact.object) == requested_type)
        }
        negative_facts = [fact for fact in self._negative_facts.values()
                          if self._qualifiers_equal(
                              fact.qualifiers, qualifiers)]
        matches: dict[
            tuple[str, ...], tuple[str, list[FactEvidence], bool]
        ] = {}
        relation_hits = False
        for fact in facts:
            relation = _tokens(fact.relation)
            if len(relation) != 1:
                continue
            subject = _tokens(fact.subject)
            if remaining[:len(subject)] != subject:
                continue
            query_predicate = remaining[len(subject):]
            if not query_predicate:
                continue
            verb = relation[0]
            base_forms = {relation}
            if verb.endswith("ied") and len(verb) > 3:
                base_forms.add((verb[:-3] + "y",))
            if verb.endswith("ed") and len(verb) > 2:
                base_forms.update({(verb[:-2],), (verb[:-2] + "e",)})
                if (len(verb) > 4 and verb[-3] == verb[-4]
                        and verb[-3].isalpha()):
                    base_forms.add((verb[:-3],))
            if query_predicate not in base_forms:
                continue
            relation_hits = True
            obj = _tokens(fact.object)
            if obj not in typed_objects:
                continue
            evidence = [fact]
            evidence.extend(type_fact for type_fact in facts
                            if (_tokens(type_fact.relation) == type_relation
                                and _tokens(type_fact.subject) == obj
                                and _tokens(type_fact.object) == requested_type))
            conflicting = any(
                ((_tokens(negative.relation) == relation
                  and _tokens(negative.subject) == subject
                  and _tokens(negative.object) == obj)
                 or (_tokens(negative.relation) == type_relation
                     and _tokens(negative.subject) == obj
                     and _tokens(negative.object) == requested_type))
                for negative in negative_facts)
            if conflicting:
                evidence.extend(
                    negative for negative in negative_facts
                    if ((_tokens(negative.relation) == relation
                         and _tokens(negative.subject) == subject
                         and _tokens(negative.object) == obj)
                        or (_tokens(negative.relation) == type_relation
                            and _tokens(negative.subject) == obj
                            and _tokens(negative.object) == requested_type)))
            matches[obj] = (fact.object, evidence, conflicting)

        template = " ".join(words)
        if not matches:
            if relation_hits:
                return QuestionResult(
                    "unknown", matched_templates=[template],
                    request=("A matching object is stored, but no positive "
                             "type fact supports the requested "
                             f"classification: {' '.join(requested_type)}."))
            return None
        answers = [matches[key][0] for key in sorted(matches)]
        evidence_by_key = {
            json.dumps(asdict(fact), sort_keys=True, ensure_ascii=False): fact
            for _answer, support, _conflict in matches.values()
            for fact in support
        }
        evidence = [asdict(fact) for fact in evidence_by_key.values()]
        if len(answers) > 1 or any(row[2] for row in matches.values()):
            return QuestionResult(
                "ambiguous", candidates=answers, evidence=evidence,
                matched_templates=[template],
                request=("The type or relation evidence conflicts for a "
                         "candidate object." if any(
                             row[2] for row in matches.values()) else
                         "Multiple typed objects satisfy this question."))
        return QuestionResult(
            "answered", answer=answers[0], candidates=answers,
            evidence=evidence, matched_templates=[template])

    def _ask_do_support_object_question(
            self, question_words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Resolve `Which TYPE does SUBJECT base-verb ...?` from learned frames.

        The only productive morphology here is regular third-person -s/-es
        inversion licensed by the explicit auxiliary `does`. Relation meaning
        still comes from an accepted source frame, and typed answers require
        explicit positive `is-a` evidence.
        """
        if (len(question_words) < 5
                or question_words[0] not in {"which", "what"}):
            return None
        wh_word = question_words[0]
        aux_positions = [index for index, word in enumerate(question_words)
                         if word == "does"]
        if len(aux_positions) != 1:
            return None
        auxiliary = aux_positions[0]
        requested_type = question_words[1:auxiliary]
        if wh_word == "which" and not requested_type:
            return None
        if auxiliary + 2 >= len(question_words):
            return None
        subject_words = question_words[auxiliary + 1:-1]
        # The question must end in a predicate phrase; the trailing token
        # check above avoids treating the bound subject itself as that phrase.
        if not subject_words:
            return None

        observed = self._observed_predicates_by_relation()
        forms_by_relation: dict[
            tuple[str, ...],
            tuple[set[tuple[str, ...]], dict[tuple[str, ...], dict[str, Any]]]
        ] = {}
        parses: dict[tuple[Any, ...], dict[str, Any]] = {}
        for key, examples in self._fact_pattern_examples.items():
            if (not self._fact_pattern_is_licensed(key, examples)
                    or not self._fact_pattern_polarities.get(key, True)):
                continue
            relation = key[1]
            if relation not in forms_by_relation:
                forms_by_relation[relation] = self._predicate_forms_for_relation(
                    relation, observed.get(relation, set()))
            predicate_forms, _morphology = forms_by_relation[relation]
            for surface in predicate_forms:
                if not surface:
                    continue
                source_verb = surface[0]
                base_forms: set[str] = set()
                if len(source_verb) >= 4 and source_verb.endswith("ies"):
                    base_forms.add(source_verb[:-3] + "y")
                if len(source_verb) >= 4 and source_verb.endswith("es"):
                    base_forms.add(source_verb[:-2])
                if len(source_verb) >= 3 and source_verb.endswith("s"):
                    base_forms.add(source_verb[:-1])
                for base in base_forms:
                    alignment = _analyze_predicate_spelling(base, source_verb)
                    if alignment is None or alignment[2] not in {"s", "es"}:
                        continue
                    query_predicate = (base, *surface[1:])
                    if (len(query_predicate) >= len(question_words)
                            or question_words[-len(query_predicate):]
                            != query_predicate):
                        continue
                    predicate_start = len(question_words) - len(query_predicate)
                    if predicate_start <= auxiliary + 1:
                        continue
                    parsed_subject = question_words[auxiliary + 1:predicate_start]
                    if parsed_subject != subject_words[:len(parsed_subject)]:
                        continue
                    if predicate_start + len(query_predicate) != len(question_words):
                        continue
                    signature = (wh_word, requested_type, relation, surface,
                                 parsed_subject, query_predicate)
                    parses[signature] = {
                        "relation": relation,
                        "surface_predicate": surface,
                        "query_predicate": query_predicate,
                        "subject": parsed_subject,
                        "type": requested_type,
                        "alignment": alignment,
                    }
        if len(parses) != 1:
            return None
        frame = next(iter(parses.values()))
        relation_tokens = frame["relation"]
        bound_subject = frame["subject"]

        def lookup_subject(store: Any) -> list[FactEvidence]:
            if hasattr(store, "lookup"):
                rows = store.lookup(relation_tokens, bound_subject, "subject")
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.relation) == relation_tokens
                        and _tokens(fact.subject) == bound_subject)
            return [fact for fact in rows
                    if self._qualifiers_equal(fact.qualifiers, qualifiers)]

        relation_facts = (
            [(fact, True) for fact in lookup_subject(self._facts)]
            + [(fact, False) for fact in lookup_subject(self._negative_facts)])
        if not relation_facts:
            return None
        candidate_objects = {_tokens(fact.object)
                             for fact, _polarity in relation_facts}

        def lookup_types(store: Any) -> list[FactEvidence]:
            if not frame["type"]:
                return []
            if hasattr(store, "select_relation_subjects"):
                rows = store.select_relation_subjects(
                    _tokens("is-a"), candidate_objects)
            else:
                rows = (fact for fact in store.values()
                        if _tokens(fact.relation) == _tokens("is-a")
                        and _tokens(fact.subject) in candidate_objects)
            return [fact for fact in rows
                    if _tokens(fact.object) == frame["type"]
                    and self._qualifiers_equal(fact.qualifiers, qualifiers)]

        positive_types: dict[tuple[str, ...], list[FactEvidence]] = {}
        negative_types: dict[tuple[str, ...], list[FactEvidence]] = {}
        for store, target in ((self._facts, positive_types),
                              (self._negative_facts, negative_types)):
            for fact in lookup_types(store):
                target.setdefault(_tokens(fact.subject), []).append(fact)

        answers: dict[tuple[str, ...], str] = {}
        evidence: dict[str, dict[str, Any]] = {}
        conflicts: set[tuple[str, ...]] = set()
        for fact, polarity in relation_facts:
            obj_key = _tokens(fact.object)
            if frame["type"] and obj_key not in positive_types:
                continue
            opposite = (self._negative_facts.get(self._fact_key(
                fact.subject, fact.relation, fact.object, fact.qualifiers))
                if polarity else self._facts.get(self._fact_key(
                    fact.subject, fact.relation, fact.object, fact.qualifiers)))
            if ((frame["type"] and obj_key in negative_types)
                    or opposite is not None):
                conflicts.add(obj_key)
                evidence[json.dumps(asdict(fact), sort_keys=True,
                                    ensure_ascii=False)] = asdict(fact)
                for type_fact in (*positive_types.get(obj_key, []),
                                  *negative_types.get(obj_key, [])):
                    evidence[json.dumps(asdict(type_fact), sort_keys=True,
                                        ensure_ascii=False)] = asdict(type_fact)
                if opposite is not None:
                    evidence[json.dumps(asdict(opposite), sort_keys=True,
                                        ensure_ascii=False)] = asdict(opposite)
                continue
            if not polarity:
                continue
            answers[obj_key] = fact.object
            evidence[json.dumps(asdict(fact), sort_keys=True,
                                ensure_ascii=False)] = asdict(fact)
            for type_fact in positive_types.get(obj_key, []):
                evidence[json.dumps(asdict(type_fact), sort_keys=True,
                                    ensure_ascii=False)] = asdict(type_fact)

        type_text = (" <type>" if frame["type"] else "")
        template = (f"{wh_word}{type_text} does <subject> "
                    + " ".join(frame["query_predicate"]))
        language_evidence = [{
            "kind": ("typed_object_question" if frame["type"]
                     else "object_question"),
            "wh": wh_word,
            **({"type": " ".join(frame["type"])} if frame["type"] else {}),
            "predicate": " ".join(frame["query_predicate"]),
            "surface_form": " ".join(frame["surface_predicate"]),
            "relation": " ".join(relation_tokens),
            "morphology": {
                "kind": "regular third-person do-support",
                "context": frame["alignment"][0],
                "removed_ending": frame["alignment"][1],
                "ending": frame["alignment"][2],
            },
        }]
        candidate_names = [answers[key] for key in sorted(answers)]
        if conflicts:
            candidate_names.extend(
                next((fact.object for fact, _polarity in relation_facts
                      if _tokens(fact.object) == key), " ".join(key))
                for key in sorted(conflicts) if key not in answers)
            candidate_names = sorted(set(candidate_names), key=_tokens)
            return QuestionResult(
                "ambiguous", candidates=candidate_names or None,
                evidence=list(evidence.values()), matched_templates=[template],
                language_evidence=language_evidence,
                request="Relation or type evidence conflicts for this question.")
        if len(candidate_names) > 1:
            return QuestionResult(
                "ambiguous", candidates=candidate_names,
                evidence=list(evidence.values()), matched_templates=[template],
                language_evidence=language_evidence,
                request="Multiple source-backed objects satisfy this question.")
        if not candidate_names:
            return QuestionResult(
                "unknown", evidence=list(evidence.values()) or None,
                matched_templates=[template], language_evidence=language_evidence,
                request=("No matching relation has explicit positive evidence for "
                         "the requested type." if frame["type"] else
                         "No positive fact matches this source-grounded relation "
                         "and bound subject."))
        return QuestionResult(
            "answered", answer=candidate_names[0], candidates=candidate_names,
            evidence=list(evidence.values()), matched_templates=[template],
            language_evidence=language_evidence)

    def _ask_is_a_definition_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Answer bounded type-definition wording from explicit class facts."""
        prefixes = (
            (("what", "is"), "What is <subject>?"),
            (("what", "kind", "of", "thing", "is"),
             "What kind of thing is <subject>?"),
            (("what", "type", "of", "thing", "is"),
             "What type of thing is <subject>?"),
        )
        matched = next(((prefix, template) for prefix, template in prefixes
                        if words[:len(prefix)] == prefix), None)
        if matched is None:
            return None
        prefix, template = matched
        subject_words = words[len(prefix):]
        if subject_words[:1] in {("a",), ("an",), ("the",)}:
            subject_words = subject_words[1:]
        if not subject_words:
            return None
        subject_key = tuple(subject_words)
        relation = _tokens("is-a")
        positive = [fact for fact in self._facts.values()
                    if (_tokens(fact.subject) == subject_key
                        and _tokens(fact.relation) == relation
                        and self._qualifiers_equal(fact.qualifiers, qualifiers))]
        negative = [fact for fact in self._negative_facts.values()
                    if (_tokens(fact.subject) == subject_key
                        and _tokens(fact.relation) == relation
                        and self._qualifiers_equal(fact.qualifiers, qualifiers))]
        if not positive and not negative:
            return None
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        language_evidence = [{
            "kind": "is_a_definition_question",
            "grammar": template,
            "support": "explicit positive or negative is-a facts",
        }]
        positive_objects = {_tokens(fact.object): fact.object for fact in positive}
        negative_objects = {_tokens(fact.object) for fact in negative}
        conflict = set(positive_objects) & negative_objects
        if conflict or len(positive_objects) > 1:
            return QuestionResult(
                "ambiguous", candidates=[positive_objects[key]
                                          for key in sorted(positive_objects)],
                evidence=evidence, matched_templates=[template],
                language_evidence=language_evidence,
                request="The sources give conflicting or multiple type descriptions; inspect the evidence.")
        if positive_objects:
            answer = next(iter(positive_objects.values()))
            return QuestionResult(
                "answered", answer=answer, candidates=[answer],
                evidence=evidence, matched_templates=[template],
                language_evidence=language_evidence)
        return QuestionResult(
            "unknown", evidence=evidence, matched_templates=[template],
            language_evidence=language_evidence,
            request=("I have source-backed exclusions for this entity, but no "
                     "positive type description to answer what it is."))

    def _ask_is_a_polar_question(
            self, words: tuple[str, ...],
            qualifiers: tuple[tuple[str, str], ...]
            ) -> QuestionResult | None:
        """Resolve ``Is SUBJECT a TYPE?`` only against explicit is-a facts."""
        if len(words) < 4 or words[0] not in {"is", "are", "was", "were"}:
            return None
        relation = _tokens("is-a")
        facts = [fact for store in (self._facts, self._negative_facts)
                 for fact in store.values()
                 if (_tokens(fact.relation) == relation
                     and self._qualifiers_equal(fact.qualifiers, qualifiers))]
        subjects = {_tokens(fact.subject) for fact in facts}
        parses: dict[tuple[tuple[str, ...], tuple[str, ...]], dict[str, Any]] = {}
        for subject in subjects:
            start = 1
            if start < len(words) and words[start] in {"a", "an", "the"}:
                start += 1
            if words[start:start + len(subject)] != subject:
                continue
            article_index = start + len(subject)
            if article_index >= len(words) or words[article_index] not in {"a", "an"}:
                continue
            object_words = words[article_index + 1:]
            if not object_words:
                continue
            object_key = tuple(object_words)
            parses[(subject, object_key)] = {
                "subject": subject,
                "object": object_key,
                "positive": [fact for fact in self._facts.values()
                             if (_tokens(fact.subject) == subject
                                 and _tokens(fact.relation) == relation
                                 and _tokens(fact.object) == object_key
                                 and self._qualifiers_equal(
                                     fact.qualifiers, qualifiers))],
                "negative": [fact for fact in self._negative_facts.values()
                             if (_tokens(fact.subject) == subject
                                 and _tokens(fact.relation) == relation
                                 and _tokens(fact.object) == object_key
                                 and self._qualifiers_equal(
                                     fact.qualifiers, qualifiers))],
            }
        if not parses:
            return None
        if len(parses) > 1:
            return QuestionResult(
                "ambiguous", matched_templates=["<copula> <subject> a <type>?"],
                request="This type question has more than one possible entity boundary.")
        parsed = next(iter(parses.values()))
        positive, negative = parsed["positive"], parsed["negative"]
        evidence = [asdict(fact) for fact in (*positive, *negative)]
        template = "<copula> <subject> a <type>?"
        if positive and negative:
            return QuestionResult(
                "ambiguous", evidence=evidence, matched_templates=[template],
                request="Positive and negative sources conflict for this type claim.")
        if positive:
            return QuestionResult(
                "answered", answer="Yes", candidates=["Yes"], truth=True,
                evidence=evidence, matched_templates=[template])
        if negative:
            return QuestionResult(
                "answered", answer="No", candidates=["No"], truth=False,
                evidence=evidence, matched_templates=[template])
        subject_facts = [fact for fact in self._facts.values()
                         if (_tokens(fact.subject) == parsed["subject"]
                             and _tokens(fact.relation) == relation
                             and self._qualifiers_equal(
                                 fact.qualifiers, qualifiers))]
        subject = (subject_facts[0].subject if subject_facts else
                   " ".join(parsed["subject"]))
        known_types = sorted({fact.object for fact in subject_facts},
                             key=str.casefold)
        target_type = " ".join(parsed["object"])
        request = (f"Stored type: {subject} is "
                   f"{'an' if known_types and known_types[0][:1].casefold() in 'aeiou' else 'a'} "
                   f"{' / '.join(known_types)}. "
                   f"There is no explicit positive or negative evidence for "
                   f"the claim that {subject} is "
                   f"{'an' if target_type[:1].casefold() in 'aeiou' else 'a'} "
                   f"{target_type}.") if known_types else (
            f"There is no explicit positive or negative evidence for the "
            f"claim that {subject} is a {target_type}.")
        return QuestionResult(
            "unknown", evidence=[asdict(fact) for fact in subject_facts] or None,
            matched_templates=[template],
            request=request,
            reason_code="missing_is_a_evidence")

    def ask(self, question: str, *,
            qualifiers: Mapping[str, str] | None = None,
            max_inference_expansions: int = 10_000) -> QuestionResult:
        """Answer a learned question, optionally filtered by explicit context.

        Qualifier filters are exact, open-world constraints: facts missing a
        requested qualifier do not match. The aggregate bound applies across
        every candidate answer considered for a learned inference question.
        """
        question = _display(question, "question")
        if (not isinstance(max_inference_expansions, int)
                or isinstance(max_inference_expansions, bool)
                or max_inference_expansions < 1):
            raise ValueError("max_inference_expansions must be a positive integer")
        distributive = self._ask_distributive_subject_question(
            question, qualifiers=qualifiers)
        if distributive is not None:
            return distributive
        conjunctive = self._ask_composed_question(
            question, qualifiers=qualifiers)
        if conjunctive is not None:
            return conjunctive
        words = _tokens(question)
        requested_qualifiers = self._normalize_qualifiers(qualifiers)
        subject_pattern_result = self._ask_subject_pattern_question(
            words, requested_qualifiers)
        if subject_pattern_result is not None:
            return self._attach_query_alias_evidence(
                question, subject_pattern_result)
        class_definition = self._ask_is_a_definition_question(
            words, requested_qualifiers)
        if class_definition is not None:
            return self._attach_query_alias_evidence(question, class_definition)
        observed_predicates = self._observed_predicates_by_relation()
        if self._is_grounded_progressive_question(words, observed_predicates):
            scope = dict(requested_qualifiers)
            if ("aspect" in scope
                    and _tokens(scope["aspect"]) != ("progressive",)):
                return QuestionResult(
                    "unknown",
                    request="The progressive wording requires aspect=progressive evidence.")
            scope["aspect"] = "progressive"
            requested_qualifiers = self._normalize_qualifiers(scope)
        qualified_result = self._ask_multi_qualified_question(
            words, requested_qualifiers)
        if qualified_result is None:
            qualified_result = self._ask_qualified_question(
                words, requested_qualifiers)
        if qualified_result is not None:
            return self._attach_query_alias_evidence(question, qualified_result)
        typed_subject_result = self._ask_typed_subject_question(
            words, requested_qualifiers)
        if typed_subject_result is not None:
            return self._attach_query_alias_evidence(
                question, typed_subject_result)
        do_support_object_result = self._ask_do_support_object_question(
            words, requested_qualifiers)
        if do_support_object_result is not None:
            return self._attach_query_alias_evidence(
                question, do_support_object_result)
        matches: list[tuple[str, str, list[FactEvidence], str, str]] = []
        question_frames, induced_frames = self._question_frames_for_ask()
        forms_by_relation: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        morphology_by_relation: dict[
            tuple[str, ...], dict[tuple[str, ...], dict[str, Any]]] = {}
        for relation in {tuple(json.loads(key[0]))
                         for key in question_frames}:
            forms, morphology = self._predicate_forms_for_relation(
                relation, observed_predicates.get(relation, set()))
            forms_by_relation[relation] = forms
            morphology_by_relation[relation] = morphology
        matched_morphology: dict[str, dict[str, Any]] = {}
        matched_aliases: dict[str, dict[str, Any]] = {}
        matched_induced_frames: dict[str, dict[str, Any]] = {}
        matched_frame_transformations: dict[str, dict[str, Any]] = {}
        optional_frame_evidence = self._optional_question_word_evidence(
            requested_qualifiers)
        matched_optional_frame_evidence: dict[str, dict[str, Any]] = {}
        direct_parse_signatures: set[tuple[Any, ...]] = set()
        optional_parse_candidates: list[
            tuple[tuple[Any, ...], tuple[str, str, list[FactEvidence], str, str],
                  list[dict[str, Any]]]
        ] = []
        entity_alias_records = self._entity_alias_records()
        known_entities: dict[tuple[str, ...], str] | None = None

        def all_known_entities() -> dict[tuple[str, ...], str]:
            nonlocal known_entities
            if known_entities is None:
                known_entities = {}
                for fact in self.facts() + self.negative_facts():
                    if not self._qualifiers_equal(
                            fact.qualifiers, requested_qualifiers):
                        continue
                    if _tokens(fact.relation) == _tokens("has relation type"):
                        continue
                    known_entities[_tokens(fact.subject)] = fact.subject
                    known_entities[_tokens(fact.object)] = fact.object
                for alias, record in entity_alias_records.items():
                    known_entities[alias] = record["entity"]
            return known_entities

        if words[:1] == ("is",):
            known = all_known_entities()
            polar_matches: list[tuple[str, str, str]] = []
            for subject_key, subject_value in known.items():
                if words[1:1 + len(subject_key)] != subject_key:
                    continue
                pos = 1 + len(subject_key)
                if pos < len(words) and words[pos] in {"a", "an", "the"}:
                    pos += 1
                for rule in self._inference_rules.values():
                    relation_tokens = _tokens(rule.conclusion_relation)
                    end = pos + len(relation_tokens)
                    if not relation_tokens or words[pos:end] != relation_tokens:
                        continue
                    if (relation_tokens[-1] != "of" and end < len(words)
                            and words[end] == "of"):
                        end += 1
                    object_value = known.get(words[end:])
                    if object_value is not None:
                        polar_matches.append((subject_value,
                                              rule.conclusion_relation,
                                              object_value))
            polar_matches = sorted(set(polar_matches))
            if len(polar_matches) == 1:
                subject, relation, obj = polar_matches[0]
                inferred = self.infer_relation(
                    subject, relation, obj,
                    qualifiers=dict(requested_qualifiers),
                    max_expansions=max_inference_expansions)
                if inferred.status == "answered":
                    return QuestionResult(
                        "answered", answer="Yes", candidates=["Yes"],
                        inference_proofs=list(inferred.proofs), truth=True,
                        matched_templates=[question],
                        request=inferred.request,
                        complete=inferred.complete,
                        expansions=inferred.expansions)
                if inferred.status == "ambiguous":
                    return QuestionResult(
                        "ambiguous", inference_proofs=list(inferred.proofs),
                        request=(inferred.request or
                                 "The rule search found conflicting support for this relation."),
                        complete=inferred.complete,
                        reason_code=inferred.reason_code,
                        expansions=inferred.expansions)
                if inferred.failure_kind == "missing_premise":
                    details = []
                    supported_premises: dict[tuple[str, str, str], None] = {}
                    for item in inferred.missing_premises[:6]:
                        for premise in item.get("supported_premises", []):
                            key = (str(premise.get("subject", "?")),
                                   str(premise.get("relation", "?")),
                                   str(premise.get("object", "?")))
                            supported_premises.setdefault(key, None)
                        missing = item.get("missing_premise", {})
                        details.append(
                            f"Rule {item.get('rule_id', '?')} needs premise "
                            f"{item.get('premise_index', '?')}: "
                            f"{missing.get('subject', '?')} — "
                            f"{missing.get('relation', '?')} → "
                            f"{missing.get('object', '?')}.")
                    if details:
                        known = "; ".join(
                            f"{subject} — {relation} → {object_}"
                            for subject, relation, object_
                            in list(supported_premises)[:3])
                        detail = ((f"I have {known}. " if known else "")
                                  + "I still need:\n" + "\n".join(details)
                                  + "\nTell me a missing fact or point me to a source.")
                    else:
                        detail = ("No source-backed proof establishes this claim. "
                                  "I cannot answer yes or no from the facts I have; "
                                  "add a relevant fact or point me to a source.")
                    return QuestionResult(
                        "unknown", request=detail, reason_code="missing_premise",
                        complete=inferred.complete, expansions=inferred.expansions)
                if not inferred.complete:
                    return QuestionResult(
                        "unknown", request="Bounded inference search did not establish a complete answer.",
                        complete=False, expansions=inferred.expansions)
        for (relation_repr, answer_field, prefix, suffix), entities in question_frames.items():
            key = (relation_repr, answer_field, prefix, suffix)
            if not self._question_frame_is_licensed(key, entities):
                continue
            relation_tokens = tuple(json.loads(relation_repr))
            relation = " ".join(relation_tokens)
            frame_variants = []
            for frame_prefix, frame_suffix in self._question_frame_variants(
                    relation_tokens, prefix, suffix,
                    forms_by_relation.get(relation_tokens, {relation_tokens}),
                    morphology_by_relation.get(relation_tokens, {})):
                frame_variants.append((frame_prefix, frame_suffix, []))
                if (frame_prefix, frame_suffix) == (prefix, suffix):
                    frame_variants.extend(
                        variant for variant in self._optional_question_frame_variants(
                            prefix, suffix, optional_frame_evidence.get(key, []))
                        if variant[2])
            for frame_prefix, frame_suffix, used_optional_evidence in frame_variants:
                if (len(words) <= len(frame_prefix) + len(frame_suffix)
                        or words[:len(frame_prefix)] != frame_prefix
                        or (frame_suffix and words[-len(frame_suffix):] != frame_suffix)):
                    continue
                end = len(words) - len(frame_suffix) if frame_suffix else len(words)
                bound_words = words[len(frame_prefix):end]
                if not bound_words:
                    continue
                bound = " ".join(bound_words)
                bound_key = _tokens(bound)
                alias_record = entity_alias_records.get(bound_key)
                canonical_bound = _tokens(alias_record["entity"] if alias_record
                                           else self._canonicalize_entity(bound))
                # Accept a leading article as surface wording only when the
                # exact entity is absent and the article-free form is known.
                if bound_key[:1] in {("a",), ("an",), ("the",)}:
                    known = all_known_entities()
                    bare_key = bound_key[1:]
                    if canonical_bound not in known and bare_key in known:
                        bound_key = bare_key
                        canonical_bound = bare_key
                if alias_record is not None:
                    alias_evidence = dict(alias_record) | {"alias": bound}
                    matched_aliases[json.dumps(
                        alias_evidence, sort_keys=True, ensure_ascii=False
                    )] = alias_evidence
                bound_field = "object" if answer_field == "subject" else "subject"
                evidence = [fact for fact in self._facts.values()
                            if _tokens(fact.relation) == relation_tokens
                            and self._has_qualifiers(fact, requested_qualifiers)
                            and _tokens(fact.object if bound_field == "object" else fact.subject)
                            == canonical_bound]
                template = " ".join(frame_prefix + ("{" + bound_field + "}",)
                                     + frame_suffix)
                match = (answer_field, relation, evidence, template, bound)
                if (prefix[:1] in {("who",), ("what",)}
                        and len(prefix) == 2
                        and prefix[1:] == relation_tokens
                        and frame_prefix == (prefix[0], "has") + prefix[1:]
                        and not frame_suffix):
                    supporting_examples = []
                    for example_words in entities:
                        example_entity = _tokens(" ".join(example_words))
                        example_facts = [fact for fact in self._facts.values()
                                         if _tokens(fact.relation) == relation_tokens
                                         and _tokens(
                                             fact.object if bound_field == "object"
                                             else fact.subject) == example_entity]
                        supporting_examples.append({
                            "bound_entity": " ".join(example_words),
                            "sources": sorted({source for fact in example_facts
                                               for source in fact.sources}),
                        })
                    transform = {
                        "kind": "regular_perfect_aspect_question_frame",
                        "rule": "singular WH subject + has + regular -ed participle",
                        "licensed_frame": " ".join(prefix),
                        "derived_frame": " ".join(frame_prefix),
                        "supporting_examples": supporting_examples,
                    }
                    matched_frame_transformations[json.dumps(
                        transform, sort_keys=True, ensure_ascii=False)] = transform
                if (answer_field == "subject" and len(prefix) == 2
                        and prefix[0] == "who" and not suffix
                        and (
                            (not frame_prefix and len(frame_suffix) == 4
                             and frame_suffix[0] == "was"
                             and frame_suffix[2:] == ("by", "whom"))
                            or (frame_prefix == ("who", "was")
                                and len(frame_suffix) == 2
                                and frame_suffix[1] == "by"))):
                    passive_verb = (frame_suffix[1] if not frame_prefix
                                    else frame_suffix[0])
                    if not passive_verb.endswith("ed"):
                        continue
                    supporting_examples = []
                    for example_words in entities:
                        example_entity = _tokens(" ".join(example_words))
                        example_facts = [fact for fact in self._facts.values()
                                         if _tokens(fact.relation) == relation_tokens
                                         and _tokens(fact.object) == example_entity]
                        supporting_examples.append({
                            "bound_entity": " ".join(example_words),
                            "sources": sorted({source for fact in example_facts
                                               for source in fact.sources}),
                        })
                    transform = {
                        "kind": "active_to_passive_subject_question_frame",
                        "rule": ("licensed regular -ed active predicate becomes "
                                 "a passive by-phrase; object remains bound and "
                                 "the agent remains the answer"),
                        "predicate": passive_verb,
                        "licensed_frame": " ".join(
                            prefix + ("{object}",) + suffix),
                        "derived_frame": (
                            "{object} was " + passive_verb + " by whom"
                            if not frame_prefix else
                            "Who was {object} " + passive_verb + " by"),
                        "supporting_examples": supporting_examples,
                    }
                    matched_frame_transformations[json.dumps(
                        transform, sort_keys=True, ensure_ascii=False)] = transform
                if (len(prefix) == 5
                        and prefix[:3] == ("who", "is", "the")
                        and prefix[-1] == "of"
                        and frame_prefix == ("who", relation_tokens[-1])
                        and not frame_suffix):
                    noun = prefix[-2]
                    noun_stem = (noun[:-2] if noun.endswith(("er", "tor"))
                                 and len(noun) > 3 else "")
                    verb = relation_tokens[-1]
                    verb_stem = verb[:-2] if verb.endswith("ed") else ""
                    if noun_stem and noun_stem == verb_stem:
                        supporting_examples = []
                        for example_words in entities:
                            example_entity = _tokens(" ".join(example_words))
                            example_facts = [fact for fact in self._facts.values()
                                             if _tokens(fact.relation) == relation_tokens
                                             and _tokens(
                                                 fact.object if bound_field == "object"
                                                 else fact.subject) == example_entity]
                            supporting_examples.append({
                                "bound_entity": " ".join(example_words),
                                "sources": sorted({source for fact in example_facts
                                                   for source in fact.sources}),
                            })
                        transform = {
                            "kind": "regular_agent_noun_to_verb_question_frame",
                            "rule": "agent noun -er/-or and past verb -ed share a stem",
                            "noun": noun,
                            "verb": verb,
                            "stem": noun_stem,
                            "licensed_frame": " ".join(prefix),
                            "derived_frame": " ".join(frame_prefix),
                            "supporting_examples": supporting_examples,
                        }
                        matched_frame_transformations[json.dumps(
                            transform, sort_keys=True, ensure_ascii=False)] = transform
                used_items = list(used_optional_evidence)
                used_items.extend(
                    item for item in optional_frame_evidence.get(key, [])
                    if (tuple(item.get("variant_prefix", ())) == frame_prefix
                        and tuple(item.get("variant_suffix", ()))
                        == frame_suffix))
                parse_signature = (relation_tokens, answer_field, canonical_bound)
                is_groundable = bool(evidence) or self._relation_has_inference_schema(
                    relation, requested_qualifiers)
                if used_optional_evidence and is_groundable:
                    optional_parse_candidates.append(
                        (parse_signature, match, used_items))
                else:
                    if is_groundable:
                        direct_parse_signatures.add(parse_signature)
                    matches.append(match)
                    for item in used_items:
                        matched_optional_frame_evidence[json.dumps(
                            item, sort_keys=True, ensure_ascii=False)] = item
                if key in induced_frames:
                    proposal = induced_frames[key]
                    if proposal.get("derivation"):
                        matched_induced_frames[template] = {
                            "kind": "fact_pattern_derived_question_frame",
                            "artifact_id": proposal["artifact_id"],
                            "base_relation": proposal["base_relation"],
                            "target_relation": proposal["target_relation"],
                            "lineage": copy.deepcopy(proposal["lineage"]),
                            "derivation": copy.deepcopy(proposal["derivation"]),
                        }
                    else:
                        matched_induced_frames[template] = {
                            "kind": "induced_question_frame",
                            "artifact_id": proposal["artifact_id"],
                            "base_relation": proposal["base_relation"],
                            "target_relation": proposal["target_relation"],
                            "lineage": copy.deepcopy(proposal["lineage"]),
                        }
                for predicate, rule_evidence in morphology_by_relation.get(
                        relation_tokens, {}).items():
                    in_prefix = any(
                        frame_prefix[index:index + len(predicate)] == predicate
                        for index in range(len(frame_prefix) - len(predicate) + 1))
                    in_suffix = any(
                        frame_suffix[index:index + len(predicate)] == predicate
                        for index in range(len(frame_suffix) - len(predicate) + 1))
                    if in_prefix or in_suffix:
                        matched_morphology[json.dumps(
                            rule_evidence, sort_keys=True, ensure_ascii=False
                        )] = rule_evidence

        # A narrowly bounded agent-noun question can be answered from an
        # accepted verb relation when the noun and relation share a regular
        # derivational stem ("designed" / "designer", "created" / "creator").
        # This parser never creates facts or licenses a relation: the answer
        # still has to come from an accepted fact for the exact bound entity.
        if (words[:3] in {("who", "was", "the"), ("who", "is", "the")}
                and len(words) >= 6):
            for of_index in range(4, len(words) - 1):
                nominal = words[3:of_index]
                bound_words = words[of_index + 1:]
                if len(nominal) != 1 or not bound_words:
                    continue
                noun = nominal[0]
                noun_stems = set()
                if noun.endswith("er") and len(noun) > 2:
                    noun_stems.add(noun[:-2])
                if noun.endswith("or") and len(noun) > 2:
                    noun_stems.add(noun[:-2])
                if not noun_stems:
                    continue
                bound_key = _tokens(self._canonicalize_entity(
                    " ".join(bound_words)))
                if (bound_key[:1] in {("a",), ("an",), ("the",)}
                        and bound_key not in all_known_entities()):
                    bound_key = _tokens(self._canonicalize_entity(
                        " ".join(bound_words[1:])))
                if bound_key not in all_known_entities():
                    continue
                relations_by_stem: dict[str, set[tuple[str, ...]]] = {}
                for fact in self._facts.values():
                    relation_tokens = _tokens(fact.relation)
                    if not relation_tokens:
                        continue
                    verb = relation_tokens[-1]
                    stems = set()
                    if verb.endswith("ied") and len(verb) > 3:
                        stems.add(verb[:-3] + "y")
                    if verb.endswith("ed") and len(verb) > 2:
                        stems.add(verb[:-2])
                        stems.add(verb[:-2] + "e")
                    for stem in noun_stems & stems:
                        relations_by_stem.setdefault(stem, set()).add(
                            relation_tokens)
                matching_relations = {
                    relation for relations in relations_by_stem.values()
                    for relation in relations
                    if any(_tokens(fact.object) == bound_key
                           and _tokens(fact.relation) == relation
                           and self._has_qualifiers(
                               fact, requested_qualifiers)
                           for fact in self._facts.values())
                }
                if len(matching_relations) != 1:
                    continue
                relation_tokens = next(iter(matching_relations))
                relation = " ".join(relation_tokens)
                evidence = [fact for fact in self._facts.values()
                            if _tokens(fact.relation) == relation_tokens
                            and _tokens(fact.object) == bound_key
                            and self._has_qualifiers(
                                fact, requested_qualifiers)]
                template = f"Who was the {noun} of {{object}}"
                signature = (relation_tokens, "subject", bound_key)
                if signature not in direct_parse_signatures:
                    matches.append(("subject", relation, evidence,
                                    template, " ".join(bound_words)))
                    direct_parse_signatures.add(signature)

        if optional_parse_candidates:
            parse_signatures = direct_parse_signatures | {
                signature for signature, _match, _items
                in optional_parse_candidates}
            if len(parse_signatures) != 1:
                return QuestionResult(
                    "unknown",
                    request=("The learned optional question tokens allow multiple "
                             "grounded parses; please rephrase or teach a contrastive example."))
            for _signature, match, items in optional_parse_candidates:
                matches.append(match)
                for item in items:
                    matched_optional_frame_evidence[json.dumps(
                        item, sort_keys=True, ensure_ascii=False)] = item

        if not matches and words[:2] == ("who", "is"):
            # A conclusion relation introduced by a stored inference rule is
            # sufficient to parse the bounded form "Who is a <relation>
            # <entity>?". This lets rule conclusions enter the same
            # proof-backed answer path as taught question frames.
            articles = {"a", "an", "the"}
            for rule in self._inference_rules.values():
                relation_tokens = _tokens(rule.conclusion_relation)
                if not relation_tokens:
                    continue
                start = 2
                if start < len(words) and words[start] in articles:
                    start += 1
                end = start + len(relation_tokens)
                if words[start:end] != relation_tokens:
                    continue
                if (relation_tokens[-1] != "of" and end < len(words)
                        and words[end] == "of"):
                    end += 1
                if end >= len(words):
                    continue
                bound = " ".join(words[end:])
                bound_key = _tokens(self._canonicalize_entity(bound))
                if bound_key not in all_known_entities():
                    continue
                relation = " ".join(relation_tokens)
                template = question
                signature = (relation_tokens, "subject", bound_key)
                if signature not in direct_parse_signatures:
                    matches.append(("subject", relation, [], template, bound))
                    direct_parse_signatures.add(signature)

        if not matches:
            stored_subject_result = self._ask_stored_relation_subject_question(
                words, requested_qualifiers)
            if stored_subject_result is not None:
                return self._attach_query_alias_evidence(
                    question, stored_subject_result)
            source_location_wh = self._ask_source_licensed_location_wh_question(
                words, requested_qualifiers)
            if source_location_wh is not None:
                return self._attach_query_alias_evidence(
                    question, source_location_wh)
            typed_object_did = self._ask_typed_object_did_question(
                words, requested_qualifiers)
            if typed_object_did is not None:
                return self._attach_query_alias_evidence(
                    question, typed_object_did)
            source_object_wh = self._ask_source_licensed_object_wh_question(
                words, requested_qualifiers)
            if source_object_wh is not None:
                return self._attach_query_alias_evidence(
                    question, source_object_wh)
            polar_result = self.ask_polar_question(
                question, qualifiers=qualifiers)
            if polar_result.matched_templates:
                return self._attach_query_alias_evidence(question, polar_result)
            path_result = self.ask_path_question(
                question, qualifiers=qualifiers)
            if path_result.matched_templates:
                return self._attach_query_alias_evidence(question, path_result)
            # Give a useful, bounded explanation when the wording is close to
            # a taught frame. This is diagnostic only: it never licenses a
            # different predicate or answers from the suggested frame.
            frame_hints = []
            for (relation_repr, answer_field, prefix, suffix), _entities in question_frames.items():
                relation_tokens = tuple(json.loads(relation_repr))
                forms, morphology = self._predicate_forms_for_relation(
                    relation_tokens, observed_predicates.get(relation_tokens, set()))
                for frame_prefix, frame_suffix in self._question_frame_variants(
                        relation_tokens, prefix, suffix, forms, morphology):
                    shared = 0
                    for actual, expected in zip(words, frame_prefix):
                        if actual != expected:
                            break
                        shared += 1
                    if shared:
                        template = " ".join(
                            frame_prefix + ("{" + ("object" if answer_field == "subject" else "subject") + "}",)
                            + frame_suffix) + "?"
                        template = template[:1].upper() + template[1:]
                        frame_hints.append((shared, len(frame_prefix), template, relation_tokens))
            if frame_hints:
                _shared, _length, template, _relation = max(
                    frame_hints, key=lambda item: (item[0], item[1], item[2]))
                return QuestionResult(
                    "unknown",
                    request=(f"I don't recognize this wording. The closest taught frame is "
                             f"'{template}'; teach a fact-backed example if you want "
                             "to license this wording."))
            return QuestionResult(
                "unknown", request="Please teach this question with a fact-backed example.")

        answers: dict[tuple[str, ...], str] = {}
        evidence_by_key: dict[tuple[Any, ...], FactEvidence] = {}
        direct_negative_evidence: dict[tuple[Any, ...], dict[str, Any]] = {}
        inference_proofs: list[dict[str, Any]] = []
        inference_evidence: dict[tuple[Any, ...], dict[str, Any]] = {}
        inference_conflict = False
        inference_incomplete = False
        inference_failure_kinds: set[str] = set()
        inference_failure_requests: dict[str, None] = {}
        missing_premises: dict[str, dict[str, Any]] = {}
        inference_budget = max_inference_expansions

        def indexed_rule_answers(answer_field: str, relation: str, bound: str
                                  ) -> tuple[list[str], int, bool] | None:
            """Find bounded answers through indexed base and linear joins.

            Besides extensional rules, this evaluates the common recursive
            form ``edge + relation -> relation`` (subject answers) or its
            inverse ``relation + edge -> relation`` (object answers) to a
            bounded least fixed point. Mutually recursive linear rules use a
            goal-local fixed point in either answer direction. Other derived
            premises use the bounded entity scan or report incomplete search.
            """
            relation_key = _tokens(relation)
            target_rules = [rule for rule in self._inference_rules_for_use()
                            if _tokens(rule.conclusion_relation) == relation_key]
            if not target_rules:
                return None
            qualifier_key = tuple(requested_qualifiers)
            lookup_cache: dict[tuple[tuple[str, ...], str, tuple[str, ...]],
                               list[FactEvidence]] = {}
            work = 0
            scan_exhausted = False
            candidate_keys: dict[tuple[str, ...], str] = {}

            def premise_is_extensional(premise_relation: str) -> bool:
                key = _tokens(premise_relation)
                if self._relation_has_inference_schema(
                        premise_relation, qualifier_key):
                    return False
                if self._relation_type_fact(
                        premise_relation, "symmetric", qualifier_key) is not None:
                    return False
                return not any(
                    len(case.get("conclusion", {})) >= 3
                    and _tokens(case["conclusion"].get("relation", "")) == key
                    and self._normalize_qualifiers(
                        dict(case.get("qualifiers", ()))) == qualifier_key
                    for case in self._derived_cases.values())

            def facts_at(relation_name: str, bound_field: str,
                         value: str) -> list[FactEvidence]:
                nonlocal work, scan_exhausted
                rel_key = _tokens(relation_name)
                value_key = _tokens(self._canonicalize_entity(value))
                cache_key = (rel_key, bound_field, value_key)
                if cache_key in lookup_cache:
                    return lookup_cache[cache_key]
                if isinstance(self._facts, SQLiteFactMap):
                    rows = self._facts.lookup(rel_key, value_key, bound_field)
                else:
                    index = (self._facts_by_relation_object
                             if bound_field == "object"
                             else self._facts_by_relation_subject)
                    keys = index.get((rel_key, value_key), ())
                    rows = (self._facts[key] for key in keys)
                remaining = max(0, inference_budget - work)
                scanned = []
                for fact in rows:
                    if len(scanned) >= remaining:
                        scan_exhausted = True
                        break
                    scanned.append(fact)
                matches = [fact for fact in scanned
                           if _tokens(fact.relation) == rel_key
                           and _tokens(fact.object if bound_field == "object"
                                       else fact.subject) == value_key
                           and self._qualifiers_equal(
                               fact.qualifiers, qualifier_key)]
                work += len(scanned)
                lookup_cache[cache_key] = matches
                return matches

            def has_kind(entity: str, kind: str) -> bool:
                return any(_tokens(fact.object) == _tokens(kind)
                           for fact in facts_at("is-a", "subject", entity))

            def mutually_recursive_answers(
                    ) -> tuple[list[str], int, bool] | None:
                """Close a bounded family of mutually recursive linear rules."""
                all_rules = self._inference_rules_for_use()
                rules_by_conclusion: dict[tuple[str, ...], list[InferenceRule]] = {}
                for rule in all_rules:
                    rules_by_conclusion.setdefault(
                        _tokens(rule.conclusion_relation), []).append(rule)
                closure = {relation_key}
                pending = [relation_key]
                while pending:
                    current_relation = pending.pop()
                    current_rules = rules_by_conclusion.get(current_relation, [])
                    if not current_rules:
                        return None
                    for rule in current_rules:
                        premise_relations = [rule.first_relation,
                                             rule.second_relation]
                        if rule.third_relation is not None:
                            premise_relations.append(rule.third_relation)
                        for premise_relation in premise_relations:
                            premise_key = _tokens(premise_relation)
                            if premise_key in rules_by_conclusion:
                                if premise_key not in closure:
                                    closure.add(premise_key)
                                    pending.append(premise_key)
                            elif self._relation_has_inference_schema(
                                    premise_relation, qualifier_key):
                                # This join path handles learned-rule recursion;
                                # other schemas keep their existing solver.
                                return None
                if not any(
                        _tokens(rule.conclusion_relation) != premise_key
                        for relation in closure
                        for rule in rules_by_conclusion[relation]
                        for premise_key in (
                            _tokens(rule.first_relation),
                            _tokens(rule.second_relation),
                            *(() if rule.third_relation is None else
                              (_tokens(rule.third_relation),))
                        ) if premise_key in closure):
                    return None

                rule_rows = [rule for relation in sorted(closure)
                             for rule in sorted(
                                 rules_by_conclusion[relation],
                                 key=lambda item: item.rule_id)]
                recursive: list[tuple[InferenceRule, str]] = []
                base: list[InferenceRule] = []
                for rule in rule_rows:
                    premise_fields = ["first_relation", "second_relation"]
                    if rule.third_relation is not None:
                        premise_fields.append("third_relation")
                    derived_fields = [field for field in premise_fields
                                      if _tokens(getattr(rule, field)) in closure]
                    if len(derived_fields) > 1:
                        return None
                    if not derived_fields:
                        if not all(premise_is_extensional(
                                getattr(rule, field)) for field in premise_fields):
                            return None
                        base.append(rule)
                        continue
                    if rule.third_relation is not None:
                        return None
                    recursive_field = derived_fields[0]
                    if (answer_field == "subject"
                            and recursive_field != "second_relation"):
                        return None
                    edge_field = ("first_relation"
                                  if recursive_field == "second_relation"
                                  else "second_relation")
                    if not premise_is_extensional(getattr(rule, edge_field)):
                        return None
                    recursive.append((rule, recursive_field))
                if not recursive or not base:
                    return None

                if answer_field == "object":
                    base_by_relation: dict[tuple[str, ...], list[InferenceRule]] = {}
                    recursive_by_relation: dict[
                        tuple[str, ...], list[tuple[InferenceRule, str]]] = {}
                    for rule in base:
                        base_by_relation.setdefault(
                            _tokens(rule.conclusion_relation), []).append(rule)
                    for rule, recursive_field in recursive:
                        recursive_by_relation.setdefault(
                            _tokens(rule.conclusion_relation), []).append(
                                (rule, recursive_field))
                    goal_key = (relation_key,
                                _tokens(self._canonicalize_entity(bound)))
                    goal_entities = {goal_key: bound}
                    answers_by_goal: dict[
                        tuple[tuple[str, ...], tuple[str, ...]],
                        dict[tuple[str, ...], str]] = {}
                    incomplete = False

                    def ensure_goal(goal_relation: tuple[str, ...],
                                    entity: str) -> tuple[
                                        tuple[str, ...], tuple[str, ...]] | None:
                        nonlocal incomplete
                        key = (goal_relation, _tokens(
                            self._canonicalize_entity(entity)))
                        if key not in goal_entities:
                            if len(goal_entities) >= 256:
                                incomplete = True
                                return None
                            goal_entities[key] = entity
                        return key

                    def add_goal_answer(
                            goal: tuple[tuple[str, ...], tuple[str, ...]],
                            answer: str) -> bool:
                        nonlocal incomplete
                        values = answers_by_goal.setdefault(goal, {})
                        key = _tokens(answer)
                        if key in values:
                            return False
                        values[key] = answer
                        if len(values) > 256:
                            incomplete = True
                        return True

                    changed = True
                    while changed and not incomplete and not scan_exhausted:
                        changed = False
                        goal_count = len(goal_entities)
                        for current_goal in sorted(list(goal_entities)):
                            current_relation, _entity_key = current_goal
                            entity = goal_entities[current_goal]
                            for rule in base_by_relation.get(current_relation, []):
                                if rule.third_relation is None:
                                    for head in facts_at(
                                            rule.first_relation, "subject", entity):
                                        middle = head.object
                                        if (rule.middle_kind is not None
                                                and not has_kind(
                                                    middle, rule.middle_kind)):
                                            continue
                                        for tail in facts_at(
                                                rule.second_relation,
                                                "subject", middle):
                                            changed = add_goal_answer(
                                                current_goal, tail.object) or changed
                                else:
                                    first_kind = rule.middle_kind or ""
                                    second_kind = rule.second_middle_kind or ""
                                    for head in facts_at(
                                            rule.first_relation, "subject", entity):
                                        middle1 = head.object
                                        if not has_kind(middle1, first_kind):
                                            continue
                                        for middle_edge in facts_at(
                                                rule.second_relation,
                                                "subject", middle1):
                                            middle2 = middle_edge.object
                                            if not has_kind(middle2, second_kind):
                                                continue
                                            for tail in facts_at(
                                                    rule.third_relation,
                                                    "subject", middle2):
                                                changed = add_goal_answer(
                                                    current_goal,
                                                    tail.object) or changed
                            for rule, recursive_field in (
                                    recursive_by_relation.get(
                                        current_relation, [])):
                                if recursive_field == "first_relation":
                                    dependency = ensure_goal(
                                        _tokens(rule.first_relation), entity)
                                    if dependency is None:
                                        continue
                                    middles = list(answers_by_goal.get(
                                        dependency, {}).values())
                                    for middle in middles:
                                        if (rule.middle_kind is not None
                                                and not has_kind(
                                                    middle, rule.middle_kind)):
                                            continue
                                        for tail in facts_at(
                                                rule.second_relation,
                                                "subject", middle):
                                            changed = add_goal_answer(
                                                current_goal,
                                                tail.object) or changed
                                else:
                                    for head in facts_at(
                                            rule.first_relation,
                                            "subject", entity):
                                        middle = head.object
                                        if (rule.middle_kind is not None
                                                and not has_kind(
                                                    middle, rule.middle_kind)):
                                            continue
                                        dependency = ensure_goal(
                                            _tokens(rule.second_relation), middle)
                                        if dependency is None:
                                            continue
                                        for answer in answers_by_goal.get(
                                                dependency, {}).values():
                                            changed = add_goal_answer(
                                                current_goal, answer) or changed
                        if len(goal_entities) > goal_count:
                            changed = True
                    candidates = answers_by_goal.get(goal_key, {})
                    return (sorted(candidates.values()), work,
                            not incomplete and not scan_exhausted)

                answers_by_relation: dict[
                    tuple[str, ...], dict[tuple[str, ...], str]] = {}

                def add_answer(rule: InferenceRule, answer: str) -> bool:
                    relation = _tokens(rule.conclusion_relation)
                    rows = answers_by_relation.setdefault(relation, {})
                    key = _tokens(answer)
                    if key in rows:
                        return False
                    rows[key] = answer
                    return True

                for rule in base:
                    if rule.third_relation is None:
                        if answer_field == "subject":
                            for tail in facts_at(rule.second_relation,
                                                 "object", bound):
                                middle = tail.subject
                                if (rule.middle_kind is not None
                                        and not has_kind(middle, rule.middle_kind)):
                                    continue
                                for head in facts_at(rule.first_relation,
                                                     "object", middle):
                                    add_answer(rule, head.subject)
                        else:
                            for head in facts_at(rule.first_relation,
                                                 "subject", bound):
                                middle = head.object
                                if (rule.middle_kind is not None
                                        and not has_kind(middle, rule.middle_kind)):
                                    continue
                                for tail in facts_at(rule.second_relation,
                                                     "subject", middle):
                                    add_answer(rule, tail.object)
                    else:
                        first_kind = rule.middle_kind or ""
                        second_kind = rule.second_middle_kind or ""
                        if answer_field == "subject":
                            for tail in facts_at(rule.third_relation,
                                                 "object", bound):
                                middle2 = tail.subject
                                if not has_kind(middle2, second_kind):
                                    continue
                                for middle_edge in facts_at(
                                        rule.second_relation, "object", middle2):
                                    middle1 = middle_edge.subject
                                    if not has_kind(middle1, first_kind):
                                        continue
                                    for head in facts_at(
                                            rule.first_relation, "object", middle1):
                                        add_answer(rule, head.subject)
                        else:
                            for head in facts_at(rule.first_relation,
                                                 "subject", bound):
                                middle1 = head.object
                                if not has_kind(middle1, first_kind):
                                    continue
                                for middle_edge in facts_at(
                                        rule.second_relation, "subject", middle1):
                                    middle2 = middle_edge.object
                                    if not has_kind(middle2, second_kind):
                                        continue
                                    for tail in facts_at(
                                            rule.third_relation, "subject", middle2):
                                        add_answer(rule, tail.object)

                if any(len(values) > 256 for values in
                       answers_by_relation.values()):
                    return (sorted(answers_by_relation.get(
                        relation_key, {}).values()), work, False)

                changed = True
                while changed:
                    changed = False
                    for rule, recursive_field in recursive:
                        derived_relation = _tokens(getattr(rule, recursive_field))
                        current = list(answers_by_relation.get(
                            derived_relation, {}).values())
                        for middle in current:
                            if (rule.middle_kind is not None
                                    and not has_kind(middle, rule.middle_kind)):
                                continue
                            if answer_field == "subject":
                                edges = facts_at(rule.first_relation,
                                                 "object", middle)
                                additions = (edge.subject for edge in edges)
                            else:
                                edges = facts_at(rule.second_relation,
                                                 "subject", middle)
                                additions = (edge.object for edge in edges)
                            for answer in additions:
                                changed = add_answer(rule, answer) or changed
                                if any(len(values) > 256 for values in
                                       answers_by_relation.values()):
                                    return (sorted(answers_by_relation.get(
                                        relation_key, {}).values()), work, False)
                candidates = answers_by_relation.get(relation_key, {})
                return (sorted(candidates.values()), work, not scan_exhausted)

            mutual = mutually_recursive_answers()
            if mutual is not None:
                return mutual

            base_rules = []
            recursive_rules = []
            for rule in target_rules:
                if rule.third_relation is not None:
                    premise_relations = [rule.first_relation,
                                         rule.second_relation,
                                         rule.third_relation]
                    if not all(premise_is_extensional(item)
                               for item in premise_relations):
                        return None
                    base_rules.append(rule)
                    continue
                recursive_positions = [
                    field for field in ("first_relation", "second_relation")
                    if _tokens(getattr(rule, field)) == relation_key]
                if not recursive_positions:
                    if not all(premise_is_extensional(item) for item in
                               (rule.first_relation, rule.second_relation)):
                        return None
                    base_rules.append(rule)
                    continue
                if len(recursive_positions) != 1:
                    return None
                recursive_field = recursive_positions[0]
                if ((answer_field == "subject"
                     and recursive_field != "second_relation")
                        or (answer_field == "object"
                            and recursive_field != "first_relation")):
                    return None
                edge_relation = (rule.first_relation if answer_field == "subject"
                                 else rule.second_relation)
                if not premise_is_extensional(edge_relation):
                    return None
                recursive_rules.append(rule)

            for rule in base_rules:
                if rule.third_relation is None:
                    if answer_field == "subject":
                        # X -first-> M -second-> bound
                        for tail in facts_at(rule.second_relation, "object", bound):
                            middle = tail.subject
                            if (rule.middle_kind is not None
                                    and not has_kind(middle, rule.middle_kind)):
                                continue
                            for head in facts_at(
                                    rule.first_relation, "object", middle):
                                candidate_keys[_tokens(head.subject)] = head.subject
                                if len(candidate_keys) > 256:
                                    return (sorted(candidate_keys.values()),
                                            work, False)
                    else:
                        # bound -first-> M -second-> X
                        for head in facts_at(rule.first_relation, "subject", bound):
                            middle = head.object
                            if (rule.middle_kind is not None
                                    and not has_kind(middle, rule.middle_kind)):
                                continue
                            for tail in facts_at(
                                    rule.second_relation, "subject", middle):
                                candidate_keys[_tokens(tail.object)] = tail.object
                                if len(candidate_keys) > 256:
                                    return (sorted(candidate_keys.values()),
                                            work, False)
                    continue

                first_kind = rule.middle_kind or ""
                second_kind = rule.second_middle_kind or ""
                if answer_field == "subject":
                    # X -first-> M1 -second-> M2 -third-> bound
                    for tail in facts_at(rule.third_relation, "object", bound):
                        middle2 = tail.subject
                        if not has_kind(middle2, second_kind):
                            continue
                        for middle_edge in facts_at(
                                rule.second_relation, "object", middle2):
                            middle1 = middle_edge.subject
                            if not has_kind(middle1, first_kind):
                                continue
                            for head in facts_at(
                                    rule.first_relation, "object", middle1):
                                candidate_keys[_tokens(head.subject)] = head.subject
                                if len(candidate_keys) > 256:
                                    return (sorted(candidate_keys.values()),
                                            work, False)
                else:
                    # bound -first-> M1 -second-> M2 -third-> X
                    for head in facts_at(rule.first_relation, "subject", bound):
                        middle1 = head.object
                        if not has_kind(middle1, first_kind):
                            continue
                        for middle_edge in facts_at(
                                rule.second_relation, "subject", middle1):
                            middle2 = middle_edge.object
                            if not has_kind(middle2, second_kind):
                                continue
                            for tail in facts_at(
                                    rule.third_relation, "subject", middle2):
                                candidate_keys[_tokens(tail.object)] = tail.object
                                if len(candidate_keys) > 256:
                                    return (sorted(candidate_keys.values()),
                                            work, False)
            # Close the supported linear recursive form. Each pass adds at
            # least one distinct entity or terminates; fact lookup is cached
            # and charged to the same caller-visible scan budget.
            changed = True
            while recursive_rules and changed:
                changed = False
                current = list(candidate_keys.values())
                for rule in recursive_rules:
                    for middle in current:
                        if (rule.middle_kind is not None
                                and not has_kind(middle, rule.middle_kind)):
                            continue
                        if answer_field == "subject":
                            edges = facts_at(rule.first_relation, "object", middle)
                            additions = (edge.subject for edge in edges)
                        else:
                            edges = facts_at(rule.second_relation, "subject", middle)
                            additions = (edge.object for edge in edges)
                        for answer in additions:
                            key = _tokens(answer)
                            if key not in candidate_keys:
                                candidate_keys[key] = answer
                                changed = True
                                if len(candidate_keys) > 256:
                                    return (sorted(candidate_keys.values()),
                                            work, False)
            return sorted(candidate_keys.values()), work, not scan_exhausted

        for answer_field, relation, evidence, _template, bound in matches:
            for fact in evidence:
                value = fact.subject if answer_field == "subject" else fact.object
                answers.setdefault(_tokens(value), value)
                fact_key = self._fact_key(
                    fact.subject, fact.relation, fact.object, fact.qualifiers)
                evidence_by_key[fact_key] = fact
                negative = self._negative_facts.get(fact_key)
                if negative is not None:
                    direct_negative_evidence[fact_key] = (
                        asdict(negative) | {"polarity": "negative"})
            relation_key = _tokens(relation)
            if not self._relation_has_inference_schema(
                    " ".join(relation_key), requested_qualifiers):
                continue
            known = all_known_entities()
            possible_answers = list(known.values())
            if len(known) > 256:
                indexed = indexed_rule_answers(answer_field, relation, bound)
                if indexed is None:
                    inference_incomplete = True
                    continue
                possible_answers, candidate_work, candidate_complete = indexed
                inference_budget -= candidate_work
                if not candidate_complete or inference_budget < 1:
                    inference_incomplete = True
                if inference_budget < 1:
                    continue
            for possible_answer in possible_answers:
                if inference_budget < 1:
                    inference_incomplete = True
                    break
                subject, obj = ((possible_answer, bound) if answer_field == "subject"
                                else (bound, possible_answer))
                inferred = self.infer_relation(
                    subject, relation, obj,
                    qualifiers=dict(requested_qualifiers),
                    max_expansions=inference_budget)
                inference_budget -= inferred.expansions
                if inferred.status == "unknown":
                    if not inferred.complete:
                        inference_incomplete = True
                    elif inferred.failure_kind:
                        inference_failure_kinds.add(inferred.failure_kind)
                        if inferred.request:
                            inference_failure_requests[inferred.request] = None
                        for item in inferred.missing_premises:
                            missing_premises[repr(item)] = item
                    continue
                if inferred.status == "ambiguous":
                    inference_conflict = True
                if inferred.status == "answered":
                    root_rules = [proof for proof in inferred.proofs
                                  if _is_derived_proof(proof)]
                    if root_rules:
                        answers.setdefault(_tokens(possible_answer), possible_answer)
                        inference_proofs.extend(root_rules)
                elif inferred.status == "ambiguous":
                    inference_proofs.extend(inferred.proofs)
                for proof in inferred.proofs:
                    for leaf in self._inference_fact_leaves(proof):
                        fact_key = self._fact_key(
                            leaf["subject"], leaf["relation"], leaf["object"],
                            tuple(tuple(item) for item in
                                  leaf.get("qualifiers", ())))
                        contradictions = [negative for negative in self._negative_facts.values()
                                         if self._fact_key(negative.subject,
                                                           negative.relation,
                                                           negative.object,
                                                           negative.qualifiers) == fact_key]
                        if contradictions:
                            inference_evidence[(leaf["subject"], leaf["relation"],
                                                leaf["object"])] = dict(leaf) | {
                                "contradictory_sources": sorted({
                                    source for negative in contradictions
                                    for source in negative.sources})}
        templates = sorted({template for _, _, _, template, _ in matches})
        language_evidence = [matched_morphology[key]
                             for key in sorted(matched_morphology)]
        language_evidence.extend(matched_aliases[key]
                                 for key in sorted(matched_aliases))
        language_evidence.extend(matched_induced_frames[key]
                                 for key in sorted(matched_induced_frames))
        language_evidence.extend(matched_frame_transformations[key]
                                 for key in sorted(matched_frame_transformations))
        language_evidence.extend(matched_optional_frame_evidence[key]
                                 for key in sorted(matched_optional_frame_evidence))
        if not answers:
            if inference_conflict:
                return QuestionResult(
                    "ambiguous", evidence=list(inference_evidence.values()),
                    matched_templates=templates, inference_proofs=inference_proofs,
                    language_evidence=language_evidence,
                    request=("A possible inferred answer conflicts with explicit "
                             "negative evidence or a declared relation integrity "
                             "constraint."))
            if inference_incomplete:
                return QuestionResult(
                    "unknown", matched_templates=templates,
                    language_evidence=language_evidence,
                    request="Bounded inference search did not establish a complete answer set.")
            if "missing_premise" in inference_failure_kinds:
                if missing_premises:
                    ordered_missing = [missing_premises[key]
                                       for key in sorted(missing_premises)[:6]]
                    supported: dict[tuple[str, str, str], None] = {}
                    for item in ordered_missing:
                        for premise in item.get("supported_premises", []):
                            key = (str(premise.get("subject", "?")),
                                   str(premise.get("relation", "?")),
                                   str(premise.get("object", "?")))
                            supported.setdefault(key, None)
                    known = "; ".join(
                        f"{subject} — {relation} → {object_}"
                        for subject, relation, object_ in list(supported)[:3])
                    lines = ([f"I have {known}."] if known else
                             ["A rule applies, but its proof is incomplete."])
                    lines.append("I still need:")
                    for item in ordered_missing:
                        missing = item.get("missing_premise", {})
                        lines.append(
                            f"  Rule {item.get('rule_id', '?')} needs premise "
                            f"{item.get('premise_index', '?')}: "
                            f"{missing.get('subject', '?')} — "
                            f"{missing.get('relation', '?')} → "
                            f"{missing.get('object', '?')}.")
                    lines.append("Tell me a missing fact or point me to a source.")
                else:
                    lines = [
                        "A rule could apply, but the facts do not establish "
                        "this answer or identify a specific missing link.",
                        "Add a relevant fact or point me to a source.",
                    ]
                return QuestionResult(
                    "unknown", matched_templates=templates,
                    language_evidence=language_evidence,
                    request="\n".join(lines),
                    reason_code="missing_premise",
                    missing_premises=[missing_premises[key]
                                      for key in sorted(missing_premises)[:6]])
            if inference_failure_kinds == {"no_applicable_rule"}:
                return QuestionResult(
                    "unknown", matched_templates=templates,
                    language_evidence=language_evidence,
                    request="No inference rule or derivation schema applies to this relation.",
                    reason_code="no_applicable_rule")
            if "rule_needs_review" in inference_failure_kinds:
                return QuestionResult(
                    "unknown", matched_templates=templates,
                    language_evidence=language_evidence,
                    request=(next(iter(inference_failure_requests), None)
                             or "A validated inference rule is suspended after "
                             "contradictory evidence. Review the rule and evidence "
                             "before using it."),
                    reason_code="rule_needs_review")
            return QuestionResult(
                "unknown", matched_templates=templates,
                language_evidence=language_evidence,
                request=("I recognize the taught question frame, but no matching "
                         "fact is stored for the requested entity or value."))
        evidence_output = [
            asdict(evidence_by_key[key])
            | ({"polarity": "positive"} if direct_negative_evidence else {})
            for key in sorted(evidence_by_key)]
        evidence_output.extend(inference_evidence[key]
                               for key in sorted(inference_evidence))
        evidence_output.extend(direct_negative_evidence[key]
                               for key in sorted(direct_negative_evidence))
        proof_by_key = {repr(proof): proof for proof in inference_proofs}
        inference_proofs = [proof_by_key[key] for key in sorted(proof_by_key)]
        candidates = [answers[key] for key in sorted(answers)]
        if direct_negative_evidence:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence_output,
                matched_templates=templates,
                inference_proofs=inference_proofs,
                language_evidence=language_evidence,
                request=("Positive and negative source-backed evidence conflict "
                         "for this answer."))
        if inference_conflict:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence_output,
                matched_templates=templates, inference_proofs=inference_proofs,
                language_evidence=language_evidence,
                request=("A possible inferred answer conflicts with explicit "
                         "negative evidence or a declared relation integrity "
                         "constraint."))
        if inference_incomplete:
            return QuestionResult(
                "unknown", evidence=evidence_output, matched_templates=templates,
                inference_proofs=inference_proofs,
                language_evidence=language_evidence,
                request="Bounded inference search did not establish a complete answer set.")
        if len(candidates) > 1:
            return QuestionResult("ambiguous", candidates=candidates,
                                  evidence=evidence_output,
                                  matched_templates=templates,
                                  inference_proofs=inference_proofs,
                                  language_evidence=language_evidence,
                                  request="Please provide evidence that distinguishes these answers.")
        return QuestionResult("answered", answer=candidates[0],
                              candidates=candidates, evidence=evidence_output,
                              matched_templates=templates,
                              inference_proofs=inference_proofs,
                              language_evidence=language_evidence)

    def _attach_query_alias_evidence(
            self, question: str, result: QuestionResult) -> QuestionResult:
        """Expose cited aliases used by specialized fact-question matchers."""
        if not self._entity_aliases or not result.matched_templates:
            return result
        words = _tokens(question)
        supported_entities: set[tuple[str, ...]] = set()
        for item in result.evidence or []:
            if isinstance(item, FactEvidence):
                supported_entities.update((_tokens(item.subject), _tokens(item.object)))
            elif isinstance(item, Mapping):
                for field in ("subject", "object"):
                    value = item.get(field)
                    if isinstance(value, str) and value:
                        supported_entities.add(_tokens(value))
        for proof in result.inference_proofs or []:
            for fact in self._inference_fact_leaves(proof):
                supported_entities.update((_tokens(fact["subject"]),
                                           _tokens(fact["object"])))
        evidence = {json.dumps(item, sort_keys=True, ensure_ascii=False): item
                    for item in result.language_evidence or []}
        for alias, record in self._entity_alias_records().items():
            entity = record["entity"]
            if (not alias or _tokens(entity) not in supported_entities
                    or not any(words[index:index + len(alias)] == alias
                               for index in range(len(words) - len(alias) + 1))):
                continue
            item = dict(record) | {"alias": " ".join(alias)}
            evidence[json.dumps(item, sort_keys=True, ensure_ascii=False)] = item
        result.language_evidence = [evidence[key] for key in sorted(evidence)] or None
        return result

    def teach_path_question(self, question: str, *, relations: Iterable[str],
                            bound_entity: str, answer: str) -> bool:
        """Ground a question frame to a verified forward relation path."""
        question = _display(question, "question")
        bound_entity = _display(bound_entity, "bound_entity")
        answer = _display(answer, "answer")
        path = tuple(_tokens(_display(relation, "relation"))
                     for relation in relations)
        if not path or len(path) > 3 or any(not relation for relation in path):
            raise ValueError("relation path must contain one to three non-empty edges")
        result = self.ask_path(bound_entity, [" ".join(relation) for relation in path])
        if (result.status != "answered"
                or _tokens(result.answer or "") != _tokens(answer)):
            raise ValueError("question example is not supported by one unique fact path")

        words = _path_question_tokens(question)
        entity_words = _tokens(bound_entity)
        positions = [index for index in range(len(words) - len(entity_words) + 1)
                     if words[index:index + len(entity_words)] == entity_words]
        if len(positions) != 1:
            raise ValueError("bound entity must occur exactly once in the question")
        start = positions[0]
        end = start + len(entity_words)
        key = (path, words[:start], words[end:])
        entities = self._path_question_examples.setdefault(key, set())
        entities.add(entity_words)
        return self._path_question_frame_is_licensed(key, entities)

    def _path_question_frame_is_licensed(
            self, key: tuple[tuple[tuple[str, ...], ...],
                            tuple[str, ...], tuple[str, ...]],
            entities: set[tuple[str, ...]]) -> bool:
        """Check exact path-frame evidence or same-path wording transfer."""
        if len(entities) >= 2:
            return True
        if len(entities) != 1:
            return False
        relations, _prefix, _suffix = key
        return any(other_relations == relations and len(other_entities) >= 2
                   and (other_relations, other_prefix, other_suffix) != key
                   for (other_relations, other_prefix, other_suffix),
                   other_entities in self._path_question_examples.items())

    def ask_path_question(self, question: str, *,
                          qualifiers: Mapping[str, str] | None = None
                          ) -> QuestionResult:
        """Resolve a learned frame, then execute its grounded relation path."""
        words = _path_question_tokens(_display(question, "question"))
        results: list[tuple[QuestionResult, str]] = []
        for (relations, prefix, suffix), entities in self._path_question_examples.items():
            key = (relations, prefix, suffix)
            if (not self._path_question_frame_is_licensed(key, entities)
                    or len(words) <= len(prefix) + len(suffix)):
                continue
            if words[:len(prefix)] != prefix:
                continue
            if suffix and words[-len(suffix):] != suffix:
                continue
            end = len(words) - len(suffix) if suffix else len(words)
            bound_words = words[len(prefix):end]
            if not bound_words:
                continue
            start = " ".join(bound_words)
            relation_path = [" ".join(relation) for relation in relations]
            template = " ".join(prefix + ("{subject}",) + suffix)
            results.append((self.ask_path(start, relation_path,
                                          qualifiers=qualifiers), template))

        if not results:
            return QuestionResult("unknown")
        templates = sorted({template for _, template in results})
        answers: dict[tuple[str, ...], str] = {}
        evidence_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        proofs_by_key: dict[tuple, list[dict[str, Any]]] = {}
        recognized = False
        for result, _template in results:
            recognized = True
            for candidate in result.candidates or []:
                answers.setdefault(_tokens(candidate), candidate)
            for fact in result.evidence or []:
                key = (fact["subject"], fact["relation"], fact["object"],
                       tuple(tuple(pair) for pair in fact.get("qualifiers", [])))
                evidence_by_key[key] = fact
            for proof in result.proofs or []:
                key = tuple((fact["subject"], fact["relation"], fact["object"],
                             tuple(tuple(pair) for pair in fact.get("qualifiers", [])))
                            for fact in proof)
                proofs_by_key[key] = proof

        if not recognized or not answers:
            return QuestionResult(
                "unknown", matched_templates=templates,
                request="The question frame is grounded, but no matching fact path is stored.")
        candidates = [answers[key] for key in sorted(answers)]
        evidence = [evidence_by_key[key] for key in sorted(evidence_by_key)]
        proofs = [proofs_by_key[key] for key in sorted(proofs_by_key)]
        if len(candidates) > 1:
            return QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=templates, proofs=proofs,
                request="The grounded question reaches multiple answers; provide a distinguishing constraint.")
        return QuestionResult(
            "answered", answer=candidates[0], candidates=candidates,
            evidence=evidence, matched_templates=templates, proofs=proofs)

    def teach_counterfactual_path_question(
            self, question: str, *, start: str, target: str,
            relations: Iterable[str], source: str,
            qualifiers: Mapping[str, str] | None = None) -> bool:
        """Learn a grounded frame with variable start, target, and source.

        Relation sequence and qualifier values remain fixed. Every example
        must prove the named path and cite the named source; licensing requires
        distinct examples that vary all three bound roles.
        """
        question = _display(question, "question")
        start = self._canonicalize_entity(_display(start, "start"))
        target = self._canonicalize_entity(_display(target, "target"))
        source = _display(source, "source")
        path = tuple(_tokens(_display(relation, "relation"))
                     for relation in relations)
        if not path or len(path) > 3 or any(not relation for relation in path):
            raise ValueError("relation path must contain one to three non-empty edges")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        qualifier_key = tuple((_tokens(name), _tokens(value))
                              for name, value in normalized_qualifiers)
        baseline = self.ask_path_between(
            start, target, [" ".join(relation) for relation in path],
            qualifiers=dict(normalized_qualifiers))
        cited = {label for proof in baseline.proofs or [] for step in proof
                 for label in step.get("sources", [])}
        if baseline.status != "answered" or source not in cited:
            raise ValueError("example must name a source cited by a proven path")

        words = _tokens(question)
        spans: list[tuple[int, int, str]] = []
        for role, value in (("start", start), ("target", target),
                            ("source", source)):
            phrase = _tokens(value)
            positions = [index for index in range(len(words) - len(phrase) + 1)
                         if phrase and words[index:index + len(phrase)] == phrase]
            if len(positions) != 1:
                raise ValueError(f"{role} must occur exactly once in the question")
            spans.append((positions[0], positions[0] + len(phrase), role))
        ordered_spans = sorted(spans)
        if any(left[1] > right[0]
               for left, right in zip(ordered_spans, ordered_spans[1:])):
            raise ValueError("start, target, and source spans may not overlap")
        template: list[str] = []
        cursor = 0
        for begin, end, role in ordered_spans:
            template.extend(words[cursor:begin])
            template.append("\x00" + role)
            cursor = end
        template.extend(words[cursor:])
        key = (tuple(template), path, qualifier_key)
        example_key = (_tokens(start), _tokens(target), _tokens(source))
        examples = self._counterfactual_path_examples.setdefault(key, {})
        examples[example_key] = (start, target, source)
        start_values = {example[0] for example in examples}
        target_values = {example[1] for example in examples}
        source_values = {example[2] for example in examples}
        return (len(examples) >= 2 and len(start_values) >= 2
                and len(target_values) >= 2 and len(source_values) >= 2)

    def ask_counterfactual_path_question(
            self, question: str) -> CounterfactualResult | None:
        """Execute a learned three-slot source-counterfactual frame."""
        words = _tokens(_display(question, "question"))
        recognized = False
        evaluated: dict[tuple[Any, ...], CounterfactualResult] = {}
        baseline_failures: list[QuestionResult] = []
        for (template, relation_tokens, qualifier_key), examples in \
                self._counterfactual_path_examples.items():
            role_examples = list(examples)
            licensed = (len(role_examples) >= 2
                        and len({row[0] for row in role_examples}) >= 2
                        and len({row[1] for row in role_examples}) >= 2
                        and len({row[2] for row in role_examples}) >= 2)
            if not licensed:
                continue
            parses = _match_counterfactual_template(template, words)
            if not parses:
                continue
            recognized = True
            if len(parses) >= 3:
                ambiguous = QuestionResult(
                    "ambiguous", request="The wording has several possible role bindings.")
                return CounterfactualResult("ambiguous_frame", None, ambiguous,
                                            None, None)
            slot_order = [_COUNTERFACTUAL_SLOTS[token] for token in template
                          if token in _COUNTERFACTUAL_SLOTS]
            qualifiers = {" ".join(name): " ".join(value)
                          for name, value in qualifier_key}
            for captures in parses:
                bound = dict(zip(slot_order, captures))
                if set(bound) != {"start", "target", "source"}:
                    continue
                start = self._entity_display_for_tokens(bound["start"])
                target = self._entity_display_for_tokens(bound["target"])
                relation_path = [" ".join(relation)
                                 for relation in relation_tokens]
                baseline = self.ask_path_between(
                    start, target, relation_path, qualifiers=qualifiers)
                if baseline.status != "answered":
                    baseline_failures.append(baseline)
                    continue
                source_words = bound["source"]
                sources = {
                    label for fact in self.facts() + self.negative_facts()
                    for label in fact.sources if _tokens(label) == source_words
                }
                if len(sources) > 1:
                    result = CounterfactualResult(
                        "ambiguous_source", None, baseline, None, None,
                        " ".join(source_words))
                else:
                    source = next(iter(sources), " ".join(source_words))
                    result = self.counterfactual_path_without_source(
                        start, target, relation_path, source=source,
                        qualifiers=qualifiers)
                signature = (bound["start"], bound["target"], source_words,
                             relation_tokens, qualifier_key)
                evaluated[signature] = result

        if not recognized:
            return None
        if len(evaluated) == 1:
            return next(iter(evaluated.values()))
        if len(evaluated) > 1:
            ambiguous = QuestionResult(
                "ambiguous", request="The wording has multiple grounded path bindings.")
            return CounterfactualResult("ambiguous_frame", None, ambiguous,
                                        None, None)
        baseline = (baseline_failures[0] if baseline_failures else
                    QuestionResult("unknown", request="No unique grounded path binding was found."))
        return CounterfactualResult(
            "baseline_not_proven", None, baseline, None, None)

    def teach_counterfactual_source_question(
            self, question: str, *, start: str, target: str,
            relations: Iterable[str], source: str,
            qualifiers: Mapping[str, str] | None = None) -> bool:
        """Learn an exact question frame with one variable citation slot.

        Two distinct cited sources must occur in questions with the same
        literal prefix and suffix and refer to the same grounded path.
        """
        question = _display(question, "question")
        start = self._canonicalize_entity(_display(start, "start"))
        target = self._canonicalize_entity(_display(target, "target"))
        source = _display(source, "source")
        path = tuple(_tokens(_display(relation, "relation"))
                     for relation in relations)
        if not path or len(path) > 3 or any(not relation for relation in path):
            raise ValueError("relation path must contain one to three non-empty edges")
        normalized_qualifiers = self._normalize_qualifiers(qualifiers)
        qualifier_key = tuple((_tokens(name), _tokens(value))
                              for name, value in normalized_qualifiers)
        baseline = self.ask_path_between(
            start, target, [" ".join(relation) for relation in path],
            qualifiers=dict(normalized_qualifiers))
        cited = {label for proof in baseline.proofs or [] for step in proof
                 for label in step.get("sources", [])}
        if baseline.status != "answered" or source not in cited:
            raise ValueError("example must name a source cited by a proven path")

        words = _tokens(question)
        source_words = _tokens(source)
        positions = [index for index in range(len(words) - len(source_words) + 1)
                     if source_words and words[index:index + len(source_words)] == source_words]
        if len(positions) != 1:
            raise ValueError("source must occur exactly once in the question")
        slot = positions[0]
        key = (_tokens(start), _tokens(target), path, qualifier_key,
               words[:slot], words[slot + len(source_words):])
        examples = self._counterfactual_source_examples.setdefault(key, {})
        old = examples.get(source_words)
        if old is not None and old != source:
            raise ValueError("source wording has conflicting canonical citations")
        examples[source_words] = source
        return len(examples) >= 2

    def ask_counterfactual_source_question(
            self, question: str) -> CounterfactualResult | None:
        """Resolve either learned source-only or multi-role question frames."""
        path_frame = self.ask_counterfactual_path_question(question)
        source_frame = self._ask_counterfactual_fixed_source_question(question)
        if path_frame is not None and source_frame is not None:
            ambiguous = QuestionResult(
                "ambiguous", request="The request matches multiple learned counterfactual frames.")
            return CounterfactualResult("ambiguous_frame", None, ambiguous,
                                        None, None)
        return path_frame if path_frame is not None else source_frame

    def _ask_counterfactual_fixed_source_question(
            self, question: str) -> CounterfactualResult | None:
        """Execute a licensed source-counterfactual frame, if one matches."""
        words = _tokens(_display(question, "question"))
        matches: list[tuple[tuple[Any, ...], tuple[str, ...]]] = []
        for key, examples in self._counterfactual_source_examples.items():
            _start, _target, _relations, _qualifiers, prefix, suffix = key
            if len(examples) < 2 or len(words) <= len(prefix) + len(suffix):
                continue
            if words[:len(prefix)] != prefix:
                continue
            if suffix and words[-len(suffix):] != suffix:
                continue
            end = len(words) - len(suffix) if suffix else len(words)
            source_words = words[len(prefix):end]
            if source_words:
                matches.append((key, source_words))
        if not matches:
            return None
        if len(matches) > 1:
            ambiguous = QuestionResult(
                "ambiguous", request="The request matches multiple learned counterfactual frames.")
            return CounterfactualResult("ambiguous_frame", None, ambiguous,
                                        None, None)

        key, source_words = matches[0]
        (start_tokens, target_tokens, relation_tokens, qualifier_key,
         _prefix, _suffix) = key
        start = self._entity_display_for_tokens(start_tokens)
        target = self._entity_display_for_tokens(target_tokens)
        relation_path = [" ".join(relation) for relation in relation_tokens]
        qualifiers = {" ".join(name): " ".join(value)
                      for name, value in qualifier_key}
        baseline = self.ask_path_between(
            start, target, relation_path, qualifiers=qualifiers)
        if baseline.status != "answered":
            return CounterfactualResult(
                "baseline_not_proven", None, baseline, None, None,
                " ".join(source_words))

        available_sources = {
            label for fact in self.facts() + self.negative_facts()
            for label in fact.sources if _tokens(label) == source_words
        }
        if len(available_sources) > 1:
            return CounterfactualResult(
                "ambiguous_source", None, baseline, None, None,
                " ".join(source_words))
        source = next(iter(available_sources), " ".join(source_words))
        return self.counterfactual_path_without_source(
            start, target, relation_path, source=source,
            qualifiers=qualifiers)

    def _entity_display_for_tokens(self, tokens: tuple[str, ...]) -> str:
        displays = {
            value for fact in self.facts() + self.negative_facts()
            for value in (fact.subject, fact.object)
            if _tokens(self._canonicalize_entity(value)) == tokens
        }
        if len(displays) == 1:
            return next(iter(displays))
        return self._canonicalize_entity(" ".join(tokens))

    def render_counterfactual(self, result: CounterfactualResult) -> str:
        """Render a bounded path counterfactual with its evidence response."""
        source = result.excluded_source
        if result.status == "supported":
            text = f"The path remains supported without source {source}."
        elif result.status == "unsupported":
            text = f"The path is no longer supported without source {source}."
        elif result.status == "ambiguous":
            text = f"The path is ambiguous without source {source}."
        elif result.status == "source_not_in_proof":
            text = f"Source {source} does not support the baseline proof."
        elif result.status == "ambiguous_source":
            text = f"The source name {source} matches multiple stored citations."
        elif result.status == "ambiguous_frame":
            return "This request matches multiple learned counterfactual frames; please rephrase it."
        else:
            text = "The baseline path is not proven, so no source counterfactual was run."
        if result.counterfactual is not None:
            text += "\n" + self.render(result.counterfactual)
        elif result.baseline.status != "answered":
            text += "\n" + self.render(result.baseline)
        return text

    def respond(self, question: str, *,
                qualifiers: Mapping[str, str] | None = None
                ) -> tuple[QuestionResult, str]:
        """Answer a learned question frame with controlled, evidence-aware text."""
        result = self.ask(question, qualifiers=qualifiers)
        return result, self.render(result)

    @staticmethod
    def render(result: QuestionResult) -> str:
        """Realize a result with fixed templates; never invent missing content."""
        if result.status == "answered":
            text = f"Answer: {result.answer}."
        elif result.status == "ambiguous":
            if result.candidates:
                options = "; ".join(result.candidates)
                text = f"I found multiple supported answers: {options}."
            else:
                text = "The available evidence conflicts."
        else:
            text = "I don't have a grounded answer for that yet."

        if result.matched_templates:
            text += "\nMatched question frame: " + "; ".join(
                result.matched_templates) + "."
        if result.status == "answered" and result.complete is False and result.request:
            text += "\n" + result.request

        for item in result.language_evidence or []:
            if item.get("kind") == "entity_alias":
                text += (f"\nEntity alias: {item['alias']} → {item['entity']} "
                         f"(sources: {', '.join(item.get('sources', []))}).")
                continue
            if item.get("kind") == "induced_entity_plural":
                support = "; ".join(
                    f"{entry['entity']} → {', '.join(entry['surface_forms'])} "
                    f"[sources: {', '.join(entry['sources'])}]"
                    for entry in item.get("support", []))
                roles = ", ".join(
                    f"{role['relation']} {role['role']}"
                    for role in item.get("shared_roles", []))
                role_sources = ", ".join(item.get("target_role_sources", []))
                text += (f"\nPlural form: {item['alias']} → {item['entity']} "
                         f"(context {item['context']}; role {roles} "
                         f"[target evidence: {role_sources}]; "
                         f"supported by {support}).")
                continue
            if item.get("kind") == "induced_question_frame":
                lineage = item.get("lineage", {})
                train_sources = ", ".join(
                    lineage.get("training_source_documents", []))
                holdout_sources = ", ".join(
                    lineage.get("holdout_source_documents", []))
                text += (f"\nInduced question frame: {item['base_relation']} → "
                         f"{item['target_relation']} (artifact {item['artifact_id']}; "
                         f"training sources: {train_sources}; held-out sources: "
                         f"{holdout_sources}).")
                continue
            if item.get("kind") == "induced_qualified_question_frame":
                train_sources = ", ".join(
                    item.get("training_source_documents", []))
                holdout_sources = ", ".join(
                    item.get("holdout_source_documents", []))
                text += (f"\nInduced qualified question frame: "
                         f"{item['base_relation']} → {item['target_relation']} "
                         f"(context {item['qualifier_name']}; artifact "
                         f"{item['artifact_id']}; training sources: "
                         f"{train_sources}; held-out sources: {holdout_sources}).")
                continue
            if item.get("kind") == "induced_multi_qualified_question_frame":
                train_sources = ", ".join(
                    item.get("training_source_documents", []))
                holdout_sources = ", ".join(
                    item.get("holdout_source_documents", []))
                qualifiers = ", ".join(item.get("qualifier_names", []))
                text += (f"\nInduced multi-context question frame: "
                         f"{item['base_relation']} → {item['target_relation']} "
                         f"(contexts {qualifiers}; artifact {item['artifact_id']}; "
                         f"training sources: {train_sources}; held-out sources: "
                         f"{holdout_sources}).")
                continue
            if item.get("kind") in {"optional_question_word",
                                     "optional_question_phrase"}:
                examples = "; ".join(
                    f"{entry['bound_entity']} → {entry['answer']} "
                    f"[sources: {', '.join(entry['sources'])}]"
                    for entry in item.get("support", []))
                frames = " / ".join(item.get("equivalent_frames", []))
                unit = ("word" if item.get("kind") == "optional_question_word"
                        else "phrase")
                text += (f"\nLearned optional question {unit}: "
                         f"'{item['word']}' "
                         f"(frames {frames}; aligned fact-backed examples: "
                         f"{examples}).")
                continue
            if item.get("kind") in {"typed_subject_question",
                                     "subject_question"}:
                type_text = (f"{item['type']} "
                             if item.get("type") else "")
                text += (f"\nMatched source-grounded question: "
                         f"{item.get('wh', 'which')} {type_text}"
                         f"{item['predicate']} (relation: "
                         f"{item['relation']}).")
                continue
            if item.get("kind") in {
                    "source_licensed_polar_question",
                    "stored_relation_polar_question"}:
                wording_label = ("stored-relation" if item.get("kind")
                                 == "stored_relation_polar_question" else
                                 "source-licensed")
                text += (f"\nMatched {wording_label} yes/no wording: "
                         f"{item['grammar']} "
                         f"(predicate: {item['predicate']}; "
                         f"relation: {item['relation']}).")
                continue
            if item.get("kind") == "source_licensed_object_wh_question":
                text += (f"\nMatched source-licensed object question: "
                         f"{item['grammar']} "
                         f"(predicate: {item['predicate']}; "
                         f"relation: {item['relation']}).")
                continue
            if item.get("kind") == "stored_relation_subject_question":
                text += (f"\nMatched stored-relation subject question: "
                         f"{item['grammar']} "
                         f"(predicate: {item['predicate']}; "
                         f"relation: {item['relation']}).")
                continue
            support = "; ".join(
                f"{entry['relation']} → {', '.join(entry['surface_forms'])} "
                f"[sources: {', '.join(entry['sources'])}]"
                for entry in item.get("support", []))
            if item.get("kind") == "observed_predicate_form":
                text += (f"\nObserved predicate form: {item['canonical_form']} → "
                         f"{item['surface_form']} (grounded by {support}).")
            else:
                text += (f"\nLanguage rule: {item['canonical_form']} → "
                         f"{item['surface_form']} (context {item['context']}, "
                         f"supported by {support}).")
        if result.proofs:
            proof_lines = []
            for index, proof in enumerate(result.proofs, start=1):
                steps = []
                for fact in proof:
                    sources = ", ".join(fact["sources"])
                    context = ("; context: " + ", ".join(
                        f"{name}={value}" for name, value in fact.get("qualifiers", []))
                        if fact.get("qualifiers") else "")
                    steps.append(
                        f'{fact["subject"]} — {fact["relation"]} → '
                        f'{fact["object"]}{context} [sources: {sources}]')
                proof_lines.append(f"Proof {index}: " + "; then ".join(steps) + ".")
            text += "\n" + "\n".join(proof_lines)
        if result.inference_proofs:
            for index, proof in enumerate(result.inference_proofs, start=1):
                text += (f"\nRule proof {index}: "
                         f"{CRMSKnowledgeBase._render_inference_step(proof)}.")
        else:
            sources = sorted({source for fact in result.evidence or []
                              for source in (list(fact.get("sources", []))
                                             + list(fact.get("contradictory_sources", [])))})
            if sources:
                text += "\nSources: " + "; ".join(sources) + "."
            contexts = sorted({tuple(tuple(pair) for pair in fact.get("qualifiers", []))
                               for fact in result.evidence or []
                               if fact.get("qualifiers")})
            if contexts:
                rendered_contexts = [", ".join(f"{name}={value}" for name, value in context)
                                     for context in contexts]
                text += "\nRecorded context: " + "; or ".join(rendered_contexts) + "."
        return text

    def ask_path(self, start: str, relations: Iterable[str], *,
                 qualifiers: Mapping[str, str] | None = None) -> QuestionResult:
        """Follow an explicit forward relation path of at most three edges.

        This is bounded symbolic composition, not open-ended path search. Every
        returned answer includes at least one complete fact proof.
        """
        start_query = _display(start, "start")
        start = self._canonicalize_query_entity(start_query)
        path = tuple(_display(relation, "relation") for relation in relations)
        if not path or len(path) > 3:
            raise ValueError("relation path must contain one to three edges")
        requested_qualifiers = self._normalize_qualifiers(qualifiers)

        frontier: list[tuple[str, tuple[FactEvidence, ...]]] = [(start, ())]
        for relation in path:
            relation_key = _tokens(relation)
            next_frontier = []
            for current, proof in frontier:
                current_key = _tokens(self._canonicalize_entity(current))
                for fact in self._facts.values():
                    if (_tokens(self._canonicalize_entity(fact.subject)) == current_key
                            and _tokens(fact.relation) == relation_key
                            and self._has_qualifiers(fact, requested_qualifiers)):
                        next_frontier.append((fact.object, proof + (fact,)))
            frontier = next_frontier
            if not frontier:
                break

        if not frontier:
            return QuestionResult(
                "unknown", request="No complete fact path matches the requested relations.",
                matched_templates=["path: " + " -> ".join(path)],
                complete=True, reason_code="no_path")

        answer_by_key: dict[tuple[str, ...], str] = {}
        proof_by_key: dict[tuple[str, ...], list[tuple[FactEvidence, ...]]] = {}
        for answer, proof in frontier:
            key = _tokens(answer)
            answer_by_key.setdefault(key, answer)
            proof_by_key.setdefault(key, []).append(proof)
        candidates = [answer_by_key[key] for key in sorted(answer_by_key)]
        proofs = [
            [asdict(fact) for fact in proof]
            for key in sorted(proof_by_key)
            for proof in sorted(proof_by_key[key], key=lambda row: tuple(
                (fact.subject, fact.relation, fact.object) for fact in row))
        ]
        evidence_by_key = {
            (fact.subject, fact.relation, fact.object, fact.qualifiers): fact
            for proof in proof_by_key.values() for row in proof for fact in row
        }
        evidence = [asdict(evidence_by_key[key])
                    for key in sorted(evidence_by_key)]
        if len(candidates) > 1:
            return self._attach_query_alias_evidence(
                start_query, QuestionResult(
                "ambiguous", candidates=candidates, evidence=evidence,
                matched_templates=["path: " + " -> ".join(path)], proofs=proofs,
                request="The grounded path reaches multiple answers; provide a distinguishing constraint.",
                complete=True, reason_code="multiple_answers"))
        return self._attach_query_alias_evidence(
            start_query, QuestionResult(
            "answered", answer=candidates[0], candidates=candidates,
            evidence=evidence, matched_templates=["path: " + " -> ".join(path)],
            proofs=proofs, complete=True, reason_code="supported"))

    def ask_path_between(self, start: str, target: str,
                         relations: Iterable[str], *,
                         qualifiers: Mapping[str, str] | None = None,
                         max_expansions: int = 10_000) -> QuestionResult:
        """Check a bounded relation path between two specified entities.

        Search proceeds from both endpoints and joins at the middle entity. A
        successful result is a proof-backed ``yes``; no path or expansion-limit
        exhaustion returns ``unknown``. This is graph-path lookup over explicit
        facts, not inference over learned rules.
        """
        start_query = _display(start, "start")
        target_query = _display(target, "target")
        start = self._canonicalize_query_entity(start_query)
        target = self._canonicalize_query_entity(target_query)
        path = tuple(_display(relation, "relation") for relation in relations)
        if not path or len(path) > 3:
            raise ValueError("relation path must contain one to three edges")
        if (not isinstance(max_expansions, int) or isinstance(max_expansions, bool)
                or max_expansions < 1):
            raise ValueError("max_expansions must be a positive integer")
        requested_qualifiers = self._normalize_qualifiers(qualifiers)

        # Index both directions so each frontier visits only facts that extend
        # that side of the requested path.
        outgoing: dict[tuple[tuple[str, ...], tuple[str, ...]], list[FactEvidence]] = {}
        incoming: dict[tuple[tuple[str, ...], tuple[str, ...]], list[FactEvidence]] = {}
        for fact in self._facts.values():
            relation_key = _tokens(fact.relation)
            start_key = _tokens(self._canonicalize_entity(fact.subject))
            end_key = _tokens(self._canonicalize_entity(fact.object))
            outgoing.setdefault((start_key, relation_key), []).append(fact)
            incoming.setdefault((end_key, relation_key), []).append(fact)

        split = len(path) // 2
        expanded = 0
        forward: list[tuple[str, tuple[FactEvidence, ...]]] = [(start, ())]
        for relation in path[:split]:
            relation_key = _tokens(relation)
            next_frontier: list[tuple[str, tuple[FactEvidence, ...]]] = []
            for current, proof in forward:
                current_key = _tokens(self._canonicalize_entity(current))
                for fact in outgoing.get((current_key, relation_key), ()):
                    if not self._has_qualifiers(fact, requested_qualifiers):
                        continue
                    if expanded >= max_expansions:
                        return QuestionResult(
                            "unknown",
                            request="Path search reached its expansion limit; no conclusion was drawn.",
                            matched_templates=["path: " + " -> ".join(path)],
                            complete=False, reason_code="search_limit",
                            expansions=expanded)
                    expanded += 1
                    next_frontier.append((fact.object, proof + (fact,)))
            forward = next_frontier
            if not forward:
                return QuestionResult(
                    "unknown", request="No complete fact path matches the requested relations.",
                    matched_templates=["path: " + " -> ".join(path)],
                    complete=True, reason_code="no_path", expansions=expanded)

        backward: list[tuple[str, tuple[FactEvidence, ...]]] = [(target, ())]
        for relation in reversed(path[split:]):
            relation_key = _tokens(relation)
            next_frontier = []
            for current, reverse_proof in backward:
                current_key = _tokens(self._canonicalize_entity(current))
                for fact in incoming.get((current_key, relation_key), ()):
                    if not self._has_qualifiers(fact, requested_qualifiers):
                        continue
                    if expanded >= max_expansions:
                        return QuestionResult(
                            "unknown",
                            request="Path search reached its expansion limit; no conclusion was drawn.",
                            matched_templates=["path: " + " -> ".join(path)],
                            complete=False, reason_code="search_limit",
                            expansions=expanded)
                    expanded += 1
                    next_frontier.append((fact.subject, reverse_proof + (fact,)))
            backward = next_frontier
            if not backward:
                return QuestionResult(
                    "unknown", request="No complete fact path matches the requested relations.",
                    matched_templates=["path: " + " -> ".join(path)],
                    complete=True, reason_code="no_path", expansions=expanded)

        backward_by_entity: dict[tuple[str, ...], list[tuple[FactEvidence, ...]]] = {}
        for entity, reverse_proof in backward:
            backward_by_entity.setdefault(
                _tokens(self._canonicalize_entity(entity)), []).append(reverse_proof)
        complete = [forward_proof + tuple(reversed(reverse_proof))
                    for entity, forward_proof in forward
                    for reverse_proof in backward_by_entity.get(
                        _tokens(self._canonicalize_entity(entity)), ())]
        if not complete:
            return QuestionResult(
                "unknown", request="No complete fact path matches the requested endpoints.",
                matched_templates=["path: " + " -> ".join(path)],
                complete=True, reason_code="no_path", expansions=expanded)

        complete.sort(key=lambda row: tuple(
            (fact.subject, fact.relation, fact.object, fact.sources) for fact in row))
        negative_by_triple: dict[tuple[Any, ...], list[FactEvidence]] = {}
        for negative in self._negative_facts.values():
            key = self._fact_key(negative.subject, negative.relation,
                                 negative.object)
            negative_by_triple.setdefault(key, []).append(negative)
        conflicts: dict[tuple[Any, ...], dict[str, Any]] = {}
        for proof in complete:
            for fact in proof:
                key = self._fact_key(fact.subject, fact.relation, fact.object)
                contradictory = [negative for negative in negative_by_triple.get(key, ())
                                 if self._has_qualifiers(negative, requested_qualifiers)]
                if contradictory:
                    evidence_key = (fact.subject, fact.relation,
                                    fact.object, fact.qualifiers)
                    conflicts[evidence_key] = asdict(fact) | {
                        "contradictory_sources": sorted({
                            source for negative in contradictory
                            for source in negative.sources})}
        if conflicts:
            return self._attach_query_alias_evidence(
                f"{start_query} {target_query}", QuestionResult(
                "ambiguous", evidence=[conflicts[key] for key in sorted(conflicts)],
                matched_templates=["path: " + " -> ".join(path)],
                request="Positive and negative fact sources conflict on a path edge.",
                complete=True, reason_code="contradiction", expansions=expanded))

        proofs = [[asdict(fact) for fact in proof] for proof in complete]
        evidence_by_key = {
            (fact.subject, fact.relation, fact.object, fact.qualifiers): fact
            for proof in complete for fact in proof
        }
        evidence = [asdict(evidence_by_key[key]) for key in sorted(evidence_by_key)]
        return self._attach_query_alias_evidence(
            f"{start_query} {target_query}", QuestionResult(
            "answered", answer="yes", candidates=["yes"], evidence=evidence,
            matched_templates=["path: " + " -> ".join(path)], proofs=proofs,
            truth=True, complete=True, reason_code="supported", expansions=expanded))

    def counterfactual_path_between(
            self, start: str, target: str, relations: Iterable[str], *,
            excluded_fact: FactEvidence | Mapping[str, Any],
            qualifiers: Mapping[str, str] | None = None,
            max_expansions: int = 10_000) -> CounterfactualResult:
        """Rerun a proven path query with one cited fact excluded read-only.

        The exclusion removes one stored fact proposition and its aggregated
        source set from a shallow, temporary knowledge-base view. The original
        knowledge base and its persistence state are never modified.
        """
        if isinstance(excluded_fact, FactEvidence):
            fields: Mapping[str, Any] = asdict(excluded_fact)
        elif isinstance(excluded_fact, Mapping):
            fields = excluded_fact
        else:
            raise TypeError("excluded_fact must be a fact record")
        relation_path = tuple(relations)
        try:
            fact_subject = self._canonicalize_entity(
                _display(fields["subject"], "excluded fact subject"))
            fact_relation = _display(fields["relation"], "excluded fact relation")
            fact_object = self._canonicalize_entity(
                _display(fields["object"], "excluded fact object"))
            raw_qualifiers = fields.get("qualifiers", ())
            normalized_qualifiers = self._normalize_qualifiers(dict(raw_qualifiers))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("excluded_fact must include subject, relation, object, and qualifiers") from error
        excluded_key = self._fact_key(
            fact_subject, fact_relation, fact_object, normalized_qualifiers)
        stored_fact = self._facts.get(excluded_key)
        if stored_fact is None:
            raise ValueError("excluded_fact is not present in the positive fact store")

        baseline = self.ask_path_between(
            start, target, relation_path, qualifiers=qualifiers,
            max_expansions=max_expansions)
        if baseline.status != "answered" or not baseline.proofs:
            return CounterfactualResult(
                "baseline_not_proven", None, baseline, None, asdict(stored_fact))

        def proof_key(step: Mapping[str, Any]) -> tuple[Any, ...]:
            step_qualifiers = self._normalize_qualifiers(
                dict(step.get("qualifiers", ())))
            return self._fact_key(
                self._canonicalize_entity(step["subject"]), step["relation"],
                self._canonicalize_entity(step["object"]), step_qualifiers)

        if not any(proof_key(step) == excluded_key
                   for proof in baseline.proofs for step in proof):
            return CounterfactualResult(
                "fact_not_in_proof", None, baseline, None, asdict(stored_fact))

        temporary_view = copy.copy(self)
        temporary_view._facts = {
            key: fact for key, fact in self._facts.items()
            if key != excluded_key
        }
        temporary_view._rebuild_fact_indexes()
        counterfactual = temporary_view.ask_path_between(
            start, target, relation_path, qualifiers=qualifiers,
            max_expansions=max_expansions)
        if counterfactual.status == "answered" and counterfactual.truth is True:
            return CounterfactualResult(
                "supported", True, baseline, counterfactual, asdict(stored_fact))
        if counterfactual.status == "ambiguous":
            return CounterfactualResult(
                "ambiguous", None, baseline, counterfactual, asdict(stored_fact))
        return CounterfactualResult(
            "unsupported", False, baseline, counterfactual, asdict(stored_fact))

    def counterfactual_path_without_source(
            self, start: str, target: str, relations: Iterable[str], *,
            source: str, qualifiers: Mapping[str, str] | None = None,
            max_expansions: int = 10_000) -> CounterfactualResult:
        """Rerun a proven path query after removing one citation everywhere.

        The named source is removed from positive and negative stored facts in
        a temporary view. A proposition remains supported when it has another
        source; records with no remaining sources are omitted. Source documents
        and the original knowledge base are not modified.
        """
        source = _display(source, "source")
        relation_path = tuple(relations)
        baseline = self.ask_path_between(
            start, target, relation_path, qualifiers=qualifiers,
            max_expansions=max_expansions)
        if baseline.status != "answered" or not baseline.proofs:
            return CounterfactualResult(
                "baseline_not_proven", None, baseline, None, None, source)
        cited_sources = {
            label for proof in baseline.proofs for step in proof
            for label in step.get("sources", [])
        }
        if source not in cited_sources:
            return CounterfactualResult(
                "source_not_in_proof", None, baseline, None, None, source)

        temporary_view = copy.copy(self)

        def without_citation(store: Mapping[tuple[Any, ...], FactEvidence]
                             ) -> dict[tuple[Any, ...], FactEvidence]:
            result = {}
            for key, fact in store.items():
                remaining = tuple(label for label in fact.sources if label != source)
                if remaining:
                    result[key] = (fact if remaining == fact.sources
                                   else replace(fact, sources=remaining))
            return result

        temporary_view._facts = without_citation(self._facts)
        temporary_view._negative_facts = without_citation(self._negative_facts)
        temporary_view._rebuild_fact_indexes()
        counterfactual = temporary_view.ask_path_between(
            start, target, relation_path, qualifiers=qualifiers,
            max_expansions=max_expansions)
        if counterfactual.status == "answered" and counterfactual.truth is True:
            return CounterfactualResult(
                "supported", True, baseline, counterfactual, None, source)
        if counterfactual.status == "ambiguous":
            return CounterfactualResult(
                "ambiguous", None, baseline, counterfactual, None, source)
        return CounterfactualResult(
            "unsupported", False, baseline, counterfactual, None, source)

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        payload = {
            "format_version": self.FORMAT_VERSION,
            "max_derived_cases": self.max_derived_cases,
            "inference_rules": [
                asdict(rule) | ({"validation": self._inference_rule_validation[key]}
                                if key in self._inference_rule_validation else {})
                for key, rule in sorted(self._inference_rules.items())
            ],
            "derived_cases": [copy.deepcopy(case) for _, case
                              in sorted(self._derived_cases.items())],
            "entity_aliases": [
                {"alias": list(alias), "entity": entity,
                 "sources": sorted(sources)}
                for alias, (entity, sources) in sorted(self._entity_aliases.items())
            ],
            "entity_alias_explicit_sources": [
                {"alias": list(alias), "sources": sorted(sources)}
                for alias, sources in sorted(
                    self._entity_alias_explicit_sources.items()) if sources
            ],
            "fact_pattern_alias_sources": [
                {"alias": list(item[0]), "entity": item[1],
                 "relation": list(item[2]), "subject": list(item[3]),
                 "object": list(item[4]), "source": item[5],
                 "positive": item[6]}
                for item in sorted(self._fact_pattern_alias_sources)
            ],
            "question_examples": [
                {"relation": list(json.loads(key[0])),
                 "answer_field": key[1], "prefix": list(key[2]),
                 "suffix": list(key[3]),
                 "entities": [list(entity) for entity in sorted(values)]}
                for key, values in sorted(self._question_examples.items())
            ],
            "question_example_evidence": [
                {"relation": list(json.loads(key[0])),
                 "answer_field": key[1], "prefix": list(key[2]),
                 "suffix": list(key[3]),
                 "examples": [
                     {"entity": list(entity),
                      "evidence": copy.deepcopy(records)}
                     for entity, records in sorted(by_entity.items())
                 ]}
                for key, by_entity in sorted(
                    self._question_example_evidence.items())
            ],
            "subject_pattern_question_examples": [
                {"relation": list(json.loads(key[0])),
                 "answer_field": key[1], "question_prefix": list(key[2]),
                 "question_suffix": list(key[3]),
                 "fact_bound_field": key[4],
                 "fact_prefix": list(key[5]), "fact_suffix": list(key[6]),
                 "examples": [
                     {"entity": list(entity), "answers": sorted(answers)}
                     for entity, answers in sorted(examples.items())
                 ]}
                for key, examples in sorted(
                    self._subject_pattern_question_examples.items())
            ],
            "induced_question_frames": [
                copy.deepcopy(proposal)
                for _key, proposal in sorted(self._induced_question_frames.items())
            ],
            "induced_qualified_question_frames": [
                copy.deepcopy(proposal)
                for _key, proposal in sorted(
                    self._induced_qualified_question_frames.items())
            ],
            "induced_multi_qualified_question_frames": [
                copy.deepcopy(proposal)
                for _key, proposal in sorted(
                    self._induced_multi_qualified_question_frames.items())
            ],
            "qualified_question_examples": [
                {"relation": list(key[0]), "answer_field": key[1],
                 "qualifier": list(key[2]), "entity_first": key[3],
                 "prefix": list(key[4]), "middle": list(key[5]),
                 "suffix": list(key[6]),
                 "examples": [
                     {"entity": list(pair[0]), "value": list(pair[1]),
                      "answers": sorted(answers)}
                     for pair, answers in sorted(examples.items())
                 ]}
                for key, examples in sorted(self._qualified_question_examples.items())
            ],
            "multi_qualified_question_examples": [
                {"relation": list(key[0]), "answer_field": key[1],
                 "qualifier_names": [list(name) for name in key[2]],
                 "template": list(key[3]),
                 "examples": [
                     {"entity": list(pair[0]),
                      "values": [list(value) for value in pair[1]],
                      "answers": sorted(answers)}
                     for pair, answers in sorted(examples.items())
                 ]}
                for key, examples in sorted(
                    self._multi_qualified_question_examples.items())
            ],
            "polar_question_examples": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "examples": [
                     {"subject": list(pair[0]), "object": list(pair[1]),
                      "answer": answer}
                     for pair, answer in sorted(examples.items())
                 ]}
                for key, examples in sorted(self._polar_question_examples.items())
            ],
            "qualified_polar_question_examples": [
                {"relation": list(key[0]),
                 "qualifier_names": [list(name) for name in key[1]],
                 "template": list(key[2]),
                 "examples": [
                     {"subject": list(pair[0]), "object": list(pair[1]),
                      "values": [list(value) for value in pair[2]],
                      "answer": answer}
                     for pair, answer in sorted(examples.items())
                 ]}
                for key, examples in sorted(
                    self._qualified_polar_question_examples.items())
            ],
            "path_question_examples": [
                {"relations": [list(relation) for relation in key[0]],
                 "prefix": list(key[1]), "suffix": list(key[2]),
                 "entities": [list(entity) for entity in sorted(entities)]}
                for key, entities in sorted(self._path_question_examples.items())
            ],
            "counterfactual_source_examples": [
                {"start": list(key[0]), "target": list(key[1]),
                 "relations": [list(relation) for relation in key[2]],
                 "qualifiers": [
                     {"name": list(name), "value": list(value)}
                     for name, value in key[3]
                 ],
                 "prefix": list(key[4]), "suffix": list(key[5]),
                 "sources": [
                     {"tokens": list(tokens), "source": examples[tokens]}
                     for tokens in sorted(examples)
                 ]}
                for key, examples in sorted(
                    self._counterfactual_source_examples.items())
            ],
            "counterfactual_path_examples": [
                {"template": list(key[0]),
                 "relations": [list(relation) for relation in key[1]],
                 "qualifiers": [
                     {"name": list(name), "value": list(value)}
                     for name, value in key[2]
                 ],
                 "examples": [
                     {"start": list(example[0]), "target": list(example[1]),
                      "source": list(example[2]),
                      "display": list(examples[example])}
                     for example in sorted(examples)
                 ]}
                for key, examples in sorted(
                    self._counterfactual_path_examples.items())
            ],
            "about_question_examples": [
                {"prefix": list(key[0]), "suffix": list(key[1]),
                 "entities": [
                     {"tokens": list(tokens), "entity": examples[tokens]}
                     for tokens in sorted(examples)
                 ]}
                for key, examples in sorted(self._about_question_examples.items())
            ],
            "fact_pattern_examples": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "examples": [
                     {"subject": list(pair[0]), "object": list(pair[1]),
                      "sources": sorted(sources)}
                     for pair, sources in sorted(examples.items())
                 ]}
                for key, examples in sorted(self._fact_pattern_examples.items())
            ],
            "context_fact_patterns": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "qualifier_names": list(key[2]), "positive": key[3],
                 "examples": [
                     {"subject": list(example[0]), "object": list(example[1]),
                      "qualifier_values": [list(value) for value in example[2]],
                      "predicate": list(example[3]), "sources": sorted(sources)}
                     for example, sources in sorted(examples.items())
                 ]}
                for key, examples in sorted(self._context_fact_patterns.items())
            ],
            "fact_pattern_surfaces": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "surfaces": sorted(surfaces)}
                for key, surfaces in sorted(self._fact_pattern_surfaces.items())
            ],
            "fact_pattern_predicates": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "phrases": [list(phrase) for phrase in sorted(phrases)]}
                for key, phrases in sorted(self._fact_pattern_predicates.items())
            ],
            "fact_pattern_predicate_sources": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "phrases": [
                     {"phrase": list(phrase), "examples": [
                         {"subject": list(pair[0]), "object": list(pair[1]),
                          "sources": sorted(sources)}
                         for pair, sources in sorted(by_pair.items())
                     ]}
                     for phrase, by_pair in sorted(phrases.items())
                 ]}
                for key, phrases in sorted(
                    self._fact_pattern_predicate_sources.items())
            ],
            "fact_pattern_surface_sources": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "surfaces": [
                     {"surface": surface, "examples": [
                         {"subject": list(pair[0]), "object": list(pair[1]),
                          "sources": sorted(sources)}
                         for pair, sources in sorted(by_pair.items())
                     ]}
                     for surface, by_pair in sorted(surfaces.items())
                 ]}
                for key, surfaces in sorted(
                    self._fact_pattern_surface_sources.items())
            ],
            "fact_pattern_polarities": [
                {"template": list(key[0]), "relation": list(key[1]),
                 "positive": polarity}
                for key, polarity in sorted(self._fact_pattern_polarities.items())
            ],
        }
        if destination.suffix.casefold() in {".sqlite", ".sqlite3", ".db"}:
            existing_connection = None
            if (self._knowledge_db_path is not None
                    and self._knowledge_db_path.resolve() == destination.resolve()
                    and isinstance(self._facts, SQLiteFactMap)):
                existing_connection = self._facts.connection
            _write_knowledge_database(
                destination, payload, self._facts, self._negative_facts,
                existing_connection=existing_connection)
            self._knowledge_db_path = destination.resolve()
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="\n") as output:
            output.write("{\n")
            first_member = True

            def member(name: str, write_value) -> None:
                nonlocal first_member
                if not first_member:
                    output.write(",\n")
                first_member = False
                output.write("  ")
                json.dump(name, output, ensure_ascii=False)
                output.write(": ")
                write_value()

            for name, value in payload.items():
                member(name, lambda value=value: json.dump(
                    value, output, ensure_ascii=False, indent=2))

            def write_facts(store: Mapping[tuple[Any, ...], FactEvidence]) -> None:
                output.write("[")
                rows = (store.items() if isinstance(store, SQLiteFactMap)
                        else ((key, store[key]) for key in sorted(store)))
                for number, (_key, fact) in enumerate(rows):
                    output.write("\n    " if number == 0 else ",\n    ")
                    json.dump(asdict(fact), output, ensure_ascii=False,
                              separators=(",", ":"))
                if store:
                    output.write("\n  ")
                output.write("]")

            member("facts", lambda: write_facts(self._facts))
            member("negative_facts", lambda: write_facts(self._negative_facts))
            output.write("\n}\n")

    @classmethod
    def load(cls, path: str | Path, *, fact_db: str | Path | None = None
             ) -> "CRMSKnowledgeBase":
        knowledge = cls()
        fact_connection = None
        knowledge_database_path = Path(path).expanduser().resolve()
        is_knowledge_database = knowledge_database_path.suffix.casefold() in {
            ".sqlite", ".sqlite3", ".db"}
        if is_knowledge_database:
            if fact_db is not None:
                raise ValueError(
                    "fact_db cannot be combined with a knowledge SQLite database")
            fact_connection, database_payload = _read_knowledge_database(
                knowledge_database_path)
            knowledge._facts = SQLiteFactMap(fact_connection, "positive_facts")
            knowledge._negative_facts = SQLiteFactMap(
                fact_connection, "negative_facts")
            knowledge._knowledge_db_path = knowledge_database_path
        elif fact_db is not None:
            fact_path = Path(fact_db).expanduser().resolve()
            fact_path.parent.mkdir(parents=True, exist_ok=True)
            fact_connection = sqlite3.connect(fact_path, isolation_level=None)
            tables = {row[0] for row in fact_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            expected_tables = {"fact_store_metadata", "positive_facts",
                               "negative_facts"}
            if tables and (
                    tables != expected_tables
                    or fact_connection.execute("PRAGMA application_id").fetchone()[0]
                    != _FACT_DB_APPLICATION_ID
                    or fact_connection.execute("PRAGMA user_version").fetchone()[0]
                    != _FACT_DB_VERSION):
                fact_connection.close()
                raise ValueError("existing file is not a CRMS SQLite fact store")
            fact_connection.execute("""CREATE TABLE IF NOT EXISTS fact_store_metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            ) WITHOUT ROWID""")
            metadata = dict(fact_connection.execute(
                "SELECT key,value FROM fact_store_metadata"))
            if tables and metadata.get("format") != "crms-fact-store":
                fact_connection.close()
                raise ValueError("existing SQLite fact store has invalid metadata")
            fact_connection.execute(
                f"PRAGMA application_id={_FACT_DB_APPLICATION_ID}")
            fact_connection.execute(f"PRAGMA user_version={_FACT_DB_VERSION}")
            knowledge._facts = SQLiteFactMap(fact_connection, "positive_facts")
            knowledge._negative_facts = SQLiteFactMap(
                fact_connection, "negative_facts")
            fact_connection.execute("BEGIN")
            fact_connection.execute("DELETE FROM positive_facts")
            fact_connection.execute("DELETE FROM negative_facts")
            fact_connection.execute(
                "INSERT OR REPLACE INTO fact_store_metadata VALUES (?,?)",
                ("format", "crms-fact-store"))
        try:
            payload: dict[str, Any] = (database_payload
                                       if is_knowledge_database else {})
            if not is_knowledge_database:
                with Path(path).open("r", encoding="utf-8") as source:
                    for name, value in _iter_knowledge_json(source):
                        if name in {"facts", "negative_facts"}:
                            if name == "facts":
                                add = knowledge.add_fact
                            else:
                                add = knowledge.add_negative_fact
                            for item in value:
                                if not isinstance(item, dict):
                                    raise ValueError(f"stored {name} record is malformed")
                                sources = item.get("sources", [])
                                if not sources:
                                    raise ValueError(
                                        f"stored {'negative ' if name == 'negative_facts' else ''}fact has no source provenance")
                                for citation in sources:
                                    add(item["subject"], item["relation"], item["object"],
                                        citation,
                                        qualifiers=dict(item.get("qualifiers", [])))
                        else:
                            payload[name] = value
            if payload.get("format_version") != cls.FORMAT_VERSION:
                raise ValueError("unsupported knowledge-base format version")
            configured_limit = cls(
                max_derived_cases=payload.get("max_derived_cases", 1_000))
            knowledge.max_derived_cases = configured_limit.max_derived_cases
            for item in payload.get("inference_rules", []):
                rule = knowledge.add_inference_rule(
                    item["rule_id"], item["first_relation"],
                    item["second_relation"], item["conclusion_relation"],
                    middle_kind=item.get("middle_kind"),
                    third_relation=item.get("third_relation"),
                    second_middle_kind=item.get("second_middle_kind"))
                validation = item.get("validation")
                if validation is not None:
                    if not isinstance(validation, dict):
                        raise ValueError("stored inference-rule validation is malformed")
                    knowledge._inference_rule_validation[_tokens(rule.rule_id)] = validation
            validated_relations = {
                _tokens(rule.conclusion_relation)
                for rule in knowledge._inference_rules_for_use()
                if knowledge._inference_rule_validation.get(
                    _tokens(rule.rule_id), {}).get("status", "validated")
                   == "validated"
            }
            if validated_relations:
                for negative in knowledge.negative_facts():
                    if _tokens(negative.relation) in validated_relations:
                        knowledge._flag_validated_rules_against_counterexample(
                            negative)
            for order, case in enumerate(payload.get("derived_cases", [])):
                conclusion = case.get("conclusion", {})
                if not isinstance(conclusion, dict):
                    raise ValueError("stored derived-case conclusion is malformed")
                case_qualifiers = knowledge._normalize_qualifiers(
                    dict(case.get("qualifiers", [])))
                key = knowledge._fact_key(
                    conclusion.get("subject", ""), conclusion.get("relation", ""),
                    conclusion.get("object", ""), case_qualifiers)
                proofs = case.get("proofs")
                lineage = case.get("lineage")
                practice_count = case.get("practice_count")
                retrieval_count = case.get("retrieval_count")
                if (not isinstance(proofs, list) or not proofs
                        or not isinstance(lineage, dict)
                        or not isinstance(practice_count, int)
                        or isinstance(practice_count, bool) or practice_count < 1
                        or not isinstance(retrieval_count, int)
                        or isinstance(retrieval_count, bool) or retrieval_count < 0):
                    raise ValueError("stored derived case is malformed")
                reuse_count = case.get("reuse_count", 0)
                if (not isinstance(reuse_count, int) or isinstance(reuse_count, bool)
                        or reuse_count < 0 or reuse_count > retrieval_count):
                    raise ValueError("stored derived-case reuse count is malformed")
                practice_order = case.get("practice_order", order)
                if (not isinstance(practice_order, int)
                        or isinstance(practice_order, bool) or practice_order < 0):
                    raise ValueError("stored derived-case order is malformed")
                knowledge._derived_cases[key] = {
                    "conclusion": {name: _display(conclusion[name], name)
                                   for name in ("subject", "relation", "object")},
                    "proofs": copy.deepcopy(proofs),
                    "lineage": {"sources": list(lineage.get("sources", [])),
                                "rule_ids": list(lineage.get("rule_ids", []))},
                    "practice_count": practice_count,
                    "retrieval_count": retrieval_count,
                    "reuse_count": reuse_count,
                    "practice_order": practice_order,
                    "qualifiers": list(case_qualifiers),
                    "validation_fingerprint": case.get("validation_fingerprint"),
                    "validation_bounds": copy.deepcopy(
                        case.get("validation_bounds", [])),
                }
                knowledge._next_derived_case_order = max(
                    knowledge._next_derived_case_order, practice_order + 1)
            knowledge._enforce_derived_case_limit()
            for item in payload.get("entity_aliases", []):
                sources = item.get("sources", [])
                if not sources:
                    raise ValueError("stored entity alias has no source provenance")
                for source in sources:
                    knowledge.teach_entity_alias(
                        " ".join(item["alias"]), item["entity"], source=source)
            if "entity_alias_explicit_sources" in payload:
                knowledge._entity_alias_explicit_sources = {
                    tuple(item["alias"]): set(item.get("sources", []))
                    for item in payload.get("entity_alias_explicit_sources", [])
                }
            for item in payload.get("fact_pattern_alias_sources", []):
                if type(item.get("positive")) is not bool:
                    raise ValueError("stored fact-pattern alias polarity is malformed")
                record = (tuple(item["alias"]), item["entity"],
                          tuple(item["relation"]), tuple(item["subject"]),
                          tuple(item["object"]), item["source"], item["positive"])
                if not record[0] or not record[1] or not record[5]:
                    raise ValueError("stored fact-pattern alias support is malformed")
                knowledge._fact_pattern_alias_sources.add(record)
            for alias in set(knowledge._entity_aliases) | {
                    item[0] for item in knowledge._fact_pattern_alias_sources}:
                knowledge._refresh_entity_alias(alias)
            for item in payload.get("question_examples", []):
                relation = tuple(item["relation"])
                key = (json.dumps(relation, ensure_ascii=False), item["answer_field"],
                       tuple(item["prefix"]), tuple(item["suffix"]))
                knowledge._question_examples[key] = {
                    tuple(entity): {" ".join(entity)} for entity in item["entities"]
                }
            for item in payload.get("question_example_evidence", []):
                relation = tuple(item["relation"])
                answer_field = item.get("answer_field")
                if not relation or answer_field not in {"subject", "object"}:
                    raise ValueError("stored question-frame evidence key is malformed")
                key = (json.dumps(relation, ensure_ascii=False), answer_field,
                       tuple(item.get("prefix", ())), tuple(item.get("suffix", ())))
                if key not in knowledge._question_examples:
                    raise ValueError("question-frame evidence has no stored frame")
                by_entity = {}
                for example in item.get("examples", ()):
                    entity = tuple(example.get("entity", ()))
                    if not entity or entity not in knowledge._question_examples[key]:
                        raise ValueError("question-frame evidence names an unknown entity")
                    records = example.get("evidence", ())
                    if (not isinstance(records, list)
                            or any(not isinstance(record, dict)
                                   or not isinstance(record.get("answer"), str)
                                   or not isinstance(record.get("conclusion"), dict)
                                   or not isinstance(record.get("direct_facts", []), list)
                                   or not isinstance(record.get("proofs", []), list)
                                   for record in records)):
                        raise ValueError("stored question-frame evidence is malformed")
                    for record in records:
                        conclusion = record["conclusion"]
                        try:
                            expected_qualifiers = knowledge._normalize_qualifiers(
                                dict(record.get("qualifiers", ())))
                        except (TypeError, ValueError) as error:
                            raise ValueError(
                                "stored question-frame qualifiers are malformed") from error
                        for fact in record.get("direct_facts", ()):
                            if (not isinstance(fact, Mapping)
                                    or not knowledge._proof_fact_support_is_present(fact)):
                                raise ValueError(
                                    "question-frame direct evidence is absent from the store")
                        _facts, _negatives, rules = (
                            knowledge._sqlite_inference_snapshot(
                                conclusion.get("relation", ""),
                                expected_qualifiers,
                                list(knowledge._inference_rules.values())))
                        for proof in record.get("proofs", ()):
                            checked = verify_inference_proof(
                                proof, _facts, rules,
                                expected_conclusion=conclusion,
                                expected_qualifiers=expected_qualifiers,
                                fact_lookup=knowledge._proof_fact_support_is_present)
                            if not checked.valid:
                                raise ValueError(
                                    "question-frame proof evidence failed verification")
                    by_entity[entity] = copy.deepcopy(records)
                if by_entity:
                    knowledge._question_example_evidence[key] = by_entity
            for item in payload.get("subject_pattern_question_examples", []):
                relation = tuple(item["relation"])
                answer_field = item.get("answer_field")
                fact_bound_field = item.get("fact_bound_field")
                if (not relation or answer_field not in {"subject", "object"}
                        or fact_bound_field not in {"subject", "object"}
                        or fact_bound_field == answer_field):
                    raise ValueError("stored subject-pattern question frame is malformed")
                key = (json.dumps(relation, ensure_ascii=False), answer_field,
                       tuple(item["question_prefix"]),
                       tuple(item["question_suffix"]), fact_bound_field,
                       tuple(item["fact_prefix"]), tuple(item["fact_suffix"]))
                examples = {}
                for example in item.get("examples", []):
                    entity = tuple(example["entity"])
                    answers = set(example.get("answers", []))
                    if not entity or len(answers) != 1:
                        raise ValueError(
                            "stored subject-pattern examples need one answer")
                    examples[entity] = answers
                if examples:
                    knowledge._subject_pattern_question_examples[key] = examples
            for item in payload.get("qualified_question_examples", []):
                key = (tuple(item["relation"]), item["answer_field"],
                       tuple(item["qualifier"]), item.get("entity_first", True),
                       tuple(item["prefix"]), tuple(item["middle"]),
                       tuple(item["suffix"]))
                knowledge._qualified_question_examples[key] = {
                    (tuple(example["entity"]), tuple(example["value"])):
                    set(example.get("answers", []))
                    for example in item.get("examples", [])
                }
            for item in payload.get("multi_qualified_question_examples", []):
                key = (tuple(item["relation"]), item["answer_field"],
                       tuple(tuple(name) for name in item["qualifier_names"]),
                       tuple(item["template"]))
                knowledge._multi_qualified_question_examples[key] = {
                    (tuple(example["entity"]),
                     tuple(tuple(value) for value in example["values"])):
                    set(example.get("answers", []))
                    for example in item.get("examples", [])
                }
            for item in payload.get("polar_question_examples", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                examples = {}
                for example in item.get("examples", []):
                    pair = (tuple(example["subject"]), tuple(example["object"]))
                    if type(example.get("answer")) is not bool:
                        raise ValueError("stored polar-question answer must be bool")
                    examples[pair] = example["answer"]
                knowledge._polar_question_examples[key] = examples
            for item in payload.get("qualified_polar_question_examples", []):
                key = (tuple(item["relation"]),
                       tuple(tuple(name) for name in item["qualifier_names"]),
                       tuple(item["template"]))
                examples = {}
                for example in item.get("examples", []):
                    if type(example.get("answer")) is not bool:
                        raise ValueError("stored qualified polar answer must be bool")
                    pair = (tuple(example["subject"]), tuple(example["object"]),
                            tuple(tuple(value) for value in example["values"]))
                    examples[pair] = example["answer"]
                knowledge._qualified_polar_question_examples[key] = examples
            for item in payload.get("path_question_examples", []):
                key = (tuple(tuple(relation) for relation in item["relations"]),
                       tuple(item["prefix"]), tuple(item["suffix"]))
                knowledge._path_question_examples[key] = {
                    tuple(entity) for entity in item["entities"]
                }
            for item in payload.get("counterfactual_source_examples", []):
                key = (tuple(item["start"]), tuple(item["target"]),
                       tuple(tuple(relation) for relation in item["relations"]),
                       tuple((tuple(pair["name"]), tuple(pair["value"]))
                             for pair in item.get("qualifiers", [])),
                       tuple(item["prefix"]), tuple(item["suffix"]))
                knowledge._counterfactual_source_examples[key] = {
                    tuple(example["tokens"]): example["source"]
                    for example in item.get("sources", [])
                }
            for item in payload.get("counterfactual_path_examples", []):
                key = (tuple(item["template"]),
                       tuple(tuple(relation) for relation in item["relations"]),
                       tuple((tuple(pair["name"]), tuple(pair["value"]))
                             for pair in item.get("qualifiers", [])))
                knowledge._counterfactual_path_examples[key] = {
                    (tuple(example["start"]), tuple(example["target"]),
                     tuple(example["source"])): tuple(example["display"])
                    for example in item.get("examples", [])
                }
            for item in payload.get("about_question_examples", []):
                key = (tuple(item["prefix"]), tuple(item["suffix"]))
                knowledge._about_question_examples[key] = {
                    tuple(example["tokens"]): example["entity"]
                    for example in item.get("entities", [])
                }
            for item in payload.get("fact_pattern_examples", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                examples = {}
                for example in item["examples"]:
                    pair = (tuple(example["subject"]), tuple(example["object"]))
                    examples[pair] = set(example.get("sources", []))
                knowledge._fact_pattern_examples[key] = examples
            for item in payload.get("context_fact_patterns", []):
                if type(item.get("positive")) is not bool:
                    raise ValueError("stored context fact-frame polarity is malformed")
                key = (tuple(item["template"]), tuple(item["relation"]),
                       tuple(item["qualifier_names"]), item["positive"])
                examples = {}
                for example in item.get("examples", []):
                    signature = (tuple(example["subject"]), tuple(example["object"]),
                                 tuple(tuple(value) for value in
                                       example["qualifier_values"]),
                                 tuple(example["predicate"]))
                    sources = set(example.get("sources", []))
                    if not sources:
                        raise ValueError("stored context fact-frame example has no source")
                    examples[signature] = sources
                if (not key[0] or not key[1] or not key[2]
                        or any(len(example[2]) != len(key[2])
                               for example in examples)):
                    raise ValueError("stored context fact-frame pattern is malformed")
                knowledge._context_fact_patterns[key] = examples
            for item in payload.get("fact_pattern_surfaces", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                knowledge._fact_pattern_surfaces[key] = set(item.get("surfaces", []))
            for item in payload.get("fact_pattern_predicates", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                knowledge._fact_pattern_predicates[key] = {
                    tuple(phrase) for phrase in item.get("phrases", [])
                }
            for item in payload.get("fact_pattern_predicate_sources", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                knowledge._fact_pattern_predicate_sources[key] = {
                    tuple(phrase["phrase"]): {
                        (tuple(example["subject"]), tuple(example["object"])):
                        set(example.get("sources", []))
                        for example in phrase.get("examples", [])
                    }
                    for phrase in item.get("phrases", [])
                }
            for item in payload.get("fact_pattern_surface_sources", []):
                key = (tuple(item["template"]), tuple(item["relation"]))
                knowledge._fact_pattern_surface_sources[key] = {
                    surface["surface"]: {
                        (tuple(example["subject"]), tuple(example["object"])):
                        set(example.get("sources", []))
                        for example in surface.get("examples", [])
                    }
                    for surface in item.get("surfaces", [])
                }
            for item in payload.get("fact_pattern_polarities", []):
                if type(item.get("positive")) is not bool:
                    raise ValueError("stored fact-pattern polarity must be bool")
                key = (tuple(item["template"]), tuple(item["relation"]))
                knowledge._fact_pattern_polarities[key] = item["positive"]
            # Older saved knowledge bases stored the canonical relation directly
            # in the frame and therefore need no separate predicate slot.
            for key, examples in knowledge._fact_pattern_examples.items():
                knowledge._fact_pattern_polarities.setdefault(key, True)
                if key not in knowledge._fact_pattern_predicates:
                    if "<predicate>" not in key[0]:
                        knowledge._fact_pattern_predicates[key] = {key[1]}
                # Migrate older stores conservatively to the available example
                # lineage. New stores retain per-form and per-surface citations.
                pairs = {pair: set(sources) for pair, sources in examples.items()}
                if key not in knowledge._fact_pattern_predicate_sources:
                    knowledge._fact_pattern_predicate_sources[key] = {
                        phrase: {pair: set(sources) for pair, sources in pairs.items()}
                        for phrase in knowledge._fact_pattern_predicates.get(key, set())
                    }
                if key not in knowledge._fact_pattern_surface_sources:
                    knowledge._fact_pattern_surface_sources[key] = {
                        surface: {pair: set(sources) for pair, sources in pairs.items()}
                        for surface in knowledge._fact_pattern_surfaces.get(key, set())
                    }
            raw_induced_frames = payload.get("induced_question_frames", [])
            if (not isinstance(raw_induced_frames, list)
                    or len(raw_induced_frames) > 1000):
                raise ValueError("stored induced question frames exceed their bound")
            for record in raw_induced_frames:
                if (not isinstance(record, dict)
                        or record.get("kind") not in {
                            "analogical_question_frame",
                            "analogical_qualified_question_frame",
                            "active_question_role_alternation"}
                        or not isinstance(record.get("artifact_id"), str)):
                    raise ValueError("stored induced question frame is malformed")
                # Recreate and re-evaluate the artifact against the loaded snapshot.
                # Removed or changed evidence makes it stale, so it is not activated.
                try:
                    knowledge.accept_question_frame_proposal(record["artifact_id"])
                except ValueError:
                    continue
            raw_induced_qualified_frames = payload.get(
                "induced_qualified_question_frames", [])
            if (not isinstance(raw_induced_qualified_frames, list)
                    or len(raw_induced_qualified_frames) > 1000):
                raise ValueError("stored induced qualified question frames exceed their bound")
            for record in raw_induced_qualified_frames:
                if (not isinstance(record, dict)
                        or record.get("kind") != "analogical_qualified_question_frame"
                        or not isinstance(record.get("artifact_id"), str)):
                    raise ValueError("stored induced qualified question frame is malformed")
                try:
                    knowledge.accept_question_frame_proposal(record["artifact_id"])
                except ValueError:
                    continue
            raw_induced_multi_frames = payload.get(
                "induced_multi_qualified_question_frames", [])
            if (not isinstance(raw_induced_multi_frames, list)
                    or len(raw_induced_multi_frames) > 1000):
                raise ValueError("stored induced multi-qualified frames exceed their bound")
            for record in raw_induced_multi_frames:
                if (not isinstance(record, dict)
                        or record.get("kind")
                            != "analogical_multi_qualified_question_frame"
                        or not isinstance(record.get("artifact_id"), str)):
                    raise ValueError("stored induced multi-qualified frame is malformed")
                try:
                    knowledge.accept_question_frame_proposal(record["artifact_id"])
                except ValueError:
                    continue
            if fact_connection is not None and not is_knowledge_database:
                # Keep the replacement fact snapshot private until every section
                # of the knowledge payload has passed validation. Earlier commits
                # could leave a partial or unsupported snapshot in the sidecar.
                fact_connection.commit()
            return knowledge
        except Exception:
            if fact_connection is not None:
                fact_connection.rollback()
                fact_connection.close()
            raise
