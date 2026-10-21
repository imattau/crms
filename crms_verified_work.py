"""Learn governed rules only from independently replayed completed work.

A successful plan is evidence, not a license. The learner proposes a task-plan
or procedure rule with lineage, then asks a caller-supplied replay checker
whether the completed output is still correct. A failed replay cannot validate
the rule; a formerly active rule is contested by the registry's validation
transition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping

from crms_dependency import DependencyIndex
from crms_rule_registry import RuleRegistry


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(value)


@dataclass(frozen=True)
class VerificationOutcome:
    passed: bool
    cases: int
    independent_sources: int
    detail: str = ""


@dataclass(frozen=True)
class VerifiedWork:
    work_id: str
    request: str
    goal: str
    plan_id: str
    steps: tuple[Mapping[str, Any], ...]
    output: Any
    checks: tuple[Mapping[str, Any], ...] = ()
    provenance: tuple[Mapping[str, Any], ...] = ()

    def validate(self) -> None:
        for name in ("work_id", "request", "goal", "plan_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"verified work has no {name}")
        if any(character.isspace() for character in self.work_id.strip()):
            raise ValueError("work_id cannot contain whitespace")
        if not self.steps:
            raise ValueError("verified work needs at least one step")
        if not self.checks:
            raise ValueError("verified work needs at least one check")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "work_id": self.work_id,
            "request": self.request,
            "goal": self.goal,
            "plan_id": self.plan_id,
            "steps": [dict(step) for step in self.steps],
            "output": self.output,
            "checks": [dict(check) for check in self.checks],
            "provenance": [dict(item) for item in self.provenance],
        }


@dataclass(frozen=True)
class WorkLearningResult:
    rule_id: str
    state: str
    validation: dict[str, Any] | None
    dependency_id: str
    work_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "state": self.state,
            "validation": self.validation,
            "dependency_id": self.dependency_id,
            "work_id": self.work_id,
        }


def _rule_id(work: VerifiedWork, family: str, requested: str | None) -> str:
    if requested:
        return requested
    digest = hashlib.sha256(
        _canonical({"work": work.work_id, "goal": work.goal,
                    "family": family}).encode("utf-8")).hexdigest()[:16]
    return f"work-{digest}"


def learn_from_verified_work(
        work: VerifiedWork, registry: RuleRegistry,
        dependencies: DependencyIndex,
        verifier: Callable[[VerifiedWork], VerificationOutcome],
        *, rule_id: str | None = None,
        family: str = "task-plan",
        statement: str | None = None,
        scope: str = "",
        activate: bool = False) -> WorkLearningResult:
    """Propose, replay-check, and optionally review-activate one plan rule."""
    work.validate()
    if family not in {"task-plan", "procedure"}:
        raise ValueError("verified work can learn only task-plan or procedure rules")
    if not callable(verifier):
        raise TypeError("verifier must be callable")
    target = _rule_id(work, family, rule_id)
    work_node_id = "work:" + work.work_id
    dependencies.add_node(
        work_node_id, "work", trust="derived",
        payload={
            "request": work.request,
            "goal": work.goal,
            "plan_id": work.plan_id,
            "output": work.output,
            "checks": [dict(check) for check in work.checks],
        },
        provenance=work.provenance,
    )
    for step in work.steps:
        step_id = "plan-step:" + str(step.get("step_id") or step.get("id") or "")
        if step_id == "plan-step:":
            continue
        dependencies.add_node(
            step_id, "plan", trust="derived",
            payload=dict(step), provenance=work.provenance)
        dependencies.add_edge(step_id, work_node_id, relation="contains")
    payload = {
        "origin": "verified-work",
        "work_id": work.work_id,
        "request": work.request,
        "goal": work.goal,
        "plan_id": work.plan_id,
        "steps": [dict(step) for step in work.steps],
        "output": work.output,
        "checks": [dict(check) for check in work.checks],
        "lineage": {
            "work_id": work.work_id,
            "plan_id": work.plan_id,
            "provenance": [dict(item) for item in work.provenance],
        },
    }
    if target in registry:
        record = registry.get(target)
        if record.state == "retired":
            raise ValueError(f"cannot revise retired work rule: {target!r}")
        registry.revise(
            target, statement=statement or record.statement,
            payload=payload,
            provenance=tuple(work.provenance),
        )
    else:
        registry.propose(
            rule_id=target,
            family=family,
            statement=statement or f"verified plan for {work.goal}",
            scope=scope,
            payload=payload,
            provenance=tuple(work.provenance),
            trust="derived",
        )
    rule = registry.get(target)
    dependencies.add_rule(rule, dependencies=(work_node_id,))
    try:
        outcome = verifier(work)
        if not isinstance(outcome, VerificationOutcome):
            raise TypeError("verifier must return VerificationOutcome")
    except Exception as error:
        outcome = VerificationOutcome(
            False, 0, 0, f"verifier raised: {type(error).__name__}: {error}")
    registry.validate(
        target,
        oracle="verified-work-replay",
        passed=outcome.passed,
        cases=outcome.cases,
        independent_sources=outcome.independent_sources,
        detail=outcome.detail,
    )
    rule = registry.get(target)
    if outcome.passed and activate:
        if rule.state == "validated":
            registry.activate(target, mode="review", authoriser="phase4-review")
        rule = registry.get(target)
    if "rule:" + target in dependencies:
        dependencies.mark_state(
            "rule:" + target, rule.state,
            reason="verified-work validation")
    return WorkLearningResult(
        rule_id=target,
        state=rule.state,
        validation=dict(rule.validation or {}),
        dependency_id="rule:" + target,
        work_id=work.work_id,
    )
