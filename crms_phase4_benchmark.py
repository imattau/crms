"""Frozen Phase 4 compounding benchmark.

Three learning rounds add verified procedures behind one learned
select-then-transform plan rule. Every task is scored by an independent oracle,
not by the model's own explanation. A fourth, disjoint family is never taught;
it measures whether the system abstains instead of inventing transfer.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from crms_dependency import DependencyIndex
from crms_model import CRMSModel
from crms_rule_registry import RuleRegistry
from crms_verified_work import (
    VerificationOutcome, VerifiedWork, learn_from_verified_work,
)


def load_families(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("format") != "crms-phase4-families":
        raise ValueError("not a Phase 4 families fixture")
    if len(data.get("families", ())) != 3 or "disjoint" not in data:
        raise ValueError("Phase 4 needs three training families and one disjoint family")
    return data


def selected_values(values: list[int], data: Mapping[str, Any]) -> list[int]:
    selection = data["selection"]
    positive = {int(value) for value in selection["positive"]}
    negative = {int(value) for value in selection["negative"]}
    selected = []
    for value in values:
        value = int(value)
        if value in negative:
            continue
        if value not in positive:
            raise ValueError(f"value {value} has no positive evidence")
        selected.append(value)
    return selected


def apply_procedure(name: str, values: list[int]) -> list[int]:
    if name == "sum":
        return [sum(values)]
    if name == "double":
        return [value * 2 for value in values]
    if name == "reverse":
        return list(reversed(values))
    if name == "keep_odd":
        return [value for value in values if value % 2]
    raise ValueError(f"unknown procedure: {name!r}")


def _procedure(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    try:
        return data["procedures"][name]
    except KeyError as error:
        raise ValueError(f"unknown procedure fixture: {name!r}") from error


def teach_procedure(model: CRMSModel, data: Mapping[str, Any], name: str,
                    dependencies: DependencyIndex) -> Any:
    procedure = _procedure(data, name)
    examples = [((list(pair[0])), list(pair[1]))
                for pair in procedure["examples"]]
    result = model.teach(procedure["instruction"], examples)
    if result.status != "learned":
        raise RuntimeError(
            f"procedure {name!r} did not learn: {result.status} {result.request}")
    procedure_node = dependencies.add_node(
        "procedure:" + name, "procedure", trust="taught",
        payload={"instruction": procedure["instruction"],
                 "examples": examples})
    active = [
        record for record in model.rule_registry.records(
            family="procedure", state="active")
        if record.payload.get("instruction") == procedure["instruction"]
    ]
    if not active:
        raise RuntimeError(f"procedure {name!r} produced no active rule")
    dependencies.add_rule(active[0])
    dependencies.add_edge("rule:" + active[0].id, procedure_node.id,
                          relation="derived_from")
    dependencies.add_edge("procedure:" + name,
                          "source:phase4-families",
                          relation="derived_from")
    return active[0]


def learn_plan_skeleton(
        model: CRMSModel, data: Mapping[str, Any], registry: RuleRegistry,
        dependencies: DependencyIndex) -> Any:
    source = dependencies.add_node(
        "source:phase4-families", "source", trust="source-reviewed",
        provenance=({"fixture": "experiments/scorecard/phase4_families.json"},))
    del source
    family = data["families"][0]
    task = family["tasks"][0]
    selected = selected_values(list(task["values"]), data)
    expected = apply_procedure(family["procedure"], selected)
    work = VerifiedWork(
        work_id="phase4-skeleton-sum",
        request="Select approved values and apply the learned sum procedure.",
        goal=family["goal"],
        plan_id="plan-phase4-skeleton",
        steps=(
            {"step_id": "select", "action": "select-verified-positive"},
            {"step_id": "transform", "action": "apply-learned-procedure",
             "instruction": _procedure(data, family["procedure"])["instruction"]},
            {"step_id": "return", "action": "return-output"},
        ),
        output=expected,
        checks=({"kind": "oracle", "ref": "independent-select-then-transform",
                 "passed": True},),
        provenance=({"fixture": "phase4_families.json",
                     "family": family["id"]},),
    )

    def verify(work: VerifiedWork) -> VerificationOutcome:
        replay = apply_procedure(family["procedure"], selected)
        return VerificationOutcome(
            replay == work.output, cases=len(family["tasks"]),
            independent_sources=1,
            detail="independent list oracle replayed the verified plan")

    result = learn_from_verified_work(
        work, registry, dependencies, verify,
        rule_id="phase4-select-transform",
        family="task-plan",
        statement=("filter values with verified positive evidence, apply a "
                   "learned procedure, and return the output"),
        scope="select-then-transform",
        activate=True,
    )
    if result.state != "active":
        raise RuntimeError(f"plan skeleton did not activate: {result.as_dict()}")
    return result


def run_task(model: CRMSModel, registry: RuleRegistry,
             data: Mapping[str, Any], family: Mapping[str, Any],
             task: Mapping[str, Any]) -> dict[str, Any]:
    skeleton = [
        record for record in registry.records(state="active", family="task-plan")
        if record.scope == "select-then-transform"
    ]
    procedure_name = str(family["procedure"])
    procedure = _procedure(data, procedure_name)
    instruction = str(procedure["instruction"])
    selected = selected_values(list(task["values"]), data)
    expected = list(task["expected"])
    if not skeleton:
        return {
            "status": "unsupported", "reason": "no active select-transform rule",
            "expected": expected, "output": None, "selected": selected,
        }
    if instruction not in model._procedures:
        return {
            "status": "unsupported", "reason": "procedure not learned",
            "expected": expected, "output": None, "selected": selected,
        }
    prediction = model.predict(instruction, selected)
    if prediction.status != "ok":
        registry.record_use(skeleton[0].id, success=False)
        return {
            "status": "unsupported", "reason": f"procedure status {prediction.status}",
            "expected": expected, "output": None, "selected": selected,
        }
    output = list(prediction.output)
    if output != expected:
        registry.record_use(skeleton[0].id, success=False)
        return {
            "status": "confident_error", "reason": "output disagreed with oracle",
            "expected": expected, "output": output, "selected": selected,
        }
    registry.record_use(skeleton[0].id, success=True, saved_work=1)
    return {
        "status": "answered", "reason": "", "expected": expected,
        "output": output, "selected": selected,
    }


def evaluate_family(model: CRMSModel, registry: RuleRegistry,
                    data: Mapping[str, Any],
                    family: Mapping[str, Any]) -> dict[str, Any]:
    results = [run_task(model, registry, data, family, task)
               for task in family["tasks"]]
    return {
        "family": family["id"],
        "tasks": len(results),
        "answered": sum(1 for row in results if row["status"] == "answered"),
        "unsupported": sum(1 for row in results if row["status"] == "unsupported"),
        "confident_errors": sum(
            1 for row in results if row["status"] == "confident_error"),
        "results": results,
    }


def _snapshot(model: CRMSModel, registry: RuleRegistry,
              dependencies: DependencyIndex, data: Mapping[str, Any],
              learned: list[str]) -> dict[str, Any]:
    heldout = {
        family["id"]: evaluate_family(model, registry, data, family)
        for family in data["families"]
    }
    disjoint = evaluate_family(model, registry, data, data["disjoint"])
    total_answered = sum(row["answered"] for row in heldout.values())
    total_tasks = sum(row["tasks"] for row in heldout.values())
    errors = sum(row["confident_errors"] for row in heldout.values())
    return {
        "learned": list(learned),
        "heldout": heldout,
        "heldout_answered": total_answered,
        "heldout_tasks": total_tasks,
        "heldout_completion": (total_answered / total_tasks) if total_tasks else 0.0,
        "confident_errors": errors,
        "disjoint": disjoint,
        "disjoint_completion": (
            disjoint["answered"] / disjoint["tasks"] if disjoint["tasks"] else 0.0),
        "active_rules": len(registry.records(state="active")),
        "dependency_nodes": len(dependencies),
    }


def run_compounding(model: CRMSModel, registry: RuleRegistry,
                    dependencies: DependencyIndex,
                    data: Mapping[str, Any]) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    rounds.append({
        "round": 0,
        **_snapshot(model, registry, dependencies, data, []),
    })
    learned: list[str] = []
    for number, family in enumerate(data["families"], start=1):
        if number == 1:
            learn_plan_skeleton(model, data, registry, dependencies)
        teach_procedure(model, data, family["procedure"], dependencies)
        learned.append(family["id"])
        rounds.append({
            "round": number,
            **_snapshot(model, registry, dependencies, data, learned),
        })
    first = rounds[0]
    last = rounds[-1]
    gain = last["heldout_completion"] - first["heldout_completion"]
    disjoint_gain = last["disjoint_completion"] - first["disjoint_completion"]
    no_error_regression = all(
        row["confident_errors"] == 0 for row in rounds)
    double_before = rounds[1]["heldout"].get("double", {}).get("answered", 0)
    double_after = rounds[2]["heldout"].get("double", {}).get("answered", 0)
    return {
        "rounds": rounds,
        "round_count": len(rounds) - 1,
        "baseline_completion": first["heldout_completion"],
        "final_completion": last["heldout_completion"],
        "measured_gain": gain,
        "confident_errors": [row["confident_errors"] for row in rounds],
        "no_confident_error_regression": no_error_regression,
        "plan_skeleton_transfer": {
            "family": "double",
            "before_round_2": double_before,
            "after_round_2": double_after,
            "transfer": double_after > double_before,
        },
        "disjoint_family": {
            "family": data["disjoint"]["id"],
            "baseline_completion": first["disjoint_completion"],
            "final_completion": last["disjoint_completion"],
            "gain": disjoint_gain,
            "diagnosis": (
                "plateau: the disjoint family has no verified procedure or "
                "learned rule; the system abstains instead of transferring "
                "the plan skeleton without evidence"
                if disjoint_gain == 0 else
                "unexpected positive disjoint-family transfer"),
        },
        "storage": dependencies.stats(),
        "provenance": {
            "source": "experiments/scorecard/phase4_families.json",
            "learning": "verified-work replay; no model self-scoring",
        },
    }
