"""The typed task/plan IR enforces identity, bounds, and result invariants.

Run with: python3 experiments/v1_549_task_ir_contract.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_tasks import (  # noqa: E402
    CheckSpec, EvidenceRef, Plan, PlanResult, Step, StepResult, TaskIRError,
    TaskRequest, request_id,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def expect_error(call, fragment: str, message: str) -> None:
    try:
        call()
    except TaskIRError as error:
        require(fragment in str(error),
                f"{message}: wrong error: {error}")
    else:
        raise SystemExit(message)


def base_request() -> TaskRequest:
    return TaskRequest(
        id=request_id("Which approved values sum to what?", "filter-then-sum"),
        text="Which approved values sum to what?",
        goal="filter-then-sum",
        slots={"values": [-2, 3, 8]},
        constraints=("positive proofs only",),
        provenance={"authored": "fixture"},
    )


def base_plan(request: TaskRequest) -> Plan:
    filter_step = Step(
        id="filter",
        action="select-verified-positive",
        inputs={"values": [-2, 3, 8], "relation": "approved"},
        output_type="integer-list",
        evidence=(
            EvidenceRef("fact", "approved:3", source="source:a"),
            EvidenceRef("proof", "proof:3", source="source:a"),
        ),
        check=CheckSpec("proof", ref="approved:3"),
    )
    sum_step = Step(
        id="sum",
        action="apply-learned-procedure",
        inputs={"values": "filter.output", "instruction": "sum every value"},
        output_type="integer",
        evidence=(EvidenceRef("procedure", "procedure:sum", source="teacher:1"),),
        check=CheckSpec("parity", ref="procedure:sum"),
        depends_on=("filter",),
    )
    return Plan(
        request=request,
        steps=(filter_step, sum_step),
        verification=CheckSpec("oracle", ref="independent-sum-check"),
    )


def main() -> None:
    request = base_request()
    plan = base_plan(request)
    plan.validate()
    artifact_id = plan.artifact_id
    require(artifact_id.startswith("plan-") and len(artifact_id) == 21,
            f"plan artifact id has the wrong shape: {artifact_id}")
    require(plan.artifact_id == artifact_id,
            "plan artifact id is not deterministic")

    restored = Plan.from_json(plan.to_json())
    require(restored == plan and restored.artifact_id == artifact_id,
            "plan JSON round-trip changed the plan or its identity")

    changed = Plan(
        request=request,
        steps=(plan.steps[0], Step(
            id="sum",
            action="apply-learned-procedure",
            inputs={"values": "filter.output", "instruction": "sum every value",
                    "parameter": 3},
            output_type="integer",
            evidence=plan.steps[1].evidence,
            check=plan.steps[1].check,
            depends_on=("filter",),
        )),
        verification=plan.verification,
    )
    require(changed.artifact_id != artifact_id,
            "a changed step did not change the plan artifact id")

    require(request_id("Which approved values sum to what?",
                       "filter-then-sum") == request.id,
            "request id is not deterministic")
    require(request_id("  WHICH approved   values sum to what? ",
                       "filter-then-sum") == request.id,
            "request id is not case/whitespace stable")

    expect_error(lambda: Plan(
        request=request,
        steps=tuple(plan.steps) + tuple(
            Step(id=f"extra-{index}", action="noop", inputs={},
                 output_type="none")
            for index in range(5)),
    ).validate(), "at most 6 steps", "a seven-step plan was accepted")

    expect_error(lambda: Plan(
        request=request,
        steps=(plan.steps[0], Step(
            id="filter", action="noop", inputs={}, output_type="none")),
    ).validate(), "duplicate step id", "a duplicate step id was accepted")

    expect_error(lambda: Plan(
        request=request,
        steps=(plan.steps[1], plan.steps[0]),
    ).validate(), "depends on 'filter'", "a forward dependency was accepted")

    expect_error(lambda: Step(
        id="bad", action="", inputs={}, output_type="none").validate(),
        "step action", "an empty action was accepted")

    expect_error(lambda: EvidenceRef("vibes", "x").validate(),
                 "unknown evidence kind", "an unknown evidence kind was accepted")
    expect_error(lambda: CheckSpec("trust-me").validate(),
                 "unknown check kind", "an unknown check kind was accepted")
    expect_error(lambda: TaskRequest(id="r", text=" ", goal="g").validate(),
                 "request text", "an empty request was accepted")

    ok_result = PlanResult(
        status="ok",
        plan=plan,
        output=11,
        steps=(
            StepResult("filter", "ok", output=[3, 8],
                       evidence=(EvidenceRef("proof", "proof:3"),)),
            StepResult("sum", "ok", output=11),
        ),
    )
    ok_result.validate()
    require(PlanResult.from_dict(ok_result.to_dict()) == ok_result,
            "plan result round-trip changed the result")

    expect_error(lambda: PlanResult(
        status="ok", plan=plan, output=11,
        steps=(StepResult("filter", "ok", output=[3, 8]),
               StepResult("sum", "failed", detail="checker rejected")),
    ).validate(), "every planned step", "an ok result with a failed step was accepted")

    expect_error(lambda: PlanResult(
        status="ok", plan=plan, output=None,
        steps=(StepResult("filter", "ok", output=[3, 8]),
               StepResult("sum", "ok", output=11)),
    ).validate(), "requires an output", "an ok result without output was accepted")

    expect_error(lambda: PlanResult(
        status="verification_failed", plan=plan, output=11).validate(),
        "requires at least one reason", "a failure without a reason was accepted")

    expect_error(lambda: PlanResult(
        status="execution_failed", plan=plan).validate(),
        "requires at least one reason",
        "an execution failure without a reason was accepted")

    expect_error(lambda: PlanResult(
        status="unsupported",
        steps=(StepResult("filter", "ok", output=[]),),
    ).validate(), "cannot carry executed steps", "unsupported carried steps")

    expect_error(lambda: StepResult("sum", "ok").validate(),
                 "has no output", "a successful step without output was accepted")

    print("plan identity, bounds, dependencies, and round-trip: PASS")
    print("request identity and evidence/check validation: PASS")
    print("result invariants reject false success and incomplete states: PASS")


if __name__ == "__main__":
    main()
