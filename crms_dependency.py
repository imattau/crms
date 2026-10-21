"""Persistent dependency index for source, fact, schema, rule, and plan lineage.

The governed rule registry owns rule lifecycle. This module owns the wider
reverse index that connects sources to facts, facts to derived artifacts, and
artifacts to rules and plans. A correction enters here and propagates through
both the index and the registry, so a dependent rule cannot keep being used
after its support is gone.

Trust is ordered: ``taught`` > ``source-reviewed`` > ``derived``. A taught
conflict is authoritative. Derived evidence can propose and explain, but it
cannot win a conflict against a teacher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from crms_rule_registry import RuleRegistry

FORMAT = "crms-dependency-index"
VERSION = 1

NODE_KINDS = frozenset({
    "source", "fact", "schema", "procedure", "rule", "derived", "plan",
    "task", "work", "correction",
})
NODE_STATES = frozenset({
    "proposed", "validated", "active", "contested", "retired"})
EDGE_RELATIONS = frozenset({
    "supports", "derived_from", "uses", "contains", "revises", "merged_from",
})
TRUST_RANK = {"taught": 3, "source-reviewed": 2, "derived": 1}
TRUST_LEVELS = frozenset(TRUST_RANK)
RULE_ID_PREFIX = "rule:"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if any(character.isspace() for character in value.strip()):
        raise ValueError(f"{label} cannot contain whitespace: {value!r}")
    return value.strip()


def _trust(value: str) -> str:
    if value not in TRUST_LEVELS:
        raise ValueError(f"unknown trust level: {value!r}")
    return value


@dataclass
class DependencyNode:
    id: str
    kind: str
    trust: str = "derived"
    state: str = "active"
    provenance: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "trust": self.trust,
            "state": self.state,
            "provenance": copy.deepcopy(self.provenance),
            "payload": copy.deepcopy(self.payload),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DependencyNode":
        return cls(
            id=_id(str(raw.get("id", "")), "node id"),
            kind=str(raw.get("kind", "")),
            trust=_trust(str(raw.get("trust", "derived"))),
            state=str(raw.get("state", "active")),
            provenance=[dict(item) for item in raw.get("provenance", ())
                        if isinstance(item, Mapping)],
            payload=dict(raw.get("payload") or {}),
            created_at=str(raw.get("created_at", _now())),
            updated_at=str(raw.get("updated_at", _now())),
        )


@dataclass(frozen=True)
class CorrectionResult:
    trigger: str
    affected: tuple[str, ...]
    retained: tuple[str, ...]
    retired_sources: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "affected": list(self.affected),
            "retained": list(self.retained),
            "retired_sources": list(self.retired_sources),
            "affected_count": len(self.affected),
        }


class DependencyIndex:
    """SQLite-backed graph of evidence, artifacts, and governed rules."""

    def __init__(self, *, max_nodes: int = 20_000,
                 max_edges: int = 100_000) -> None:
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError("max_nodes must be a positive integer")
        if type(max_edges) is not int or max_edges < 1:
            raise ValueError("max_edges must be a positive integer")
        self.max_nodes = max_nodes
        self.max_edges = max_edges
        self._nodes: dict[str, DependencyNode] = {}
        self._edges: set[tuple[str, str, str]] = set()

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def get(self, node_id: str) -> DependencyNode:
        try:
            return self._nodes[node_id]
        except KeyError as error:
            raise KeyError(f"unknown dependency node: {node_id!r}") from error

    def add_node(self, node_id: str, kind: str, *, trust: str = "derived",
                 state: str = "active",
                 provenance: Iterable[Mapping[str, Any]] = (),
                 payload: Mapping[str, Any] | None = None
                 ) -> DependencyNode:
        node_id = _id(node_id, "node id")
        if kind not in NODE_KINDS:
            raise ValueError(f"unknown dependency node kind: {kind!r}")
        if state not in NODE_STATES:
            raise ValueError(f"unknown dependency node state: {state!r}")
        trust = _trust(trust)
        existing = self._nodes.get(node_id)
        if existing is not None:
            if existing.kind != kind:
                raise ValueError(
                    f"node {node_id!r} is already {existing.kind!r}, not {kind!r}")
            if existing.trust != trust:
                raise ValueError(
                    f"node {node_id!r} already has trust {existing.trust!r}")
            existing.provenance.extend(
                dict(item) for item in provenance
                if isinstance(item, Mapping)
                and dict(item) not in existing.provenance)
            if payload:
                existing.payload.update(dict(payload))
            existing.updated_at = _now()
            return existing
        node = DependencyNode(
            id=node_id, kind=kind, trust=trust, state=state,
            provenance=[dict(item) for item in provenance
                        if isinstance(item, Mapping)],
            payload=dict(payload or {}),
        )
        self._nodes[node_id] = node
        return node

    def add_edge(self, target: str, source: str, *,
                 relation: str = "derived_from") -> tuple[str, str, str]:
        target = _id(target, "target node")
        source = _id(source, "source node")
        if target not in self._nodes:
            raise KeyError(f"unknown target node: {target!r}")
        if source not in self._nodes:
            raise KeyError(f"unknown source node: {source!r}")
        if relation not in EDGE_RELATIONS:
            raise ValueError(f"unknown dependency relation: {relation!r}")
        edge = (target, source, relation)
        self._edges.add(edge)
        return edge

    def add_support(self, fact_id: str, source_id: str, *,
                    fact_payload: Mapping[str, Any] | None = None,
                    source_payload: Mapping[str, Any] | None = None,
                    trust: str = "source-reviewed",
                    provenance: Iterable[Mapping[str, Any]] = ()
                    ) -> DependencyNode:
        fact_id = _id(fact_id, "fact node")
        source_id = _id(source_id, "source node")
        self.add_node(source_id, "source", trust=trust,
                      payload=source_payload, provenance=provenance)
        node = self.add_node(fact_id, "fact", trust=trust,
                             payload=fact_payload, provenance=provenance)
        self.add_edge(fact_id, source_id, relation="supports")
        return node

    def add_derivation(self, derived_id: str, inputs: Iterable[str], *,
                       payload: Mapping[str, Any] | None = None,
                       trust: str = "derived",
                       provenance: Iterable[Mapping[str, Any]] = ()
                       ) -> DependencyNode:
        derived_id = _id(derived_id, "derived node")
        node = self.add_node(derived_id, "derived", trust=trust,
                             payload=payload, provenance=provenance)
        for input_id in inputs:
            self.add_edge(derived_id, _id(input_id, "input node"),
                          relation="derived_from")
        return node

    def add_rule(self, rule, *, dependencies: Iterable[str] = (),
                 payload: Mapping[str, Any] | None = None) -> DependencyNode:
        """Mirror a governed rule node and its explicit dependency edges."""
        node_id = RULE_ID_PREFIX + rule.id
        data = {"rule_id": rule.id, "family": rule.family,
                "statement": rule.statement, "scope": rule.scope}
        data.update(dict(payload or {}))
        node = self.add_node(
            node_id, "rule", trust=rule.trust, state=rule.state,
            provenance=rule.provenance, payload=data)
        for dependency in dependencies:
            self.add_edge(node_id, _id(dependency, "rule dependency"),
                          relation="derived_from")
        for dependency in rule.dependencies:
            dependency_id = (
                dependency if dependency.startswith(RULE_ID_PREFIX)
                or dependency in self._nodes
                else RULE_ID_PREFIX + dependency)
            if dependency_id in self._nodes:
                self.add_edge(node_id, dependency_id,
                              relation="derived_from")
        return node

    def dependents(self, node_id: str, *, transitive: bool = True
                   ) -> list[DependencyNode]:
        node_id = _id(node_id, "node id")
        if node_id not in self._nodes:
            raise KeyError(f"unknown dependency node: {node_id!r}")
        found: list[DependencyNode] = []
        seen = {node_id}
        frontier = [node_id]
        while frontier:
            current = frontier.pop(0)
            rows = sorted(
                target for target, source, _relation in self._edges
                if source == current and target not in seen)
            for target in rows:
                seen.add(target)
                found.append(self._nodes[target])
                if transitive:
                    frontier.append(target)
        return sorted(found, key=lambda node: (node.kind, node.id))

    def dependencies(self, node_id: str) -> list[tuple[DependencyNode, str]]:
        node_id = _id(node_id, "node id")
        if node_id not in self._nodes:
            raise KeyError(f"unknown dependency node: {node_id!r}")
        rows = sorted(
            (source, relation) for target, source, relation in self._edges
            if target == node_id)
        return [(self._nodes[source], relation) for source, relation in rows]

    def support_sources(self, fact_id: str) -> list[DependencyNode]:
        return [node for node, relation in self.dependencies(fact_id)
                if relation == "supports" and node.state == "active"]

    def mark_state(self, node_id: str, state: str, *,
                   reason: str = "") -> DependencyNode:
        if state not in NODE_STATES:
            raise ValueError(f"unknown dependency node state: {state!r}")
        node = self.get(node_id)
        node.state = state
        node.updated_at = _now()
        if reason:
            node.payload["state_reason"] = reason
        return node

    def contest(self, node_id: str, *, reason: str,
                registry: RuleRegistry | None = None,
                evidence: Iterable[Mapping[str, Any]] = ()
                ) -> CorrectionResult:
        """Contest one node and every reachable dependent.

        Rule nodes are also contested in the governed registry, including the
        registry's own rule-to-rule dependents. The returned list is the union
        of dependency-index nodes and registry-affected rules.
        """
        node_id = _id(node_id, "node id")
        if node_id not in self._nodes:
            raise KeyError(f"unknown dependency node: {node_id!r}")
        evidence_rows = [dict(item) for item in evidence
                         if isinstance(item, Mapping)]
        affected: list[str] = []
        seen: set[str] = set()
        frontier = [node_id]
        while frontier:
            current = frontier.pop(0)
            if current in seen:
                continue
            seen.add(current)
            node = self._nodes[current]
            if node.state != "retired":
                node.state = "contested"
                node.updated_at = _now()
                node.payload["contest_reason"] = reason
                node.payload["contest_evidence"] = evidence_rows
                if current not in affected:
                    affected.append(current)
                if registry is not None and node.kind == "rule":
                    rule_id = str(node.payload.get("rule_id") or
                                  current[len(RULE_ID_PREFIX):])
                    if rule_id in registry:
                        for record in registry.contest(
                                rule_id, reason=reason, evidence=evidence_rows):
                            rule_node = RULE_ID_PREFIX + record.id
                            if rule_node not in affected:
                                affected.append(rule_node)
                            if rule_node in self._nodes:
                                self._nodes[rule_node].state = record.state
                                self._nodes[rule_node].updated_at = _now()
            for target, source, _relation in sorted(self._edges):
                if source == current and target not in seen:
                    frontier.append(target)
        return CorrectionResult(
            trigger=node_id, affected=tuple(sorted(affected)),
            retained=(), retired_sources=())

    def retract_source(self, source_id: str, *,
                       registry: RuleRegistry | None = None,
                       reason: str = "source retracted"
                       ) -> CorrectionResult:
        """Retract one source and contest only artifacts left unsupported."""
        source_id = _id(source_id, "source id")
        if source_id not in self._nodes:
            raise KeyError(f"unknown dependency node: {source_id!r}")
        source = self._nodes[source_id]
        if source.kind != "source":
            raise ValueError(f"{source_id!r} is not a source node")
        source.state = "retired"
        source.updated_at = _now()
        source.payload["state_reason"] = reason
        direct = sorted(
            target for target, origin, relation in self._edges
            if origin == source_id and relation == "supports")
        affected: list[str] = []
        retained: list[str] = []
        for fact_id in direct:
            if self.support_sources(fact_id):
                retained.append(fact_id)
                self._nodes[fact_id].payload["last_retained_source"] = source_id
                continue
            result = self.contest(
                fact_id, reason=reason, registry=registry,
                evidence=({"source": source_id},))
            affected.extend(result.affected)
        # A rule or derived artifact may cite the source directly.
        for target, origin, relation in sorted(self._edges):
            if origin == source_id and relation != "supports":
                result = self.contest(
                    target, reason=reason, registry=registry,
                    evidence=({"source": source_id},))
                affected.extend(result.affected)
        return CorrectionResult(
            trigger=source_id,
            affected=tuple(sorted(set(affected))),
            retained=tuple(sorted(set(retained))),
            retired_sources=(source_id,),
        )

    def retire(self, node_id: str, *, reason: str,
               registry: RuleRegistry | None = None) -> CorrectionResult:
        node = self.get(node_id)
        node.state = "retired"
        node.updated_at = _now()
        node.payload["state_reason"] = reason
        affected = [node_id]
        if registry is not None and node.kind == "rule":
            rule_id = str(node.payload.get("rule_id") or
                          node_id[len(RULE_ID_PREFIX):])
            if rule_id in registry:
                for record in registry.retire(rule_id, reason=reason):
                    rule_node = RULE_ID_PREFIX + record.id
                    if rule_node in self._nodes:
                        self._nodes[rule_node].state = record.state
                    affected.append(rule_node)
        for dependent in self.dependents(node_id):
            if dependent.state != "retired":
                dependent.state = "contested"
                dependent.updated_at = _now()
                affected.append(dependent.id)
                if registry is not None and dependent.kind == "rule":
                    rule_id = str(dependent.payload.get("rule_id") or
                                  dependent.id[len(RULE_ID_PREFIX):])
                    if rule_id in registry:
                        registry.contest(rule_id, reason=f"dependency retired: {node_id}")
        return CorrectionResult(
            trigger=node_id, affected=tuple(sorted(set(affected))),
            retained=())

    @staticmethod
    def resolve_trust_conflict(
            claims: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Resolve competing claims by trust; taught wins authoritatively."""
        rows = [dict(item) for item in claims]
        for row in rows:
            _trust(str(row.get("trust", "")))
        if not rows:
            return {"status": "empty", "selected": None, "losers": [],
                    "winners": []}
        best = max(TRUST_RANK[str(row["trust"])] for row in rows)
        winners = [row for row in rows
                   if TRUST_RANK[str(row["trust"])] == best]
        losers = [row for row in rows
                  if TRUST_RANK[str(row["trust"])] < best]
        if len(winners) == 1:
            return {
                "status": "selected",
                "selected": winners[0],
                "winners": winners,
                "losers": losers,
                "trust": winners[0]["trust"],
            }
        return {
            "status": "ambiguous",
            "selected": None,
            "winners": winners,
            "losers": losers,
            "trust": winners[0]["trust"],
        }

    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        by_state: dict[str, int] = {}
        for node in self._nodes.values():
            by_kind[node.kind] = by_kind.get(node.kind, 0) + 1
            by_state[node.state] = by_state.get(node.state, 0) + 1
        return {
            "nodes": len(self._nodes),
            "edges": len(self._edges),
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "by_kind": dict(sorted(by_kind.items())),
            "by_state": dict(sorted(by_state.items())),
            "within_bound": (len(self._nodes) <= self.max_nodes
                             and len(self._edges) <= self.max_edges),
        }

    def prune(self) -> int:
        """Enforce storage bounds by removing old non-rule and retired nodes."""
        removed = 0
        while len(self._nodes) > self.max_nodes or len(self._edges) > self.max_edges:
            candidates = [
                node for node in self._nodes.values()
                if not (node.kind == "rule" and node.state == "active")
                and (node.state in {"retired", "contested"}
                     or not self.dependents(node.id, transitive=False))
            ]
            if not candidates:
                candidates = [
                    node for node in self._nodes.values()
                    if node.kind != "rule" or node.state != "active"
                ]
            if not candidates:
                break
            victim = min(candidates, key=lambda node: (node.created_at, node.id))
            del self._nodes[victim.id]
            self._edges = {
                edge for edge in self._edges
                if victim.id not in (edge[0], edge[1])
            }
            removed += 1
        return removed

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
                    "CREATE TABLE IF NOT EXISTS nodes "
                    "(id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                    "state TEXT NOT NULL, payload TEXT NOT NULL)")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS edges "
                    "(target TEXT NOT NULL, source TEXT NOT NULL, "
                    "relation TEXT NOT NULL, PRIMARY KEY(target, source, relation))")
                connection.execute("DELETE FROM meta")
                connection.execute("DELETE FROM nodes")
                connection.execute("DELETE FROM edges")
                connection.execute(
                    "INSERT INTO meta VALUES(?,?)",
                    ("format", json.dumps({"format": FORMAT, "version": VERSION})))
                connection.execute(
                    "INSERT INTO meta VALUES(?,?)",
                    ("limits", json.dumps({
                        "max_nodes": self.max_nodes,
                        "max_edges": self.max_edges})))
                connection.executemany(
                    "INSERT INTO nodes VALUES(?,?,?,?)",
                    ((node.id, node.kind, node.state,
                      json.dumps(node.to_dict(), sort_keys=True))
                     for node in self._nodes.values()))
                connection.executemany(
                    "INSERT INTO edges VALUES(?,?,?)",
                    sorted(self._edges))
        finally:
            connection.close()

    @classmethod
    def load(cls, path: str | Path) -> "DependencyIndex":
        source = Path(path)
        connection = sqlite3.connect(source)
        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))
            payload = json.loads(meta.get("format", "{}"))
            if payload.get("format") != FORMAT:
                raise ValueError(f"not a CRMS dependency index: {source}")
            if int(payload.get("version", 0)) > VERSION:
                raise ValueError(
                    f"dependency index version {payload.get('version')} is newer")
            limits = json.loads(meta.get("limits", "{}"))
            index = cls(
                max_nodes=int(limits.get("max_nodes", 20_000)),
                max_edges=int(limits.get("max_edges", 100_000)))
            for rule_id, kind, state, raw in connection.execute(
                    "SELECT id, kind, state, payload FROM nodes ORDER BY id"):
                node = DependencyNode.from_dict(json.loads(raw))
                if node.kind != kind or node.state != state:
                    raise ValueError("stored dependency node disagrees with index")
                index._nodes[node.id] = node
            index._edges = {
                (target, origin, relation)
                for target, origin, relation in connection.execute(
                    "SELECT target, source, relation FROM edges")
            }
            return index
        finally:
            connection.close()

    def copy(self) -> "DependencyIndex":
        """Return an isolated deep copy suitable for a model copy."""
        return copy.deepcopy(self)

    def __deepcopy__(self, memo) -> "DependencyIndex":
        clone = type(self)(max_nodes=self.max_nodes, max_edges=self.max_edges)
        memo[id(self)] = clone
        clone._nodes = copy.deepcopy(self._nodes, memo)
        clone._edges = set(self._edges)
        return clone
