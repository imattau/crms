"""SQLite memory for the Phase 11 pattern layer.

Tables are prefixed `pat_` so the store can share a file with the Phase 10
`GenerationRuleStore` (same application id, distinct tables). It holds verb
forms, agentive nouns, induced word classes, relation specs with their
evidence, tunable parameters, and an audit trail. Specs and parameters are
versioned; the current value is the latest accepted one, and a rollback is one
status change. The visible seed file is `crms_pattern_seed.json`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from crms_pattern_ranker import DEFAULT_PARAMS
from crms_patterns import PatternLanguage
from crms_relation_specs import RelationSpec

APPLICATION_ID = int.from_bytes(b"CRGN", "big")   # shared with GenerationRuleStore
ORIGINS = frozenset({"seed", "teacher", "induced", "conversation", "human", "fit"})
SEED_PATH = Path(__file__).resolve().parent / "crms_pattern_seed.json"


class PatternMemoryError(ValueError):
    """The pattern store is malformed or an operation is invalid."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PatternMemory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        application_id = self.connection.execute("PRAGMA application_id").fetchone()[0]
        if application_id not in (0, APPLICATION_ID):
            raise PatternMemoryError("database belongs to another CRMS store")
        self.connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS pat_change (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL,
                tier TEXT NOT NULL CHECK(tier IN ('data','rule','code')),
                summary TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                accepted INTEGER NOT NULL CHECK(accepted IN (0,1)),
                metrics_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS pat_verb (
                lemma TEXT NOT NULL,
                form_kind INTEGER NOT NULL CHECK(form_kind BETWEEN 0 AND 3),
                form TEXT NOT NULL,
                PRIMARY KEY(lemma, form_kind)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_agent_noun (
                lemma TEXT NOT NULL,
                noun TEXT NOT NULL,
                PRIMARY KEY(lemma, noun)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_class (
                cls TEXT NOT NULL,
                member TEXT NOT NULL,
                support INTEGER NOT NULL,
                origin TEXT NOT NULL,
                PRIMARY KEY(cls, member)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_spec (
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                question_json TEXT NOT NULL,
                sentence_json TEXT NOT NULL,
                template TEXT NOT NULL,
                verb_class TEXT NOT NULL DEFAULT '',
                rationale TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected','retired')),
                evidence_json TEXT NOT NULL DEFAULT '{}',
                proposition_json TEXT NOT NULL DEFAULT '{}',
                change_id INTEGER REFERENCES pat_change(change_id),
                PRIMARY KEY(name, version)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_rewrite (
                name TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('phrase','verb')),
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('accepted','rejected','retired'))
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_intent (
                family TEXT NOT NULL,
                name TEXT NOT NULL,
                priority INTEGER NOT NULL,
                patterns_json TEXT NOT NULL,
                anchored INTEGER NOT NULL CHECK(anchored IN (0,1)),
                result TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('accepted','rejected','retired')),
                PRIMARY KEY(family, name)
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_gate_policy (
                dimension TEXT PRIMARY KEY,
                answer_types TEXT NOT NULL,
                invariant INTEGER NOT NULL CHECK(invariant IN (0,1)),
                threshold REAL,
                typed_reason TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('accepted','rejected','retired'))
            ) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS pat_param (
                name TEXT NOT NULL,
                version INTEGER NOT NULL,
                value REAL NOT NULL,
                origin TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                metrics_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(name, version)
            ) WITHOUT ROWID;
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "PatternMemory":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ audit
    def log_change(self, tier: str, summary: str, *, reference: str = "",
                   accepted: bool = True, metrics: Mapping[str, Any] | None = None) -> int:
        cursor = self.connection.execute(
            "INSERT INTO pat_change(at,tier,summary,reference,accepted,metrics_json) "
            "VALUES(?,?,?,?,?,?)",
            (_now(), tier, summary, reference, 1 if accepted else 0,
             json.dumps(metrics or {}, sort_keys=True)))
        return int(cursor.lastrowid)

    def changes(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.connection.execute(
            "SELECT * FROM pat_change ORDER BY change_id")]

    # -------------------------------------------------------- resources
    def put_verb(self, lemma: str, forms: Iterable[str]) -> None:
        forms = list(forms)
        if len(forms) != 4:
            raise PatternMemoryError("a verb needs base, third-person, past, participle")
        for kind, form in enumerate(forms):
            self.connection.execute(
                "INSERT OR REPLACE INTO pat_verb VALUES(?,?,?)", (lemma, kind, form))

    def put_agent_noun(self, lemma: str, noun: str) -> None:
        self.connection.execute("INSERT OR IGNORE INTO pat_agent_noun VALUES(?,?)", (lemma, noun))

    def put_class_member(self, cls: str, member: str, support: int, origin: str) -> None:
        if origin not in ORIGINS:
            raise PatternMemoryError(f"unknown origin: {origin!r}")
        self.connection.execute(
            "INSERT OR REPLACE INTO pat_class VALUES(?,?,?,?)", (cls, member, support, origin))

    def language(self) -> PatternLanguage:
        verbs: dict[str, list[str]] = {}
        for r in self.connection.execute("SELECT lemma,form_kind,form FROM pat_verb ORDER BY lemma,form_kind"):
            verbs.setdefault(r["lemma"], [""] * 4)[r["form_kind"]] = r["form"]
        agents: dict[str, list[str]] = {}
        for r in self.connection.execute("SELECT lemma,noun FROM pat_agent_noun ORDER BY lemma,noun"):
            agents.setdefault(r["lemma"], []).append(r["noun"])
        classes: dict[str, dict[str, int]] = {}
        for r in self.connection.execute("SELECT cls,member,support FROM pat_class"):
            classes.setdefault(r["cls"], {})[r["member"]] = r["support"]
        return PatternLanguage(verbs=verbs, agent_nouns=agents, classes=classes)

    # --------------------------------------------------------- rewrites
    def put_rewrite(self, kind: str, source: str, target: str, *, origin: str,
                    rationale: str = "", status: str = "accepted") -> None:
        if origin not in ORIGINS:
            raise PatternMemoryError(f"unknown origin: {origin!r}")
        self.connection.execute(
            "INSERT OR REPLACE INTO pat_rewrite VALUES(?,?,?,?,?,?,?)",
            (f"{kind}:{source}", kind, source, target, rationale, origin, status))

    def rewrites(self):
        from crms_pattern_rewrite import Rewrite
        return [Rewrite(r["kind"], r["source"], r["target"]) for r in self.connection.execute(
            "SELECT kind,source,target FROM pat_rewrite WHERE status='accepted' ORDER BY kind,source")]

    # ---------------------------------------------------------- intents
    def put_intent(self, family: str, name: str, *, priority: int,
                   patterns: Iterable[str], result: str, anchored: bool = False,
                   rationale: str = "", origin: str = "seed",
                   status: str = "accepted") -> None:
        if origin not in ORIGINS:
            raise PatternMemoryError(f"unknown origin: {origin!r}")
        from crms_patterns import parse_pattern
        patterns = list(patterns)
        for source in patterns:
            parse_pattern(source)       # reject a malformed pattern on entry
        self.connection.execute(
            "INSERT OR REPLACE INTO pat_intent VALUES(?,?,?,?,?,?,?,?,?)",
            (family, name, int(priority), json.dumps(patterns), int(anchored),
             result, rationale, origin, status))

    def set_intent_status(self, family: str, name: str, status: str) -> None:
        self.connection.execute(
            "UPDATE pat_intent SET status=? WHERE family=? AND name=?",
            (status, family, name))

    def intents(self, family: str) -> list[dict[str, Any]]:
        return [{"name": r["name"], "priority": r["priority"],
                 "patterns": json.loads(r["patterns_json"]),
                 "anchored": bool(r["anchored"]), "result": r["result"]}
                for r in self.connection.execute(
                    "SELECT * FROM pat_intent WHERE family=? AND status='accepted' "
                    "ORDER BY priority,name", (family,))]

    # ------------------------------------------------------ gate policy
    def put_gate_policy(self, dimension: str, *, answer_types: Iterable[str] | None,
                        invariant: bool, typed_reason: str, origin: str,
                        threshold: float | None = None, rationale: str = "",
                        status: str = "accepted") -> None:
        """Declare how the quote-evidence gate treats a deviation dimension.

        An invariant dimension that fails withholds the quote and abstains with
        `typed_reason`; `answer_types` of None means every question shape."""
        if origin not in ORIGINS:
            raise PatternMemoryError(f"unknown origin: {origin!r}")
        self.connection.execute(
            "INSERT OR REPLACE INTO pat_gate_policy VALUES(?,?,?,?,?,?,?,?)",
            (dimension, "*" if answer_types is None else ",".join(sorted(answer_types)),
             int(invariant), threshold, typed_reason, rationale, origin, status))

    def gate_policy(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in self.connection.execute(
                "SELECT * FROM pat_gate_policy WHERE status='accepted' ORDER BY dimension"):
            out[r["dimension"]] = {
                "answer_types": None if r["answer_types"] == "*"
                else frozenset(r["answer_types"].split(",")),
                "invariant": bool(r["invariant"]), "threshold": r["threshold"],
                "typed_reason": r["typed_reason"]}
        return out

    # ----------------------------------------------------------- params
    def set_param(self, name: str, value: float, *, origin: str, rationale: str = "",
                  metrics: Mapping[str, Any] | None = None) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM pat_param WHERE name=?", (name,)).fetchone()
        version = int(row[0])
        self.connection.execute(
            "INSERT INTO pat_param VALUES(?,?,?,?,?,?)",
            (name, version, float(value), origin, rationale,
             json.dumps(metrics or {}, sort_keys=True)))
        return version

    def params(self) -> dict[str, float]:
        out = dict(DEFAULT_PARAMS)
        for r in self.connection.execute(
                "SELECT p.name,p.value FROM pat_param p WHERE p.version="
                "(SELECT MAX(version) FROM pat_param q WHERE q.name=p.name)"):
            out[r["name"]] = r["value"]
        return out

    # ------------------------------------------------------------ specs
    def put_spec(self, spec: RelationSpec, *, evidence: Mapping[str, Any] | None = None,
                 change_id: int | None = None) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM pat_spec WHERE name=?", (spec.name,)).fetchone()
        version = int(row[0])
        self.connection.execute(
            "INSERT INTO pat_spec VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec.name, version, spec.priority, json.dumps(list(spec.question_patterns)),
             json.dumps(list(spec.sentence_patterns)), spec.template, spec.verb_class,
             spec.rationale, spec.origin, spec.status,
             json.dumps(evidence or {}, ensure_ascii=False),
             json.dumps(dict(spec.proposition), ensure_ascii=False), change_id))
        return version

    def set_spec_status(self, name: str, status: str, note: str = "") -> None:
        """Retire or reject the current version of a spec; one operation."""
        self.connection.execute(
            "UPDATE pat_spec SET status=?, rationale=rationale||? WHERE name=? AND version="
            "(SELECT MAX(version) FROM pat_spec WHERE name=?)",
            (status, (" [" + note + "]") if note else "", name, name))

    def specs(self, *, status: str = "accepted") -> list[RelationSpec]:
        out: list[RelationSpec] = []
        for r in self.connection.execute(
                "SELECT * FROM pat_spec s WHERE version=(SELECT MAX(version) FROM pat_spec t "
                "WHERE t.name=s.name) AND status=? ORDER BY priority,name", (status,)):
            out.append(RelationSpec(
                name=r["name"], priority=r["priority"],
                question_patterns=tuple(json.loads(r["question_json"])),
                sentence_patterns=tuple(json.loads(r["sentence_json"])),
                template=r["template"], verb_class=r["verb_class"],
                rationale=r["rationale"], origin=r["origin"], status=r["status"],
                proposition=json.loads(r["proposition_json"])))
        return out

    def spec_evidence(self, name: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT evidence_json FROM pat_spec WHERE name=? ORDER BY version DESC LIMIT 1",
            (name,)).fetchone()
        return json.loads(row["evidence_json"]) if row else {}

    # ------------------------------------------------------------- seed
    def seed(self, path: str | Path = SEED_PATH) -> int:
        """Load the visible seed file. Returns the number of specs loaded."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format") != "crms-pattern-seed":
            raise PatternMemoryError("not a CRMS pattern seed file")
        from crms_spec_verifier import expand
        change = self.log_change("data", "load pattern seed", reference=str(Path(path).name))
        for lemma, forms in payload["verbs"].items():
            self.put_verb(lemma, forms)
        for lemma, nouns in payload["agent_nouns"].items():
            for noun in nouns:
                self.put_agent_noun(lemma, noun)
        for cls, members in payload["classes"].items():
            for member, info in members.items():
                self.put_class_member(cls, member, int(info["support"]), info["origin"])
        for name, value in payload["params"].items():
            self.set_param(name, value, origin="seed", rationale="seed value")
        for row in payload.get("rewrites", ()):
            self.put_rewrite(row["kind"], row["source"], row["target"],
                             origin=row.get("origin", "teacher"), rationale=row.get("rationale", ""))
        for row in payload.get("intents", ()):
            self.put_intent(row["family"], row["name"], priority=row["priority"],
                            patterns=row["patterns"], result=row["result"],
                            anchored=row.get("anchored", False),
                            rationale=row.get("rationale", ""),
                            origin=row.get("origin", "seed"))
        for row in payload.get("gate_policy", ()):
            self.put_gate_policy(
                row["dimension"], answer_types=row["answer_types"],
                invariant=row["invariant"], typed_reason=row["typed_reason"],
                threshold=row.get("threshold"), rationale=row.get("rationale", ""),
                origin=row.get("origin", "seed"))
        count = 0
        for raw in payload["specs"]:
            raw = expand(dict(raw))
            spec = RelationSpec(
                name=raw["name"], priority=int(raw["priority"]),
                question_patterns=tuple(raw["question_patterns"]),
                sentence_patterns=tuple(raw["sentence_patterns"]),
                template=raw["template"], verb_class=raw.get("verb_class", ""),
                rationale=raw.get("rationale", ""), origin=raw.get("origin", "seed"),
                proposition=raw.get("proposition", {}))
            evidence = dict(raw.get("evidence", {}))
            if "base" in raw:
                evidence["base"] = raw["base"]
                evidence["transforms"] = raw.get("transforms", [])
            self.put_spec(spec, evidence=evidence, change_id=change)
            count += 1
        self.connection.commit()
        return count
