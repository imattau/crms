"""Offline examiner loop for Phase 10 generation rules.

The teacher may propose a small JSON rule change. CRMS applies it to a copied
rule payload, reruns the frozen generation suite, and accepts it only when the
suite still passes, mean quality does not fall, and copy ratio does not rise
materially. The teacher never accepts its own proposal.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from crms_composition_memory import GenerationRuleStore
from crms_generation_rules import (
    DEFAULT_RULES_PATH, GenerationRuleError, GenerationRules,
    load_rules, rules_from_mapping,
)
from run_phase10_eval import FIXTURE, evaluate_fixture

FORMAT = "crms-phase10-teacher-proposal"
VERSION = 1


class ExaminerError(ValueError):
    """A teacher proposal or examiner operation is malformed."""


@dataclass(frozen=True)
class TeacherProposal:
    proposal_id: str
    model: str
    prompt_sha256: str
    rationale: str
    changes: tuple[Mapping[str, Any], ...]
    expected: str = ""

    def validate(self) -> None:
        if not self.proposal_id.strip():
            raise ExaminerError("proposal_id is required")
        if not self.model.strip():
            raise ExaminerError("model is required")
        if not self.rationale.strip():
            raise ExaminerError("rationale is required")
        if not self.changes:
            raise ExaminerError("at least one change is required")
        for change in self.changes:
            if change.get("op") not in {"set", "append_unique"}:
                raise ExaminerError(f"unsupported change op: {change.get('op')!r}")
            if not str(change.get("path", "")).strip():
                raise ExaminerError("change path is required")
            if "value" not in change:
                raise ExaminerError("change value is required")


def load_proposal(path: str | Path) -> TeacherProposal:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("format") != FORMAT or raw.get("version") != VERSION:
        raise ExaminerError("unsupported teacher proposal format")
    proposal = TeacherProposal(
        proposal_id=str(raw.get("proposal_id", "")),
        model=str(raw.get("model", "")),
        prompt_sha256=str(raw.get("prompt_sha256", "")),
        rationale=str(raw.get("rationale", "")),
        changes=tuple(dict(change) for change in raw.get("changes", ())),
        expected=str(raw.get("expected", "")),
    )
    proposal.validate()
    return proposal


def _parent(payload: Any, path: str) -> tuple[Any, str]:
    parts = [part for part in path.split(".") if part]
    if not parts:
        raise ExaminerError("empty change path")
    value = payload
    for part in parts[:-1]:
        if not isinstance(value, dict) or part not in value:
            raise ExaminerError(f"unknown change path prefix: {path!r}")
        value = value[part]
    return value, parts[-1]


def apply_changes(payload: Mapping[str, Any],
                  changes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]
                  ) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    for change in changes:
        target, key = _parent(result, str(change["path"]))
        if not isinstance(target, dict):
            raise ExaminerError(
                f"change parent is not an object: {change['path']!r}")
        op = change["op"]
        if op == "set":
            target[key] = deepcopy(change["value"])
        elif op == "append_unique":
            if not isinstance(target.get(key), list):
                raise ExaminerError(
                    f"append_unique target is not a list: {change['path']!r}")
            if change["value"] not in target[key]:
                target[key].append(deepcopy(change["value"]))
        else:
            raise ExaminerError(f"unsupported change op: {op!r}")
    return result


def _mean_score(report: Mapping[str, Any]) -> float:
    values = [row["critique"]["score"] for row in report["cases"]
              if row.get("critique")]
    return sum(values) / len(values) if values else 0.0


def _mean_copy(report: Mapping[str, Any]) -> float:
    values = [row["critique"]["copy_ratio"] for row in report["cases"]
              if row.get("critique")]
    return sum(values) / len(values) if values else 0.0


def evaluate_proposal(proposal: TeacherProposal, *,
                      fixture: Path = FIXTURE,
                      rules_path: Path = DEFAULT_RULES_PATH,
                      rules: GenerationRules | None = None) -> dict[str, Any]:
    """Apply, rerun, and accept or reject a teacher proposal."""
    base_rules = rules or load_rules(rules_path)
    base_payload = json.loads(rules_path.read_text(encoding="utf-8"))
    base_report = evaluate_fixture(fixture, base_rules)
    proposed_payload = apply_changes(base_payload, proposal.changes)
    try:
        proposed_rules = rules_from_mapping(
            proposed_payload, path=rules_path,
            digest=hashlib.sha256(
                json.dumps(proposed_payload, sort_keys=True,
                           ensure_ascii=False).encode("utf-8")).hexdigest())
    except GenerationRuleError as error:
        raise ExaminerError(f"proposal produced invalid rules: {error}") from error
    proposed_report = evaluate_fixture(fixture, proposed_rules)

    base_score = _mean_score(base_report)
    proposed_score = _mean_score(proposed_report)
    base_copy = _mean_copy(base_report)
    proposed_copy = _mean_copy(proposed_report)
    all_pass = proposed_report["gate_passed"]
    no_regression = proposed_score + 1e-9 >= base_score
    copy_ok = proposed_copy <= base_copy + 0.05
    accepted = bool(all_pass and no_regression and copy_ok)
    reasons = []
    if not all_pass:
        reasons.append("one or more frozen cases failed")
    if not no_regression:
        reasons.append("mean quality fell")
    if not copy_ok:
        reasons.append("copy ratio rose materially")
    return {
        "format": "crms-phase10-teacher-result",
        "version": 1,
        "proposal": {
            "proposal_id": proposal.proposal_id,
            "model": proposal.model,
            "prompt_sha256": proposal.prompt_sha256,
            "rationale": proposal.rationale,
            "changes": list(proposal.changes),
            "expected": proposal.expected,
        },
        "accepted": accepted,
        "reasons": reasons,
        "before": {
            "all_pass": base_report["gate_passed"],
            "mean_score": base_score,
            "mean_copy_ratio": base_copy,
            "rule_digest": base_rules.digest,
        },
        "after": {
            "all_pass": proposed_report["gate_passed"],
            "mean_score": proposed_score,
            "mean_copy_ratio": proposed_copy,
            "rule_digest": proposed_rules.digest,
        },
        "payload": proposed_payload,
        "report": proposed_report,
    }


def record_proposal(store: GenerationRuleStore,
                    result: Mapping[str, Any]) -> str:
    """Store the proposed snapshot and its judgment; return snapshot id."""
    proposal = result["proposal"]
    snapshot_id = store.put_snapshot(
        result["payload"], origin="teacher",
        rationale=str(proposal["rationale"]),
        accepted=bool(result["accepted"]),
        reference=str(proposal["proposal_id"]))
    store.record_judgment(
        snapshot_id=snapshot_id, source="teacher",
        score=float(result["after"]["mean_score"]),
        faithfulness=1.0 if result["after"]["all_pass"] else 0.0,
        clarity=1.0 if result["after"]["all_pass"] else 0.0,
        coverage=1.0 if result["after"]["all_pass"] else 0.0,
        model=str(proposal.get("model", "")),
        note="; ".join(result.get("reasons", ())) or "accepted by frozen checks",
    )
    return snapshot_id


def run_proposal(proposal_path: str | Path, *,
                 store: GenerationRuleStore | None = None) -> dict[str, Any]:
    proposal = load_proposal(proposal_path)
    result = evaluate_proposal(proposal)
    if store is not None:
        result["snapshot_id"] = record_proposal(store, result)
    return result
