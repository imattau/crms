"""Family A actions: verified selection plus a learned procedure, end to end.

Run with: python3 experiments/v1_551_family_a_actions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_actions import (  # noqa: E402
    ApplyLearnedProcedureAction, SelectVerifiedPositiveAction,
)
from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_model import CRMSModel  # noqa: E402
from crms_planner import (  # noqa: E402
    ActionRegistry, ExecutionContext, FunctionAction, PlanExecutor, Verification,
    check_for,
)
from crms_tasks import Plan, Step, StepResult, TaskRequest  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def knowledge() -> CRMSKnowledgeBase:
    base = CRMSKnowledgeBase()
    for value in (3, 8, 5):
        base.add_fact("board", "approved", str(value),
                      source=f"minutes:{value}")
    for value in (11, -2):
        base.add_negative_fact("board", "approved", str(value),
                               source=f"minutes:no-{value}")
    return base


def model() -> CRMSModel:
    rules = CRMSModel(max_composition_depth=1)
    result = rules.teach("sum every value", [([1, 2], [3]), ([4, 5, 6], [15])])
    require(result.status == "learned",
            f"sum procedure did not learn: {result.status}")
    return rules


def request() -> TaskRequest:
    return TaskRequest(
        id="task-family-a",
        text="Which approved values sum to what?",
        goal="filter-then-sum",
    )


def plan() -> Plan:
    return Plan(
        request=request(),
        steps=(
            Step(
                id="select",
                action="select-verified-positive",
                inputs={"subject": "board", "relation": "approved",
                        "values": [-2, 3, 8, 5, 11]},
                output_type="integer-list",
                check=check_for("proof"),
            ),
            Step(
                id="sum",
                action="apply-learned-procedure",
                inputs={"values": "select.output",
                        "instruction": "sum every value"},
                output_type="integer-list",
                check=check_for("parity", ref="sum every value"),
                depends_on=("select",),
            ),
        ),
        verification=check_for("oracle", ref="independent-sum"),
    )


def executor(base: CRMSKnowledgeBase, rules: CRMSModel) -> PlanExecutor:
    actions = ActionRegistry()
    actions.register(SelectVerifiedPositiveAction(base))
    actions.register(ApplyLearnedProcedureAction(rules))
    return PlanExecutor(
        actions,
        plan_verifier=lambda plan, outputs, context: Verification(
            outputs["sum"] == [16], "independent sum disagrees"),
    )


def main() -> None:
    base = knowledge()
    rules = model()
    result = executor(base, rules).execute(
        plan(), ExecutionContext({"task": "family-a"}))
    require(result.status == "ok" and result.output == [16],
            f"family A plan did not complete: {result}")
    selected = result.steps[0]
    require(selected.output == [3, 8, 5],
            f"selection order or contents changed: {selected.output}")
    require(any(ref.kind == "proof" for ref in selected.evidence)
            and any(ref.kind == "fact" for ref in selected.evidence),
            "selection did not retain proof and negative-fact evidence")
    require(any(ref.kind == "procedure" for ref in result.steps[1].evidence),
            "procedure execution did not retain procedure evidence")

    # Unknown evidence is not negative evidence; no partial selection is returned.
    unknown_plan = Plan(
        request=request(),
        steps=(Step(id="select", action="select-verified-positive",
                    inputs={"subject": "board", "relation": "approved",
                            "values": [3, 99]}, output_type="integer-list"),),
    )
    unknown = executor(base, rules).execute(unknown_plan)
    require(unknown.status == "execution_failed"
            and "unknown values" in unknown.failures[0]
            and unknown.output is None,
            f"unknown value was silently dropped: {unknown}")

    # Explicit negative evidence excludes a value.
    negative = executor(base, rules).execute(Plan(
        request=request(),
        steps=(Step(id="select", action="select-verified-positive",
                    inputs={"subject": "board", "relation": "approved",
                            "values": [3, 11, -2]},
                    output_type="integer-list"),),
    ))
    require(negative.status == "ok" and negative.output == [3],
            f"negative evidence did not exclude values: {negative}")

    # Positive and negative evidence for the same value is a conflict.
    conflict_base = knowledge()
    conflict_base.add_negative_fact("board", "approved", "8",
                                    source="conflict")
    conflict = executor(conflict_base, rules).execute(Plan(
        request=request(),
        steps=(Step(id="select", action="select-verified-positive",
                    inputs={"subject": "board", "relation": "approved",
                            "values": [8]}, output_type="integer-list"),),
    ))
    require(conflict.status == "execution_failed"
            and "both positive proof" in conflict.failures[0],
            f"conflicting evidence was not refused: {conflict}")

    # A different relation is unknown, not a negative fact for this relation.
    wrong_relation = executor(base, rules).execute(Plan(
        request=request(),
        steps=(Step(id="select", action="select-verified-positive",
                    inputs={"subject": "board", "relation": "rejected",
                            "values": [11]}, output_type="integer-list"),),
    ))
    require(wrong_relation.status == "execution_failed"
            and "unknown values" in wrong_relation.failures[0],
            f"a different relation was treated as exclusion: {wrong_relation}")

    # An untaught procedure fails without returning the selected values.
    untaught = Plan(
        request=request(),
        steps=(plan().steps[0],
               Step(id="cube", action="apply-learned-procedure",
                    inputs={"values": "select.output",
                            "instruction": "cube every value"},
                    output_type="integer-list", depends_on=("select",))),
    )
    untaught_result = executor(base, rules).execute(untaught)
    require(untaught_result.status == "execution_failed"
            and untaught_result.output is None,
            f"an untaught procedure produced an answer: {untaught_result}")

    # Tampering with a selected value is rejected by the independent verifier.
    select_action = SelectVerifiedPositiveAction(base)
    tampered = FunctionAction(
        "select-verified-positive",
        lambda step, inputs, context: StepResult(
            step.id, "ok", output=[3, 8],
            evidence=select_action.apply(step, inputs, context).evidence),
        select_action.verify,
    )
    tamper_actions = ActionRegistry()
    tamper_actions.register(tampered)
    tamper_result = PlanExecutor(tamper_actions).execute(Plan(
        request=request(),
        steps=(Step(id="select", action="select-verified-positive",
                    inputs={"subject": "board", "relation": "approved",
                            "values": [3, 8, 5]}, output_type="integer-list"),),
    ))
    require(tamper_result.status == "verification_failed"
            and "dropped without negative evidence" in tamper_result.failures[0],
            f"a dropped value passed verification: {tamper_result}")

    # Tampering with a procedure output is rejected by parity.
    procedure_action = ApplyLearnedProcedureAction(rules)
    tampered_procedure = FunctionAction(
        "apply-learned-procedure",
        lambda step, inputs, context: StepResult(
            step.id, "ok", output=[99],
            evidence=procedure_action.apply(step, inputs, context).evidence),
        procedure_action.verify,
    )
    procedure_actions = ActionRegistry()
    procedure_actions.register(tampered_procedure)
    procedure_result = PlanExecutor(procedure_actions).execute(Plan(
        request=request(),
        steps=(Step(id="sum", action="apply-learned-procedure",
                    inputs={"values": [3, 8, 5],
                            "instruction": "sum every value"},
                    output_type="integer-list"),),
    ))
    require(procedure_result.status == "verification_failed"
            and "parity failed" in procedure_result.failures[0],
            f"a tampered procedure output passed: {procedure_result}")

    # Qualifiers are part of the selection scope.
    qualified = CRMSKnowledgeBase()
    qualified.add_fact("board", "approved", "3", source="y2024",
                       qualifiers={"year": "2024"})
    qualified.add_fact("board", "approved", "8", source="y2025",
                       qualifiers={"year": "2025"})
    qualified_action = SelectVerifiedPositiveAction(qualified)
    qstep = Step(id="select", action="select-verified-positive",
                 inputs={"subject": "board", "relation": "approved",
                         "values": [3, 8], "qualifiers": {"year": "2024"}},
                 output_type="integer-list")
    qresult = qualified_action.apply(qstep, qstep.inputs, ExecutionContext())
    require(qresult.status == "failed",
            f"a missing scoped value was silently dropped: {qresult}")
    qresult = qualified_action.apply(
        Step(id="select", action="select-verified-positive",
             inputs={"subject": "board", "relation": "approved",
                     "values": [3], "qualifiers": {"year": "2024"}},
             output_type="integer-list"),
        {"subject": "board", "relation": "approved", "values": [3],
         "qualifiers": {"year": "2024"}},
        ExecutionContext(),
    )
    require(qresult.status == "ok" and qresult.output == [3],
            f"qualified selection failed: {qresult}")

    print("verified selection -> learned procedure through the plan executor: PASS")
    print("unknown, negative, conflicting, and wrong-relation cases: PASS")
    print("untaught procedure and tampered step outputs are refused: PASS")
    print("qualifier scope is enforced: PASS")


if __name__ == "__main__":
    main()
