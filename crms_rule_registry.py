"""Governed rule registry for CRMS self-learning.

Rules are explicit, scoped, inspectable records. They move through a lifecycle
(proposed → validated → active → contested → retired), carry provenance and
validation evidence, track utility, and can be rolled back. Derived rules are
lower-trust and can never auto-activate.

This module is intentionally independent of the existing knowledge, procedure,
and inference stores. Phase integration adapts those stores into this registry
rather than replacing them.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

FORMAT = "crms-rule-registry"
VERSION = 1

FAMILIES = frozenset({
    "lexical",
    "morphology",
    "procedure",
    "fact-frame",
    "inference-schema",
    "relation-type",
    "task-plan",
    "domain",
    "dialogue-policy",
})

STATES = frozenset({"proposed", "validated", "active", "contested", "retired"})
TRUST_LEVELS = frozenset({"taught", "source-reviewed", "derived"})
ACCEPTANCE_MODES = frozenset({"review", "scoped-auto"})

#: Families whose rules have narrow, mechanically checkable scope. Only these
#: may enter scoped auto-acceptance, and only with independent evidence.
AUTO_ACCEPT_FAMILIES = frozenset({"lexical", "morphology", "procedure"})

#: Oracles that are not independent of the rule generator.
_NON_INDEPENDENT_ORACLES = frozenset({"self", "generator", "crms"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise ValueError(f"rule id must be a non-empty slug: {value!r}")
    return value


@dataclass
class RuleRecord:
    id: str
    family: str
    statement: str
    scope: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    trust: str = "taught"
    state: str = "proposed"
    acceptance_mode: str = "review"
    validation: dict[str, Any] | None = None
    dependencies: list[str] = field(default_factory=list)
    utility: dict[str, Any] = field(default_factory=lambda: {
        "applications": 0,
        "successes": 0,
        "corrections": 0,
        "saved_work": 0,
        "last_used": None,
    })
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    version: int = 1
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.state == "active"

    @property
    def validated(self) -> bool:
        return bool(self.validation and self.validation.get("passed"))

    def as_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("history", None)
        return data


class RuleRegistry:
    """Bounded, persistent rule store with lifecycle and correction propagation."""

    def __init__(self, *, allow_scoped_auto: bool = False) -> None:
        self._records: dict[str, RuleRecord] = {}
        self.allow_scoped_auto = bool(allow_scoped_auto)

    # -- inspection -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, rule_id: object) -> bool:
        return rule_id in self._records

    def get(self, rule_id: str) -> RuleRecord:
        try:
            return self._records[rule_id]
        except KeyError as error:
            raise KeyError(f"unknown rule: {rule_id!r}") from error

    def records(self, *, state: str | None = None,
                family: str | None = None) -> list[RuleRecord]:
        rows = list(self._records.values())
        if state is not None:
            rows = [row for row in rows if row.state == state]
        if family is not None:
            rows = [row for row in rows if row.family == family]
        return sorted(rows, key=lambda row: (row.family, row.id))

    def dependents(self, rule_id: str) -> list[RuleRecord]:
        """Return all non-retired rules that depend on ``rule_id`` directly or transitively."""

        found: list[RuleRecord] = []
        seen: set[str] = set()

        def visit(target: str) -> None:
            for row in self._records.values():
                if row.id in seen:
                    continue
                if target in row.dependencies:
                    seen.add(row.id)
                    found.append(row)
                    visit(row.id)

        visit(rule_id)
        return found

    # -- lifecycle ------------------------------------------------------

    def propose(self, *, rule_id: str, family: str, statement: str,
                scope: str = "", payload: Mapping[str, Any] | None = None,
                provenance: Iterable[Mapping[str, Any]] = (),
                trust: str = "taught",
                dependencies: Iterable[str] = ()) -> RuleRecord:
        rule_id = _slug(rule_id)
        if rule_id in self._records:
            raise ValueError(f"rule already exists: {rule_id!r}")
        if family not in FAMILIES:
            raise ValueError(f"unknown rule family: {family!r}")
        if trust not in TRUST_LEVELS:
            raise ValueError(f"unknown trust level: {trust!r}")
        dependencies = list(dict.fromkeys(str(item) for item in dependencies))
        unknown = [item for item in dependencies if item not in self._records]
        if unknown:
            raise ValueError(f"unknown dependencies: {unknown}")
        record = RuleRecord(
            id=rule_id,
            family=family,
            statement=statement.strip(),
            scope=scope.strip(),
            payload=dict(payload or {}),
            provenance=[dict(item) for item in provenance],
            trust=trust,
            dependencies=dependencies,
        )
        if not record.statement:
            raise ValueError("rule statement cannot be empty")
        record.history.append({
            "at": record.created_at,
            "action": "propose",
            "before": None,
            "detail": {"trust": trust},
        })
        self._records[rule_id] = record
        return record

    def validate(self, rule_id: str, *, oracle: str, passed: bool,
                 cases: int, independent_sources: int,
                 detail: str = "") -> RuleRecord:
        record = self.get(rule_id)
        if record.state == "retired":
            raise ValueError(f"cannot validate retired rule: {rule_id!r}")
        oracle = oracle.strip()
        if not oracle:
            raise ValueError("validation requires an oracle")
        if oracle.casefold() in _NON_INDEPENDENT_ORACLES:
            raise ValueError(
                f"oracle {oracle!r} is not independent of the rule generator")
        if cases < 0 or independent_sources < 0:
            raise ValueError("validation counts cannot be negative")
        before = self._snapshot(record)
        record.validation = {
            "oracle": oracle,
            "passed": bool(passed),
            "cases": int(cases),
            "independent_sources": int(independent_sources),
            "detail": detail,
            "validated_at": _now(),
        }
        if passed:
            if record.state != "active":
                record.state = "validated"
        elif record.state == "active":
            record.state = "contested"
        record.updated_at = _now()
        record.version += 1
        record.history.append({
            "at": record.updated_at,
            "action": "validate" if passed else "validation-failed",
            "before": before,
            "detail": record.validation,
        })
        return record

    def revise(self, rule_id: str, *, statement: str | None = None,
               payload: Mapping[str, Any] | None = None,
               provenance: Iterable[Mapping[str, Any]] | None = None,
               dependencies: Iterable[str] | None = None) -> RuleRecord:
        """Update a rule's evidence while preserving its lifecycle state."""

        record = self.get(rule_id)
        if record.state == "retired":
            raise ValueError(f"cannot revise retired rule: {rule_id!r}")
        before = self._snapshot(record)
        if statement is not None:
            if not statement.strip():
                raise ValueError("rule statement cannot be empty")
            record.statement = statement.strip()
        if payload is not None:
            record.payload = dict(payload)
        if provenance is not None:
            record.provenance = [dict(item) for item in provenance]
        if dependencies is not None:
            dependencies = list(dict.fromkeys(str(item) for item in dependencies))
            unknown = [item for item in dependencies if item not in self._records]
            if unknown:
                raise ValueError(f"unknown dependencies: {unknown}")
            record.dependencies = dependencies
        record.updated_at = _now()
        record.version += 1
        record.history.append({
            "at": record.updated_at,
            "action": "revise",
            "before": before,
            "detail": {"version": record.version},
        })
        return record

    def activate(self, rule_id: str, *, mode: str = "review",
                 authoriser: str = "user") -> RuleRecord:
        record = self.get(rule_id)
        if record.state != "validated":
            raise ValueError(
                f"only validated rules can activate; {rule_id!r} is "
                f"{record.state!r}")
        if mode not in ACCEPTANCE_MODES:
            raise ValueError(f"unknown acceptance mode: {mode!r}")
        if mode == "scoped-auto":
            self._require_scoped_auto_eligible(record)
        before = self._snapshot(record)
        record.state = "active"
        record.acceptance_mode = mode
        record.updated_at = _now()
        record.version += 1
        record.history.append({
            "at": record.updated_at,
            "action": "activate",
            "before": before,
            "detail": {"mode": mode, "authoriser": authoriser},
        })
        return record

    def _require_scoped_auto_eligible(self, record: RuleRecord) -> None:
        if not self.allow_scoped_auto:
            raise ValueError("scoped auto-acceptance is disabled")
        if record.trust == "derived":
            raise ValueError("derived rules cannot auto-activate")
        if record.family not in AUTO_ACCEPT_FAMILIES:
            raise ValueError(
                f"family {record.family!r} is not eligible for scoped auto-acceptance")
        validation = record.validation or {}
        if not validation.get("passed"):
            raise ValueError("scoped auto-acceptance requires a passing validation")
        if int(validation.get("independent_sources", 0)) < 2:
            raise ValueError(
                "scoped auto-acceptance requires at least two independent sources")
        if int(validation.get("cases", 0)) < 3:
            raise ValueError(
                "scoped auto-acceptance requires at least three validation cases")

    def contest(self, rule_id: str, *, reason: str,
                evidence: Iterable[Mapping[str, Any]] = ()) -> list[RuleRecord]:
        """Contest a rule and every dependent rule."""

        record = self.get(rule_id)
        affected: list[RuleRecord] = []

        def mark(target: RuleRecord) -> None:
            if target.state == "retired":
                return
            before = self._snapshot(target)
            if target.state != "contested":
                target.state = "contested"
            target.updated_at = _now()
            target.version += 1
            target.history.append({
                "at": target.updated_at,
                "action": "contest",
                "before": before,
                "detail": {
                    "reason": reason,
                    "evidence": [dict(item) for item in evidence],
                    "trigger": rule_id,
                },
            })
            affected.append(target)

        mark(record)
        for dependent in self.dependents(rule_id):
            mark(dependent)
        return affected

    def retire(self, rule_id: str, *, reason: str) -> list[RuleRecord]:
        """Retire a rule and contest its dependents (they lose support)."""

        record = self.get(rule_id)
        dependents = self.dependents(rule_id)
        before = self._snapshot(record)
        record.state = "retired"
        record.updated_at = _now()
        record.version += 1
        record.history.append({
            "at": record.updated_at,
            "action": "retire",
            "before": before,
            "detail": {"reason": reason},
        })
        affected = [record]
        if dependents:
            affected.extend(self.contest(
                rule_id, reason=f"dependency retired: {rule_id}"))
        return affected

    def record_use(self, rule_id: str, *, success: bool,
                   saved_work: int = 0) -> RuleRecord:
        record = self.get(rule_id)
        record.utility["applications"] += 1
        if success:
            record.utility["successes"] += 1
        else:
            record.utility["corrections"] += 1
        record.utility["saved_work"] += max(0, int(saved_work))
        record.utility["last_used"] = _now()
        record.updated_at = record.utility["last_used"]
        return record

    def rollback(self, rule_id: str) -> RuleRecord:
        """Undo the most recent real transition.

        Rollback records are audit entries, not transitions: repeated rollbacks
        walk further back through activation, validation, and proposal instead
        of undoing the previous rollback.
        """

        record = self.get(rule_id)
        index = None
        for position in range(len(record.history) - 1, -1, -1):
            entry = record.history[position]
            if entry.get("action") == "rollback":
                continue
            if entry.get("before") is None:
                continue
            index = position
            break
        if index is None:
            raise ValueError(f"rule has no prior state to restore: {rule_id!r}")
        entry = record.history[index]
        current = self._snapshot(record)
        self._restore(record, entry["before"])
        undone = record.history[index:]
        record.history = record.history[:index]
        record.updated_at = _now()
        record.version += 1
        record.history.append({
            "at": record.updated_at,
            "action": "rollback",
            "before": current,
            "detail": {
                "undone": [str(item.get("action")) for item in undone],
                "restored": entry.get("before"),
            },
        })
        return record

    # -- health ---------------------------------------------------------

    def health(self) -> dict[str, Any]:
        counts = {state: 0 for state in sorted(STATES)}
        families: dict[str, int] = {}
        active_without_validation = 0
        active_zero_utility = 0
        for record in self._records.values():
            counts[record.state] = counts.get(record.state, 0) + 1
            families[record.family] = families.get(record.family, 0) + 1
            if record.state == "active" and not record.validated:
                active_without_validation += 1
            if record.state == "active" and record.utility["applications"] == 0:
                active_zero_utility += 1
        duplicates = self._duplicate_groups()
        orphan_dependencies = [
            {"rule": record.id, "missing": dependency}
            for record in self._records.values()
            for dependency in record.dependencies
            if dependency not in self._records
        ]
        return {
            "total": len(self._records),
            "by_state": counts,
            "by_family": dict(sorted(families.items())),
            "active_without_validation": active_without_validation,
            "active_zero_utility": active_zero_utility,
            "duplicate_groups": duplicates,
            "orphan_dependencies": orphan_dependencies,
            "allow_scoped_auto": self.allow_scoped_auto,
        }

    def audit(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for group in self._duplicate_groups():
            issues.append({"kind": "duplicate", "rule_ids": group})
        for record in self._records.values():
            if record.state == "active" and not record.validated:
                issues.append({"kind": "active-without-validation", "rule": record.id})
            if record.state == "active" and record.trust == "derived":
                issues.append({"kind": "derived-active", "rule": record.id})
            for dependency in record.dependencies:
                if dependency not in self._records:
                    issues.append({
                        "kind": "orphan-dependency",
                        "rule": record.id,
                        "missing": dependency,
                    })
        return issues

    def _duplicate_groups(self) -> list[list[str]]:
        groups: dict[tuple[str, str, str], list[str]] = {}
        for record in self._records.values():
            if record.state == "retired":
                continue
            key = (record.family, record.statement, record.scope)
            groups.setdefault(key, []).append(record.id)
        return [sorted(ids) for ids in groups.values() if len(ids) > 1]

    # -- persistence ----------------------------------------------------

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS meta "
                    "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS rules "
                    "(id TEXT PRIMARY KEY, family TEXT NOT NULL, "
                    "state TEXT NOT NULL, payload TEXT NOT NULL, "
                    "updated_at TEXT NOT NULL)")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS history "
                    "(seq INTEGER PRIMARY KEY AUTOINCREMENT, rule_id TEXT NOT NULL, "
                    "action TEXT NOT NULL, at TEXT NOT NULL, "
                    "detail TEXT NOT NULL, before TEXT)")
                connection.execute("DELETE FROM rules")
                connection.execute("DELETE FROM history")
                connection.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                    ("format", json.dumps({"format": FORMAT, "version": VERSION})))
                connection.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                    ("allow_scoped_auto", json.dumps(self.allow_scoped_auto)))
                for record in self._records.values():
                    connection.execute(
                        "INSERT INTO rules(id, family, state, payload, updated_at) "
                        "VALUES(?, ?, ?, ?, ?)",
                        (record.id, record.family, record.state,
                         json.dumps(record.as_payload(), sort_keys=True),
                         record.updated_at))
                    for entry in record.history:
                        connection.execute(
                            "INSERT INTO history(rule_id, action, at, detail, before) "
                            "VALUES(?, ?, ?, ?, ?)",
                            (record.id, str(entry.get("action")), str(entry.get("at")),
                             json.dumps(entry.get("detail"), sort_keys=True),
                             json.dumps(entry.get("before"), sort_keys=True)))
        finally:
            connection.close()

    @classmethod
    def load(cls, path: str | Path) -> "RuleRegistry":
        source = Path(path)
        connection = sqlite3.connect(source)
        registry = cls()
        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))
            payload = json.loads(meta.get("format", "{}"))
            if payload.get("format") != FORMAT:
                raise ValueError(f"not a CRMS rule registry: {source}")
            if int(payload.get("version", 0)) > VERSION:
                raise ValueError(
                    f"rule registry version {payload.get('version')} is newer than {VERSION}")
            registry.allow_scoped_auto = json.loads(
                meta.get("allow_scoped_auto", "false"))
            rows = connection.execute(
                "SELECT id, payload FROM rules ORDER BY id").fetchall()
            for rule_id, raw in rows:
                data = json.loads(raw)
                data["history"] = []
                registry._records[rule_id] = RuleRecord(**data)
            history_rows = connection.execute(
                "SELECT rule_id, action, at, detail, before FROM history "
                "ORDER BY seq").fetchall()
            for rule_id, action, at, detail, before in history_rows:
                record = registry._records.get(rule_id)
                if record is None:
                    continue
                record.history.append({
                    "action": action,
                    "at": at,
                    "detail": json.loads(detail),
                    "before": json.loads(before) if before else None,
                })
        finally:
            connection.close()
        return registry

    # -- internal -------------------------------------------------------

    @staticmethod
    def _snapshot(record: RuleRecord) -> dict[str, Any]:
        return {
            "state": record.state,
            "trust": record.trust,
            "acceptance_mode": record.acceptance_mode,
            "validation": json.loads(json.dumps(record.validation)),
            "version": record.version,
        }

    @staticmethod
    def _restore(record: RuleRecord, snapshot: Mapping[str, Any]) -> None:
        record.state = str(snapshot.get("state", record.state))
        record.trust = str(snapshot.get("trust", record.trust))
        record.acceptance_mode = str(
            snapshot.get("acceptance_mode", record.acceptance_mode))
        record.validation = snapshot.get("validation")
        record.version = int(snapshot.get("version", record.version))
