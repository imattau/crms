"""Corrections and failures become scoped negatives plus proposed revisions.

A correction is teacher evidence. It is authoritative for conflict resolution,
but the resulting rule revision still enters the governed registry as
``proposed``. A failure without an identified rule creates the scoped negative
example and does not pretend a revision is known.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from crms_dependency import DependencyIndex
from crms_rule_registry import RuleRegistry


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


@dataclass(frozen=True)
class ScopedNegativeExample:
    id: str
    target: str
    scope: str
    excluded: Any
    reason: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "scope": self.scope,
            "excluded": self.excluded,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class CorrectionRecord:
    correction_id: str
    negative: ScopedNegativeExample
    revision_rule_id: str | None
    revision_state: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "correction_id": self.correction_id,
            "negative": self.negative.as_dict(),
            "revision_rule_id": self.revision_rule_id,
            "revision_state": self.revision_state,
        }


def _id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def learn_from_correction(
        correction_id: str, *, target_rule: str, scope: str,
        excluded: Any, corrected: Any, source: str, reason: str,
        registry: RuleRegistry, dependencies: DependencyIndex,
        revision_rule_id: str | None = None) -> CorrectionRecord:
    """Record one correction and propose a scoped revision when possible."""
    if not all(isinstance(value, str) and value.strip()
               for value in (correction_id, target_rule, scope, source, reason)):
        raise ValueError("correction fields must be non-empty strings")
    if target_rule not in registry:
        raise ValueError(f"correction target is not a governed rule: {target_rule!r}")
    target = registry.get(target_rule)
    if target.state == "retired":
        raise ValueError(f"correction target is retired: {target_rule!r}")
    dependencies.add_rule(target)
    negative = ScopedNegativeExample(
        id=_id("negative", _canonical({
            "target": target_rule, "scope": scope,
            "excluded": excluded, "source": source})),
        target=target_rule,
        scope=scope,
        excluded=excluded,
        reason=reason,
        source=source,
    )
    correction_node = dependencies.add_node(
        "correction:" + correction_id, "correction", trust="taught",
        payload={
            "target_rule": target_rule,
            "scope": scope,
            "excluded": excluded,
            "corrected": corrected,
            "negative": negative.as_dict(),
            "reason": reason,
        },
        provenance=({"source": source, "kind": "correction"},))
    revision_id = revision_rule_id or (target_rule + "-revision")
    if revision_id in registry:
        revision = registry.get(revision_id)
        if revision.state != "retired":
            registry.revise(
                revision_id,
                payload={
                    **dict(revision.payload),
                    "correction_id": correction_id,
                    "negative": negative.as_dict(),
                    "corrected": corrected,
                },
                provenance=tuple(revision.provenance) + (
                    {"source": source, "kind": "correction"},),
            )
    else:
        payload = dict(target.payload)
        payload.update({
            "correction_id": correction_id,
            "negative": negative.as_dict(),
            "corrected": corrected,
            "origin": "correction",
        })
        registry.propose(
            rule_id=revision_id,
            family=target.family,
            statement=target.statement,
            scope=scope,
            payload=payload,
            provenance=(
                {"source": source, "kind": "correction"},
                {"target": target_rule, "scope": scope},
            ),
            trust="taught",
            dependencies=(target_rule,),
        )
    revision = registry.get(revision_id)
    dependencies.add_rule(
        revision, dependencies=("rule:" + target_rule, correction_node.id))
    dependencies.add_edge(
        "rule:" + revision_id, correction_node.id, relation="revises")
    return CorrectionRecord(
        correction_id=correction_id,
        negative=negative,
        revision_rule_id=revision_id,
        revision_state=revision.state,
    )


def learn_from_failure(
        failure_id: str, *, request: str, action: str, reason: str,
        scope: str, target_rule: str | None, source: str,
        registry: RuleRegistry,
        dependencies: DependencyIndex) -> CorrectionRecord:
    """Record a failed plan as a scoped negative; revise only if identifiable."""
    if not all(isinstance(value, str) and value.strip()
               for value in (failure_id, request, action, reason, scope, source)):
        raise ValueError("failure fields must be non-empty strings")
    identifier = _id("negative", _canonical({
        "failure": failure_id, "scope": scope, "action": action,
        "reason": reason, "source": source}))
    negative = ScopedNegativeExample(
        id=identifier, target=target_rule or action, scope=scope,
        excluded={"request": request, "action": action, "reason": reason},
        reason=reason, source=source)
    node = dependencies.add_node(
        "failure:" + failure_id, "correction", trust="taught",
        payload={
            "request": request,
            "action": action,
            "reason": reason,
            "negative": negative.as_dict(),
        },
        provenance=({"source": source, "kind": "failure"},))
    revision_id = None
    revision_state = None
    if target_rule and target_rule in registry:
        revision_id = target_rule + "-failure-revision"
        target = registry.get(target_rule)
        dependencies.add_rule(target)
        if revision_id in registry:
            revision = registry.get(revision_id)
            if revision.state != "retired":
                registry.revise(
                    revision_id,
                    payload={**dict(revision.payload),
                             "negative": negative.as_dict()},
                    provenance=tuple(revision.provenance) + (
                        {"source": source, "kind": "failure"},),
                )
        else:
            payload = dict(target.payload)
            payload.update({"negative": negative.as_dict(),
                            "origin": "failure-revision"})
            registry.propose(
                rule_id=revision_id,
                family=target.family,
                statement=target.statement,
                scope=scope,
                payload=payload,
                provenance=({"source": source, "kind": "failure"},),
                trust="source-reviewed",
                dependencies=(target_rule,),
            )
        revision = registry.get(revision_id)
        dependencies.add_rule(
            revision, dependencies=("rule:" + target_rule, node.id))
        revision_state = revision.state
    return CorrectionRecord(
        correction_id=failure_id,
        negative=negative,
        revision_rule_id=revision_id,
        revision_state=revision_state,
    )
