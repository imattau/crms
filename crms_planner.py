"""Execute typed CRMS plans with independent per-step checks.

Planning is not implemented here. This module defines the action contract and a
deterministic executor: resolve step inputs from earlier outputs, run the
action, verify the result independently, and stop at the first failure. A plan
never produces an answer unless every step and the optional plan-level check
pass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import re
from typing import Any, Callable, Mapping

from crms_tasks import (
    CheckSpec, EvidenceRef, Plan, PlanResult, Step, StepResult, TaskIRError,
)


class ExecutionError(RuntimeError):
    """An action or the executor cannot complete a step."""


@dataclass(frozen=True)
class Verification:
    passed: bool
    detail: str = ""
    evidence: tuple[EvidenceRef, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.passed, bool):
            raise TaskIRError("verification passed must be a bool")
        if not self.passed and not self.detail.strip():
            raise TaskIRError("a failed verification requires a detail")
        for item in self.evidence:
            item.validate()


@dataclass
class ExecutionContext:
    data: Mapping[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class Action(ABC):
    """A typed operation with an independent verifier."""

    name: str

    @abstractmethod
    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        ...

    @abstractmethod
    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        ...

    @abstractmethod
    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult, context: ExecutionContext) -> Verification:
        ...


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action, *, replace: bool = False) -> None:
        name = getattr(action, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("action name must be a non-empty string")
        if name in self._actions and not replace:
            raise ValueError(f"action already registered: {name!r}")
        self._actions[name] = action

    def get(self, name: str) -> Action:
        try:
            return self._actions[name]
        except KeyError as error:
            raise ExecutionError(f"no action is registered as {name!r}") from error

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._actions))

    def __contains__(self, name: object) -> bool:
        return name in self._actions

    def __len__(self) -> int:
        return len(self._actions)


class FunctionAction(Action):
    """Adapt a function pair into an action.

    A verifier is mandatory unless the caller explicitly opts into
    self-verification, which is only appropriate for tests and never for a
    factual or proof-bearing action.
    """

    def __init__(self, name: str,
                 handler: Callable[[Step, Mapping[str, Any], ExecutionContext],
                                   StepResult],
                 verifier: Callable[[Step, Mapping[str, Any], StepResult,
                                    ExecutionContext], Verification] | None = None,
                 *, precondition: Callable[[Mapping[str, Any], ExecutionContext],
                                            bool] | None = None,
                 allow_self_verification: bool = False) -> None:
        self.name = name
        self._handler = handler
        self._verifier = verifier
        self._precondition = precondition
        self._allow_self_verification = allow_self_verification

    def can_apply(self, inputs: Mapping[str, Any],
                  context: ExecutionContext) -> bool:
        return True if self._precondition is None else bool(
            self._precondition(inputs, context))

    def apply(self, step: Step, inputs: Mapping[str, Any],
              context: ExecutionContext) -> StepResult:
        return self._handler(step, inputs, context)

    def verify(self, step: Step, inputs: Mapping[str, Any],
               result: StepResult,
               context: ExecutionContext) -> Verification:
        if self._verifier is not None:
            verification = self._verifier(step, inputs, result, context)
            if not isinstance(verification, Verification):
                raise TaskIRError("action verifier must return Verification")
            verification.validate()
            return verification
        if self._allow_self_verification:
            return Verification(result.status == "ok",
                                "self-verification requested by caller")
        return Verification(False, f"action {self.name!r} has no verifier")


PlanVerifier = Callable[[Plan, Mapping[str, Any], ExecutionContext],
                        Verification]

_REFERENCE = re.compile(r"^(?P<step>[A-Za-z0-9-]+)\.output$")


class PlanExecutor:
    def __init__(self, registry: ActionRegistry, *,
                 plan_verifier: PlanVerifier | None = None) -> None:
        self.registry = registry
        self.plan_verifier = plan_verifier

    def execute(self, plan: Plan,
                context: ExecutionContext | None = None) -> PlanResult:
        plan.validate()
        context = context or ExecutionContext()
        outputs: dict[str, Any] = {}
        results: list[StepResult] = []
        for step in plan.steps:
            try:
                inputs = self._resolve_inputs(step, outputs)
            except ExecutionError as error:
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: {error}")
            try:
                action = self.registry.get(step.action)
            except ExecutionError as error:
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: {error}")
            if not action.can_apply(inputs, context):
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: action {step.action!r} cannot apply")
            try:
                result = action.apply(step, inputs, context)
            except ExecutionError as error:
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: {error}")
            if not isinstance(result, StepResult):
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: action returned {type(result).__name__}")
            if result.step_id != step.id:
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: action returned result for "
                    f"{result.step_id!r}")
            try:
                result.validate()
            except TaskIRError as error:
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: invalid result: {error}")
            if result.status != "ok":
                results.append(result)
                return self._failure(
                    "execution_failed", plan, results,
                    f"step {step.id}: {result.detail or result.status}")
            verification = action.verify(step, inputs, result, context)
            if not verification.passed:
                results.append(result)
                return self._failure(
                    "verification_failed", plan, results,
                    f"step {step.id}: {verification.detail}")
            if verification.evidence:
                result = StepResult(
                    step_id=result.step_id,
                    status=result.status,
                    output=result.output,
                    evidence=result.evidence + verification.evidence,
                    detail=result.detail,
                    reason_code=result.reason_code,
                    metadata=dict(result.metadata),
                )
            outputs[step.id] = result.output
            results.append(result)

        if plan.verification is not None:
            if self.plan_verifier is None:
                return self._failure(
                    "execution_failed", plan, results,
                    "the plan declares a verification check but no plan "
                    "verifier is configured")
            verification = self.plan_verifier(plan, outputs, context)
            if not isinstance(verification, Verification):
                raise TaskIRError("plan verifier must return Verification")
            verification.validate()
            if not verification.passed:
                return self._failure(
                    "verification_failed", plan, results,
                    f"plan: {verification.detail}")

        return PlanResult(
            status="ok",
            plan=plan,
            output=results[-1].output,
            steps=tuple(results),
        )

    def _resolve_inputs(self, step: Step,
                        outputs: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: self._resolve_value(value, outputs)
            for key, value in step.inputs.items()
        }

    def _resolve_value(self, value: Any, outputs: Mapping[str, Any]) -> Any:
        if isinstance(value, str):
            match = _REFERENCE.fullmatch(value)
            if match is None:
                return value
            source = match.group("step")
            if source not in outputs:
                raise ExecutionError(
                    f"input references {source!r}.output before it is available")
            return outputs[source]
        if isinstance(value, list):
            return [self._resolve_value(item, outputs) for item in value]
        if isinstance(value, dict):
            return {
                key: self._resolve_value(item, outputs)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _failure(status: str, plan: Plan, results: list[StepResult],
                 reason: str) -> PlanResult:
        return PlanResult(
            status=status,
            plan=plan,
            output=None,
            steps=tuple(results),
            failures=(reason,),
        )


def check_for(kind: str, ref: str | None = None,
              **parameters: Any) -> CheckSpec:
    """Small convenience constructor for plan fixtures and adapters."""
    return CheckSpec(kind=kind, ref=ref, parameters=dict(parameters))
