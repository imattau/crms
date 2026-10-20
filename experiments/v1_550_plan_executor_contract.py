"""The plan executor resolves inputs, verifies steps, and refuses partial success.

Run with: python3 experiments/v1_550_plan_executor_contract.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_planner import (  # noqa: E402
    ActionRegistry, ExecutionContext, ExecutionError, FunctionAction,
    PlanExecutor, Verification, check_for,
)
from crms_tasks import (  # noqa: E402
    Plan, Step, StepResult, TaskRequest,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def request() -> TaskRequest:
    return TaskRequest(
        id="task-plan-executor",
        text="add one then double",
        goal="arithmetic",
    )


def plan() -> Plan:
    return Plan(
        request=request(),
        steps=(
            Step(id="add", action="add-one", inputs={"value": 3},
                 output_type="integer", check=check_for("exact")),
            Step(id="double", action="double", inputs={"value": "add.output"},
                 output_type="integer", check=check_for("exact"),
                 depends_on=("add",)),
        ),
        verification=check_for("oracle", ref="independent-arithmetic"),
    )


def add_one(step, inputs, context):
    return StepResult("add", "ok", output=inputs["value"] + context.get("offset", 1))


def verify_add(step, inputs, result, context):
    expected = inputs["value"] + context.get("offset", 1)
    return Verification(result.output == expected,
                        "" if result.output == expected else
                        f"expected {expected}, got {result.output}")


def double(step, inputs, context):
    return StepResult("double", "ok", output=inputs["value"] * 2)


def verify_double(step, inputs, result, context):
    expected = inputs["value"] * 2
    return Verification(result.output == expected,
                        "" if result.output == expected else
                        f"expected {expected}, got {result.output}")


def registry() -> ActionRegistry:
    actions = ActionRegistry()
    actions.register(FunctionAction("add-one", add_one, verify_add))
    actions.register(FunctionAction("double", double, verify_double))
    return actions


def main() -> None:
    actions = registry()
    executor = PlanExecutor(
        actions,
        plan_verifier=lambda plan, outputs, context: Verification(
            outputs["double"] == (3 + context.get("offset", 1)) * 2,
            "plan output disagrees with independent arithmetic",
        ),
    )
    result = executor.execute(plan(), ExecutionContext({"offset": 2}))
    require(result.status == "ok" and result.output == 10,
            f"verified plan did not execute: {result}")
    require([step.step_id for step in result.steps] == ["add", "double"],
            f"steps ran out of order: {result.steps}")
    require(result.steps[1].output == 10,
            "step output was not resolved from the prior step")
    require(Plan.from_dict(result.plan.to_dict()).artifact_id
            == result.plan.artifact_id,
            "executed plan identity changed")

    # A failing action stops the plan before later steps run.
    def explode(step, inputs, context):
        raise ExecutionError("upstream data unavailable")

    def explode_downstream(step, inputs, context):
        raise ExecutionError("downstream check unavailable")

    failing = ActionRegistry()
    failing.register(FunctionAction("add-one", explode,
                                    lambda *args: Verification(True)))
    failing.register(FunctionAction("double", double, verify_double))
    failed = PlanExecutor(failing).execute(plan())
    require(failed.status == "execution_failed"
            and failed.steps == ()
            and "upstream data unavailable" in failed.failures[0],
            f"an action failure did not stop the plan: {failed}")

    # A later failure preserves the completed prefix but still returns no answer.
    late_failure = ActionRegistry()
    late_failure.register(FunctionAction("add-one", add_one, verify_add))
    late_failure.register(FunctionAction(
        "double", explode_downstream, verify_double))
    late = PlanExecutor(late_failure).execute(plan())
    require(late.status == "execution_failed"
            and [step.step_id for step in late.steps] == ["add"]
            and late.output is None,
            f"a late failure lost its completed prefix or returned output: {late}")

    # A verifier that rejects the output prevents a false success.
    bad = ActionRegistry()
    bad.register(FunctionAction(
        "add-one", lambda step, inputs, context: StepResult("add", "ok", output=99),
        verify_add))
    bad.register(FunctionAction("double", double, verify_double))
    rejected = PlanExecutor(bad).execute(plan())
    require(rejected.status == "verification_failed"
            and rejected.steps == ()
            and rejected.output is None,
            f"a rejected step produced an answer: {rejected}")

    # A plan-level verifier can reject an otherwise well-formed execution.
    plan_only = PlanExecutor(
        registry(),
        plan_verifier=lambda plan, outputs, context: Verification(
            False, "independent oracle disagrees"),
    ).execute(plan())
    require(plan_only.status == "verification_failed"
            and plan_only.output is None
            and len(plan_only.steps) == 2,
            f"a plan-level rejection was ignored: {plan_only}")

    # Missing verifier is not self-certification.
    self_signed = ActionRegistry()
    self_signed.register(FunctionAction(
        "add-one", add_one, allow_self_verification=True))
    self_signed.register(FunctionAction(
        "double", double, verify_double))
    self_result = PlanExecutor(
        self_signed,
        plan_verifier=lambda plan, outputs, context: Verification(True),
    ).execute(plan())
    require(self_result.status == "ok",
            f"explicit self-verification fixture failed: {self_result}")

    unsigned = ActionRegistry()
    unsigned.register(FunctionAction("add-one", add_one))
    unsigned.register(FunctionAction("double", double, verify_double))
    unsigned_result = PlanExecutor(unsigned).execute(plan())
    require(unsigned_result.status == "verification_failed"
            and "no verifier" in unsigned_result.failures[0],
            f"an action without a verifier was accepted: {unsigned_result}")

    # Unresolved references and unknown actions fail before execution.
    dangling = Plan(
        request=request(),
        steps=(Step(id="double", action="double",
                    inputs={"value": "missing.output"}, output_type="integer"),),
    )
    dangling_result = PlanExecutor(registry()).execute(dangling)
    require(dangling_result.status == "execution_failed"
            and "before it is available" in dangling_result.failures[0],
            f"a dangling reference was not rejected: {dangling_result}")

    unknown = Plan(
        request=request(),
        steps=(Step(id="x", action="nope", inputs={}, output_type="none"),),
    )
    unknown_result = PlanExecutor(registry()).execute(unknown)
    require(unknown_result.status == "execution_failed"
            and "no action is registered" in unknown_result.failures[0],
            f"an unknown action was not rejected: {unknown_result}")

    # A precondition can refuse a step without running it.
    guarded = ActionRegistry()
    guarded.register(FunctionAction(
        "add-one", add_one, verify_add,
        precondition=lambda inputs, context: False))
    guarded.register(FunctionAction("double", double, verify_double))
    guarded_result = PlanExecutor(guarded).execute(plan())
    require(guarded_result.status == "execution_failed"
            and "cannot apply" in guarded_result.failures[0],
            f"a refused precondition was ignored: {guarded_result}")

    # A mismatched step id is an implementation error, not a result.
    mismatched = ActionRegistry()
    mismatched.register(FunctionAction(
        "add-one", lambda step, inputs, context: StepResult("other", "ok", output=1),
        verify_add))
    mismatched.register(FunctionAction("double", double, verify_double))
    mismatch_result = PlanExecutor(mismatched).execute(plan())
    require(mismatch_result.status == "execution_failed"
            and "returned result for 'other'" in mismatch_result.failures[0],
            f"a mismatched step id was accepted: {mismatch_result}")

    print("verified multi-step execution and input resolution: PASS")
    print("action failure, verifier rejection, and plan oracle rejection: PASS")
    print("missing verifier, dangling reference, unknown action, precondition: PASS")
    print("mismatched step id is refused: PASS")


if __name__ == "__main__":
    main()
