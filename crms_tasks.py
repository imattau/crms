"""Typed task, plan, and verification records for CRMS composition.

The task IR is the shared seam between natural language and typed operations.
A request is compiled into a plan of explicit steps; every step names an
action, its inputs, the evidence it relies on, and the check that must pass
before its output is used. A plan is bounded, deterministic, serializable, and
inspectable.

This module defines data and invariants only. Planning and execution live in
``crms_planner.py`` when they land.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

FORMAT = "crms-task-ir"
VERSION = 1
MAX_STEPS = 6

EVIDENCE_KINDS = frozenset({
    "fact", "source", "proof", "procedure", "rule", "computation",
    "translation", "generated-code",
})
CHECK_KINDS = frozenset({
    "exact", "set", "proof", "citation", "parity", "oracle", "domain",
})
RESULT_STATUSES = frozenset({
    "ok", "not_planned", "unsupported", "ambiguous", "verification_failed",
    "execution_failed",
})
STEP_STATUSES = frozenset({"ok", "failed", "skipped"})


class TaskIRError(ValueError):
    """A task, plan, or result violates the typed contract."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _slug(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskIRError(f"{label} must be a non-empty string")
    if any(character.isspace() for character in value.strip()):
        raise TaskIRError(f"{label} must be a slug without whitespace: {value!r}")
    return value.strip()


def _mapping(value: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TaskIRError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    ref: str
    source: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise TaskIRError(f"unknown evidence kind: {self.kind!r}")
        if not self.ref.strip():
            raise TaskIRError("evidence ref cannot be empty")
        if self.source is not None and not self.source.strip():
            raise TaskIRError("evidence source cannot be blank")
        if not isinstance(self.detail, Mapping):
            raise TaskIRError("evidence detail must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kind": self.kind,
            "ref": self.ref,
            "source": self.source,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "EvidenceRef":
        item = cls(
            kind=str(raw.get("kind", "")),
            ref=str(raw.get("ref", "")),
            source=(str(raw["source"]) if raw.get("source") is not None else None),
            detail=_mapping(raw.get("detail"), "evidence detail"),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class CheckSpec:
    kind: str
    ref: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in CHECK_KINDS:
            raise TaskIRError(f"unknown check kind: {self.kind!r}")
        if self.ref is not None and not self.ref.strip():
            raise TaskIRError("check ref cannot be blank")
        if not isinstance(self.parameters, Mapping):
            raise TaskIRError("check parameters must be a mapping")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kind": self.kind,
            "ref": self.ref,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CheckSpec":
        item = cls(
            kind=str(raw.get("kind", "")),
            ref=(str(raw["ref"]) if raw.get("ref") is not None else None),
            parameters=_mapping(raw.get("parameters"), "check parameters"),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class TaskRequest:
    id: str
    text: str
    goal: str
    slots: dict[str, Any] = field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _slug(self.id, "request id")
        if not self.text.strip():
            raise TaskIRError("request text cannot be empty")
        _slug(self.goal, "request goal")
        if not isinstance(self.slots, Mapping):
            raise TaskIRError("request slots must be a mapping")
        if not isinstance(self.provenance, Mapping):
            raise TaskIRError("request provenance must be a mapping")
        for constraint in self.constraints:
            if not isinstance(constraint, str) or not constraint.strip():
                raise TaskIRError("request constraints must be non-empty strings")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "text": self.text,
            "goal": self.goal,
            "slots": dict(self.slots),
            "constraints": list(self.constraints),
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TaskRequest":
        item = cls(
            id=str(raw.get("id", "")),
            text=str(raw.get("text", "")),
            goal=str(raw.get("goal", "")),
            slots=_mapping(raw.get("slots"), "request slots"),
            constraints=tuple(str(value) for value in raw.get("constraints", ())),
            provenance=_mapping(raw.get("provenance"), "request provenance"),
        )
        item.validate()
        return item


def request_id(text: str, goal: str) -> str:
    digest = hashlib.sha256(
        _canonical({"text": " ".join(text.casefold().split()), "goal": goal})
        .encode("utf-8")).hexdigest()[:12]
    return f"task-{digest}"


@dataclass(frozen=True)
class Step:
    id: str
    action: str
    inputs: dict[str, Any]
    output_type: str
    evidence: tuple[EvidenceRef, ...] = ()
    check: CheckSpec = field(default_factory=lambda: CheckSpec("exact"))
    depends_on: tuple[str, ...] = ()

    def validate(self) -> None:
        _slug(self.id, "step id")
        _slug(self.action, "step action")
        if not self.output_type.strip():
            raise TaskIRError("step output_type cannot be empty")
        if not isinstance(self.inputs, Mapping):
            raise TaskIRError("step inputs must be a mapping")
        for item in self.evidence:
            item.validate()
        self.check.validate()
        for dependency in self.depends_on:
            _slug(dependency, "step dependency")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "id": self.id,
            "action": self.action,
            "inputs": dict(self.inputs),
            "output_type": self.output_type,
            "evidence": [item.to_dict() for item in self.evidence],
            "check": self.check.to_dict(),
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Step":
        item = cls(
            id=str(raw.get("id", "")),
            action=str(raw.get("action", "")),
            inputs=_mapping(raw.get("inputs"), "step inputs"),
            output_type=str(raw.get("output_type", "")),
            evidence=tuple(
                EvidenceRef.from_dict(entry)
                for entry in raw.get("evidence", ())),
            check=CheckSpec.from_dict(raw.get("check", {"kind": "exact"})),
            depends_on=tuple(str(value) for value in raw.get("depends_on", ())),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class Plan:
    request: TaskRequest
    steps: tuple[Step, ...]
    verification: CheckSpec | None = None
    format_version: int = VERSION

    def validate(self) -> None:
        if self.format_version != VERSION:
            raise TaskIRError(
                f"unsupported task IR version: {self.format_version}")
        self.request.validate()
        if not self.steps:
            raise TaskIRError("a plan must contain at least one step")
        if len(self.steps) > MAX_STEPS:
            raise TaskIRError(
                f"a plan may contain at most {MAX_STEPS} steps; "
                f"found {len(self.steps)}")
        seen: set[str] = set()
        for position, step in enumerate(self.steps):
            step.validate()
            if step.id in seen:
                raise TaskIRError(f"duplicate step id: {step.id!r}")
            for dependency in step.depends_on:
                if dependency not in seen:
                    raise TaskIRError(
                        f"step {step.id!r} depends on {dependency!r}, which "
                        "does not appear earlier in the plan")
            seen.add(step.id)
        if self.verification is not None:
            self.verification.validate()

    @property
    def artifact_id(self) -> str:
        self.validate()
        digest = hashlib.sha256(
            _canonical(self.to_dict()).encode("utf-8")).hexdigest()[:16]
        return f"plan-{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": self.format_version,
            "request": self.request.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "verification": (self.verification.to_dict()
                             if self.verification is not None else None),
        }

    def to_json(self) -> str:
        self.validate()
        return json.dumps(self.to_dict(), indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Plan":
        if raw.get("format") != FORMAT:
            raise TaskIRError(f"not a CRMS task plan: {raw.get('format')!r}")
        item = cls(
            request=TaskRequest.from_dict(raw.get("request", {})),
            steps=tuple(Step.from_dict(step) for step in raw.get("steps", ())),
            verification=(CheckSpec.from_dict(raw["verification"])
                          if raw.get("verification") is not None else None),
            format_version=int(raw.get("version", VERSION)),
        )
        item.validate()
        return item

    @classmethod
    def from_json(cls, text: str) -> "Plan":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            raise TaskIRError(f"invalid plan JSON: {error}") from error
        if not isinstance(raw, Mapping):
            raise TaskIRError("plan JSON must be an object")
        return cls.from_dict(raw)


@dataclass(frozen=True)
class StepResult:
    step_id: str
    status: str
    output: Any = None
    evidence: tuple[EvidenceRef, ...] = ()
    detail: str = ""
    reason_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _slug(self.step_id, "step result id")
        if self.status not in STEP_STATUSES:
            raise TaskIRError(f"unknown step result status: {self.status!r}")
        for item in self.evidence:
            item.validate()
        if self.reason_code:
            _slug(self.reason_code, "step reason code")
        if not isinstance(self.metadata, Mapping):
            raise TaskIRError("step result metadata must be a mapping")
        if self.status == "ok" and self.output is None:
            raise TaskIRError(
                f"successful step {self.step_id!r} has no output")
        if self.status == "failed" and not self.detail.strip():
            raise TaskIRError(
                f"failed step {self.step_id!r} requires a detail")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "step_id": self.step_id,
            "status": self.status,
            "output": self.output,
            "evidence": [item.to_dict() for item in self.evidence],
            "detail": self.detail,
            "reason_code": self.reason_code,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StepResult":
        item = cls(
            step_id=str(raw.get("step_id", "")),
            status=str(raw.get("status", "")),
            output=raw.get("output"),
            evidence=tuple(
                EvidenceRef.from_dict(entry)
                for entry in raw.get("evidence", ())),
            detail=str(raw.get("detail", "")),
            reason_code=str(raw.get("reason_code", "")),
            metadata=_mapping(raw.get("metadata"), "step result metadata"),
        )
        item.validate()
        return item


@dataclass(frozen=True)
class PlanResult:
    status: str
    plan: Plan | None = None
    output: Any = None
    steps: tuple[StepResult, ...] = ()
    failures: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise TaskIRError(f"unknown plan result status: {self.status!r}")
        if self.plan is not None:
            self.plan.validate()
        for step in self.steps:
            step.validate()
        if self.status == "ok":
            if self.plan is None:
                raise TaskIRError("an ok result requires a plan")
            if self.output is None:
                raise TaskIRError("an ok result requires an output")
            if self.failures:
                raise TaskIRError("an ok result cannot carry failures")
            planned = [step.id for step in self.plan.steps]
            completed = [step.step_id for step in self.steps
                         if step.status == "ok"]
            if completed != planned:
                raise TaskIRError(
                    "an ok result requires every planned step to complete")
        elif self.status in {"verification_failed", "execution_failed"}:
            if not self.failures:
                raise TaskIRError(
                    f"a {self.status.replace('_', ' ')} requires at least one reason")
        elif self.steps:
            raise TaskIRError(
                f"a {self.status!r} result cannot carry executed steps")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "status": self.status,
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "output": self.output,
            "steps": [step.to_dict() for step in self.steps],
            "failures": list(self.failures),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PlanResult":
        item = cls(
            status=str(raw.get("status", "")),
            plan=(Plan.from_dict(raw["plan"])
                  if raw.get("plan") is not None else None),
            output=raw.get("output"),
            steps=tuple(
                StepResult.from_dict(step) for step in raw.get("steps", ())),
            failures=tuple(str(value) for value in raw.get("failures", ())),
        )
        item.validate()
        return item
