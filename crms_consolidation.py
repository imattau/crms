"""Consolidation for governed rules: dedupe, merge, conflict audit, retirement.

Consolidation never invents evidence. It chooses one surviving rule among
equivalent records, moves dependencies to it, preserves the union of
provenance, and retires records whose measured utility has been zero for a
configured window. Cross-mechanism conflicts are reported, not silently
resolved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Iterable, Mapping

from crms_dependency import DependencyIndex, TRUST_RANK
from crms_rule_registry import RuleRecord, RuleRegistry


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _rank(record: RuleRecord) -> tuple[int, int, int, int, str]:
    state_rank = {
        "active": 4, "validated": 3, "proposed": 2, "contested": 1,
        "retired": 0,
    }
    return (
        TRUST_RANK.get(record.trust, 0),
        state_rank.get(record.state, 0),
        int(record.utility.get("applications", 0)),
        int(record.utility.get("successes", 0)),
        record.id,
    )


@dataclass
class ConsolidationReport:
    merged: list[dict[str, Any]] = field(default_factory=list)
    retired_duplicates: list[str] = field(default_factory=list)
    compatible_merges: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    retired_zero_utility: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "merged_groups": len(self.merged),
            "merged": self.merged,
            "retired_duplicates": self.retired_duplicates,
            "compatible_merges": self.compatible_merges,
            "conflicts": self.conflicts,
            "retired_zero_utility": self.retired_zero_utility,
            "kept": self.kept,
        }


def _merge_into(canonical: RuleRecord, duplicate: RuleRecord,
                registry: RuleRegistry,
                dependencies: DependencyIndex | None) -> None:
    provenance = []
    seen = set()
    for item in list(canonical.provenance) + list(duplicate.provenance):
        signature = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            provenance.append(dict(item))
    merged_from = list(canonical.payload.get("merged_from", ()))
    if duplicate.id not in merged_from:
        merged_from.append(duplicate.id)
    payload = dict(canonical.payload)
    payload["merged_from"] = sorted(merged_from)
    registry.revise(
        canonical.id,
        payload=payload,
        provenance=provenance,
    )
    # Dependents of the duplicate now point at the survivor.
    for record in registry.records():
        if duplicate.id in record.dependencies:
            registry.revise(
                record.id,
                dependencies=[
                    canonical.id if item == duplicate.id else item
                    for item in record.dependencies
                ],
            )
    registry.retire(
        duplicate.id,
        reason=f"consolidated into {canonical.id}: duplicate evidence")
    if dependencies is not None:
        node_id = "rule:" + duplicate.id
        if node_id in dependencies:
            dependencies.mark_state(node_id, "retired",
                                    reason=f"consolidated into {canonical.id}")
        canonical_node = "rule:" + canonical.id
        if canonical_node in dependencies:
            duplicate_node = node_id
            if duplicate_node in dependencies:
                dependencies.add_edge(
                    canonical_node, duplicate_node, relation="merged_from")


def consolidate(registry: RuleRegistry, *,
                dependencies: DependencyIndex | None = None,
                zero_utility_days: int = 30,
                now: datetime | None = None) -> ConsolidationReport:
    if type(zero_utility_days) is not int or zero_utility_days < 0:
        raise ValueError("zero_utility_days must be a non-negative integer")
    if now is not None and not isinstance(now, datetime):
        raise ValueError("now must be a datetime or None")
    moment = now or _now()
    report = ConsolidationReport()

    # Exact duplicate groups: same family, statement, and scope.
    groups: dict[tuple[str, str, str], list[RuleRecord]] = {}
    for record in registry.records():
        if record.state == "retired":
            continue
        key = (record.family, record.statement.strip().casefold(),
               record.scope.strip().casefold())
        groups.setdefault(key, []).append(record)
    for key, rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        canonical = max(rows, key=_rank)
        for duplicate in sorted(rows, key=lambda row: row.id):
            if duplicate.id == canonical.id:
                continue
            _merge_into(canonical, duplicate, registry, dependencies)
            report.retired_duplicates.append(duplicate.id)
        report.merged.append({
            "canonical": canonical.id,
            "retired": [row.id for row in rows if row.id != canonical.id],
            "family": canonical.family,
        })

    # Compatible merge groups are explicit: same family/scope and merge_key,
    # but potentially different wording. A merge_key is evidence that the
    # records describe the same mechanism, not merely similar words.
    compatible: dict[tuple[str, str, str], list[RuleRecord]] = {}
    for record in registry.records(state="active"):
        merge_key = str(record.payload.get("merge_key", "")).strip()
        if not merge_key:
            continue
        compatible.setdefault(
            (record.family, record.scope.strip().casefold(), merge_key),
            []).append(record)
    for key, rows in sorted(compatible.items()):
        if len(rows) < 2:
            continue
        canonical = max(rows, key=_rank)
        for duplicate in sorted(rows, key=lambda row: row.id):
            if duplicate.id == canonical.id:
                continue
            _merge_into(canonical, duplicate, registry, dependencies)
            report.retired_duplicates.append(duplicate.id)
        report.compatible_merges.append({
            "canonical": canonical.id,
            "retired": [row.id for row in rows if row.id != canonical.id],
            "merge_key": key[2],
        })

    # Cross-mechanism conflicts are visible and left for review.
    conflicts: dict[tuple[str, str, str], list[RuleRecord]] = {}
    for record in registry.records(state="active"):
        conflict_key = str(record.payload.get("conflict_key", "")).strip()
        if not conflict_key:
            continue
        conflicts.setdefault(
            (record.family, record.scope.strip().casefold(), conflict_key),
            []).append(record)
    for key, rows in sorted(conflicts.items()):
        signatures = {
            json.dumps({
                "value": row.payload.get("value"),
                "polarity": row.payload.get("polarity"),
                "outcome": row.payload.get("outcome"),
            }, sort_keys=True, ensure_ascii=False)
            for row in rows
        }
        if len(signatures) > 1:
            report.conflicts.append({
                "family": key[0],
                "scope": key[1],
                "conflict_key": key[2],
                "rules": sorted(row.id for row in rows),
                "signatures": sorted(signatures),
            })

    # Zero utility over a measured window is not evidence of correctness; it
    # is evidence of no demonstrated use. Retire only old active records.
    cutoff = moment - timedelta(days=zero_utility_days)
    for record in list(registry.records(state="active")):
        created = _parse(record.created_at)
        if created is None or created > cutoff:
            continue
        if int(record.utility.get("applications", 0)) != 0:
            continue
        registry.retire(
            record.id,
            reason=f"zero utility for {zero_utility_days} days")
        report.retired_zero_utility.append(record.id)
        if dependencies is not None:
            node_id = "rule:" + record.id
            if node_id in dependencies:
                dependencies.mark_state(node_id, "retired",
                                        reason="zero-utility consolidation")

    report.kept = sorted(
        record.id for record in registry.records(state="active"))
    return report
