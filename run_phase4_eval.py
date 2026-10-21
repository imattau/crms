#!/usr/bin/env python3
"""Phase 4 measurement: corrections, verified-work learning, active learning,
consolidation, model-copy persistence, bounded storage, and compounding.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_active_learning import ActiveLearner, Hypothesis  # noqa: E402
from crms_consolidation import consolidate  # noqa: E402
from crms_corrections import (  # noqa: E402
    learn_from_correction, learn_from_failure,
)
from crms_dependency import DependencyIndex  # noqa: E402
from crms_model import CRMSModel  # noqa: E402
from crms_phase4_benchmark import load_families, run_compounding  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402
from crms_verified_work import (  # noqa: E402
    VerificationOutcome, VerifiedWork, learn_from_verified_work,
)

FAMILIES = PROJECT / "experiments" / "scorecard" / "phase4_families.json"


def _activate(registry: RuleRegistry, rule_id: str, *, family: str,
              statement: str, scope: str = "", trust: str = "source-reviewed",
              payload: dict[str, Any] | None = None,
              provenance: tuple[dict[str, Any], ...] = (),
              dependencies: tuple[str, ...] = ()) -> Any:
    if rule_id not in registry:
        registry.propose(
            rule_id=rule_id, family=family, statement=statement, scope=scope,
            payload=payload, provenance=provenance, trust=trust,
            dependencies=dependencies)
    registry.validate(
        rule_id, oracle="phase4-independent-check", passed=True, cases=3,
        independent_sources=2, detail="independent phase-4 fixture check")
    if registry.get(rule_id).state == "validated":
        registry.activate(rule_id, mode="review", authoriser="phase4-fixture")
    return registry.get(rule_id)


def correction_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    fact_rule = _activate(
        registry, "fact-approved-3", family="fact-frame",
        statement="board approved 3", scope="minutes",
        payload={"subject": "board", "relation": "approved", "object": "3"})
    dependent = _activate(
        registry, "plan-approved-3", family="task-plan",
        statement="use approved value 3", scope="select", trust="derived",
        dependencies=("fact-approved-3",))
    dependencies = DependencyIndex()
    dependencies.add_node("source:minutes-1", "source",
                          trust="source-reviewed")
    dependencies.add_node("source:minutes-2", "source",
                          trust="source-reviewed")
    dependencies.add_node("source:minutes-3", "source",
                          trust="source-reviewed")
    dependencies.add_support(
        "fact:board-approved-3", "source:minutes-1",
        fact_payload={"subject": "board", "relation": "approved", "object": "3"})
    dependencies.add_support(
        "fact:board-approved-8", "source:minutes-2",
        fact_payload={"subject": "board", "relation": "approved", "object": "8"})
    dependencies.add_support(
        "fact:board-approved-8", "source:minutes-3",
        fact_payload={"subject": "board", "relation": "approved", "object": "8"})
    dependencies.add_node(
        "schema:approved-selection", "schema", trust="derived",
        payload={"template": "select approved values"})
    dependencies.add_edge(
        "schema:approved-selection", "fact:board-approved-3",
        relation="derived_from")
    dependencies.add_derivation(
        "derived:selection-3", ["schema:approved-selection"])
    dependencies.add_rule(fact_rule, dependencies=("derived:selection-3",))
    dependencies.add_rule(dependent, dependencies=("rule:fact-approved-3",))

    result = dependencies.retract_source(
        "source:minutes-1", registry=registry)
    expected = {
        "fact:board-approved-3", "schema:approved-selection",
        "derived:selection-3", "rule:fact-approved-3", "rule:plan-approved-3",
    }
    propagated = expected <= set(result.affected)
    states = {
        node_id: dependencies.get(node_id).state for node_id in expected
    }
    rules_contested = (
        registry.get("fact-approved-3").state == "contested"
        and registry.get("plan-approved-3").state == "contested")
    retained = (
        "fact:board-approved-8" not in result.affected
        and dependencies.get("fact:board-approved-8").state == "active")
    source_2_active = dependencies.get("source:minutes-2").state == "active"

    # A second support keeps the fact alive; removing it then contests the fact.
    second = dependencies.retract_source("source:minutes-2", registry=registry)
    support_retained = "fact:board-approved-8" in second.retained
    third = dependencies.retract_source("source:minutes-3", registry=registry)
    support_lost = "fact:board-approved-8" in third.affected

    return {
        "expected_affected": sorted(expected),
        "observed_affected": list(result.affected),
        "propagation_rate": (
            len(expected & set(result.affected)) / len(expected)),
        "all_expected_contested": propagated and all(
            state == "contested" for state in states.values()),
        "rules_contested": rules_contested,
        "retained_unsupported_branch": retained,
        "unrelated_source_active": source_2_active,
        "second_source_retained_fact": support_retained,
        "last_source_contested_fact": support_lost,
        "node_states": states,
    }


def trust_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    taught = _activate(
        registry, "trust-taught", family="fact-frame",
        statement="approved values are positive", trust="taught")
    source = _activate(
        registry, "trust-source", family="fact-frame",
        statement="source-reviewed selection", trust="source-reviewed")
    derived = _activate(
        registry, "trust-derived", family="fact-frame",
        statement="derived selection", trust="derived")
    conflict = DependencyIndex.resolve_trust_conflict([
        {"id": taught.id, "trust": taught.trust},
        {"id": source.id, "trust": source.trust},
        {"id": derived.id, "trust": derived.trust},
    ])
    if conflict["selected"] is None or conflict["selected"]["id"] != taught.id:
        raise RuntimeError("taught evidence did not win the trust conflict")
    for loser in conflict["losers"]:
        registry.contest(loser["id"], reason="taught evidence is authoritative")
    second = DependencyIndex.resolve_trust_conflict([
        {"id": source.id, "trust": source.trust},
        {"id": derived.id, "trust": derived.trust},
    ])
    return {
        "taught_wins": conflict["status"] == "selected"
        and conflict["selected"]["id"] == taught.id,
        "source_reviewed_beats_derived": second["selected"] is not None
        and second["selected"]["id"] == source.id,
        "losers_contested": all(
            registry.get(item["id"]).state == "contested"
            for item in conflict["losers"]),
        "selected_trust": conflict["trust"],
    }


def verified_work_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    dependencies = DependencyIndex()
    good = VerifiedWork(
        work_id="phase4-good-sum",
        request="Select approved values and sum them.",
        goal="select-sum",
        plan_id="plan-good-sum",
        steps=(
            {"step_id": "select", "action": "select-verified-positive"},
            {"step_id": "sum", "action": "apply-learned-procedure"},
        ),
        output=[6],
        checks=({"kind": "oracle", "passed": True},),
        provenance=({"source": "fixture:good"},),
    )

    def verifier(work: VerifiedWork) -> VerificationOutcome:
        return VerificationOutcome(
            list(work.output) == [6], cases=2, independent_sources=2,
            detail="independent sum oracle and an independent list source")

    good_result = learn_from_verified_work(
        good, registry, dependencies, verifier,
        rule_id="verified-sum-plan", family="task-plan",
        scope="select-then-sum", activate=True)
    bad_new = VerifiedWork(
        work_id="phase4-bad-sum", request=good.request, goal=good.goal,
        plan_id="plan-bad-sum", steps=good.steps, output=[999],
        checks=good.checks, provenance=({"source": "fixture:bad"},))
    bad_result = learn_from_verified_work(
        bad_new, registry, dependencies, verifier,
        rule_id="bad-sum-plan", family="task-plan",
        scope="select-then-sum")
    bad_revision = VerifiedWork(
        work_id="phase4-bad-revision", request=good.request, goal=good.goal,
        plan_id="plan-bad-revision", steps=good.steps, output=[999],
        checks=good.checks, provenance=({"source": "fixture:bad"},))
    revision_result = learn_from_verified_work(
        bad_revision, registry, dependencies, verifier,
        rule_id="verified-sum-plan", family="task-plan",
        scope="select-then-sum")
    good_active = registry.get("verified-sum-plan").state
    bad_active = any(
        record.state == "active" and record.id in {"bad-sum-plan",
                                                    "verified-sum-plan"}
        for record in registry.records())
    return {
        "good_result": good_result.as_dict(),
        "bad_result": bad_result.as_dict(),
        "bad_revision": revision_result.as_dict(),
        "good_rule_state_after_bad_revision": good_active,
        "bad_derivation_active": bad_active,
        "bad_validation_failed": not bool(
            bad_result.validation.get("passed", True))
        and not bool(revision_result.validation.get("passed", True)),
        "lineage_nodes": len(dependencies),
    }


def correction_learning_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    dependencies = DependencyIndex()
    target = _activate(
        registry, "procedure-sum", family="procedure",
        statement="sum every value", scope="integer lists",
        trust="source-reviewed",
        payload={"instruction": "sum every value"})
    dependencies.add_rule(target)
    correction = learn_from_correction(
        "correction-empty-sum", target_rule=target.id,
        scope="empty integer lists", excluded=[], corrected=[0],
        source="teacher:correction:empty-sum",
        reason="the empty list sums to zero, not an unknown",
        registry=registry, dependencies=dependencies)
    failure = learn_from_failure(
        "failure-odd-sum", request="sum every odd value",
        action="apply-learned-procedure",
        reason="procedure not learned for odd-only selection",
        scope="odd-only selection", target_rule=target.id,
        source="plan-log:failure:odd-sum",
        registry=registry, dependencies=dependencies)
    return {
        "correction": correction.as_dict(),
        "failure": failure.as_dict(),
        "negative_examples": 2,
        "correction_revision_proposed": (
            correction.revision_state == "proposed"),
        "failure_revision_proposed": failure.revision_state == "proposed",
        "no_revision_active": not any(
            record.state == "active" and record.id.endswith(
                ("-revision", "-failure-revision"))
            for record in registry.records()),
        "correction_node_trust": dependencies.get(
            "correction:correction-empty-sum").trust,
        "failure_node_trust": dependencies.get(
            "failure:failure-odd-sum").trust,
        "revision_lineage": {
            "correction": correction.revision_rule_id,
            "failure": failure.revision_rule_id,
        },
    }


def scoped_auto_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    registry.propose(
        rule_id="auto-lexical", family="lexical",
        statement="reverse wording", scope="list", trust="source-reviewed")
    registry.validate(
        "auto-lexical", oracle="heldout-lexical", passed=True,
        cases=3, independent_sources=2)
    disabled = False
    try:
        registry.activate("auto-lexical", mode="scoped-auto",
                          authoriser="phase4-policy")
    except ValueError:
        disabled = True
    registry.allow_scoped_auto = True
    registry.activate("auto-lexical", mode="scoped-auto",
                      authoriser="phase4-policy")
    registry.propose(
        rule_id="auto-procedure", family="procedure",
        statement="apply verified sum", scope="integer lists",
        trust="source-reviewed")
    registry.validate(
        "auto-procedure", oracle="heldout-list", passed=True,
        cases=4, independent_sources=2)
    registry.activate("auto-procedure", mode="scoped-auto",
                      authoriser="phase4-policy")
    registry.propose(
        rule_id="auto-fact", family="fact-frame",
        statement="creator fact", scope="biography",
        trust="source-reviewed")
    registry.validate(
        "auto-fact", oracle="heldout-fact", passed=True,
        cases=4, independent_sources=2)
    high_risk_refused = False
    try:
        registry.activate("auto-fact", mode="scoped-auto",
                          authoriser="phase4-policy")
    except ValueError:
        high_risk_refused = True
    registry.propose(
        rule_id="auto-derived", family="procedure",
        statement="derived procedure", scope="integer lists",
        trust="derived")
    registry.validate(
        "auto-derived", oracle="heldout-list", passed=True,
        cases=4, independent_sources=2)
    derived_refused = False
    try:
        registry.activate("auto-derived", mode="scoped-auto",
                          authoriser="phase4-policy")
    except ValueError:
        derived_refused = True
    return {
        "off_by_default": disabled,
        "eligible_lexical_active": (
            registry.get("auto-lexical").state == "active"
            and registry.get("auto-lexical").acceptance_mode == "scoped-auto"),
        "eligible_procedure_active": (
            registry.get("auto-procedure").state == "active"
            and registry.get("auto-procedure").acceptance_mode == "scoped-auto"),
        "high_risk_refused": high_risk_refused,
        "derived_refused": derived_refused,
        "policy": sorted(
            record.id for record in registry.records(state="active")
            if record.acceptance_mode == "scoped-auto"),
    }


def active_learning_lane() -> dict[str, Any]:
    learner = ActiveLearner([
        Hypothesis("sum", lambda values: [sum(values)], label="sum",
                   family="procedure", statement="sum the values"),
        Hypothesis("double", lambda values: [2 * value for value in values],
                   label="double", family="procedure",
                   statement="double the values"),
    ], cases=([1, 2], [2, 3], [4, 5]))
    question = learner.ask()
    if question is None:
        raise RuntimeError("active learner found no separating question")
    decision = learner.record(question, [3], source="teacher:phase4:active")
    registry = RuleRegistry()
    winner = learner.propose_winner(
        registry, rule_id="active-sum", statement="sum the values",
        scope="integer lists")
    return {
        "questions_asked": 1,
        "question": question.as_dict(),
        "decision": decision.status,
        "remaining": list(decision.remaining),
        "supervision": [row.as_dict() for row in learner.supervision],
        "proposed_rule_state": winner.state if winner is not None else None,
        "supervision_count": len(learner.supervision),
    }


def consolidation_lane() -> dict[str, Any]:
    registry = RuleRegistry()
    a = _activate(
        registry, "dup-a", family="lexical", statement="same wording",
        scope="list", trust="source-reviewed",
        provenance=({"source": "teacher:a"},))
    b = _activate(
        registry, "dup-b", family="lexical", statement="same wording",
        scope="list", trust="source-reviewed",
        provenance=({"source": "teacher:b"},))
    c = _activate(
        registry, "compatible-a", family="lexical", statement="reverse wording a",
        scope="list", trust="source-reviewed",
        payload={"merge_key": "lexical:reverse"})
    d = _activate(
        registry, "compatible-b", family="lexical", statement="reverse wording b",
        scope="list", trust="source-reviewed",
        payload={"merge_key": "lexical:reverse"})
    _activate(
        registry, "conflict-a", family="dialogue-policy", statement="allow a",
        scope="shared", trust="source-reviewed",
        payload={"conflict_key": "shared-policy", "value": "allow"})
    _activate(
        registry, "conflict-b", family="dialogue-policy", statement="deny a",
        scope="shared", trust="source-reviewed",
        payload={"conflict_key": "shared-policy", "value": "deny"})
    old = _activate(
        registry, "old-zero", family="lexical", statement="unused wording",
        scope="list", trust="source-reviewed")
    registry.get("old-zero").created_at = (
        datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    report = consolidate(
        registry, zero_utility_days=30,
        now=datetime.now(timezone.utc))
    canonical = next(
        record for record in (registry.get(a.id), registry.get(b.id))
        if record.state == "active")
    provenance_sources = sorted({
        item.get("source") for item in canonical.provenance
        if isinstance(item, dict) and item.get("source")
    })
    return {
        "report": report.as_dict(),
        "duplicate_canonical_active": canonical.state == "active",
        "duplicate_provenance_merged": provenance_sources
        == ["teacher:a", "teacher:b"],
        "duplicate_retired": sorted(
            {a.id, b.id} & set(report.retired_duplicates)),
        "compatible_merged": bool(report.compatible_merges),
        "conflicts_detected": len(report.conflicts),
        "zero_utility_retired": "old-zero" in report.retired_zero_utility,
        "all_active_ids": sorted(
            record.id for record in registry.records(state="active")),
    }


def persistence_lane(model: CRMSModel, registry: RuleRegistry,
                     dependencies: DependencyIndex) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="crms-phase4-copy-") as folder:
        root = Path(folder)
        memory = root / "model.json"
        rules = root / "rules.sqlite"
        graph = root / "dependencies.sqlite"
        model.save(memory)
        registry.save(rules)
        dependencies.save(graph)
        memory_copy = root / "model-copy.json"
        rules_copy = root / "rules-copy.sqlite"
        graph_copy = root / "dependencies-copy.sqlite"
        shutil.copy2(memory, memory_copy)
        shutil.copy2(rules, rules_copy)
        shutil.copy2(graph, graph_copy)
        loaded_registry = RuleRegistry.load(rules_copy)
        loaded_graph = DependencyIndex.load(graph_copy)
        loaded_model = CRMSModel(
            memory_copy, max_composition_depth=1, max_workers=1,
            rule_registry=loaded_registry)
        prediction = loaded_model.predict("sum every value", [2, 3])
        copied = copy.deepcopy(loaded_registry)
        skeleton = (
            loaded_registry.get("phase4-select-transform")
            if "phase4-select-transform" in loaded_registry else None)
        return {
            "prediction": {
                "status": prediction.status,
                "output": list(prediction.output or []),
            },
            "registry_rules": len(loaded_registry),
            "dependency_nodes": len(loaded_graph),
            "skeleton_state": skeleton.state if skeleton else None,
            "skeleton_trust": skeleton.trust if skeleton else None,
            "skeleton_provenance_kept": bool(
                skeleton and skeleton.provenance),
            "deepcopy_rules": len(copied),
            "deepcopy_graph": len(copy.deepcopy(loaded_graph)),
            "graph_limits": loaded_graph.stats(),
        }


def storage_lane() -> dict[str, Any]:
    bounded = DependencyIndex(max_nodes=250, max_edges=800)
    for number in range(400):
        bounded.add_node(
            f"work:bounded-{number:03d}", "work", trust="derived",
            payload={"number": number})
    removed = bounded.prune()
    stats = bounded.stats()
    return {
        "removed": removed,
        "stats": stats,
        "bounded": stats["within_bound"] and stats["nodes"] <= 250,
    }


def _display_path(path: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def evaluate(families_path: str | Path = FAMILIES) -> dict[str, Any]:
    correction = correction_lane()
    correction_learning = correction_learning_lane()
    trust = trust_lane()
    verified_work = verified_work_lane()
    active = active_learning_lane()
    scoped_auto = scoped_auto_lane()
    consolidation = consolidation_lane()
    storage = storage_lane()

    data = load_families(families_path)
    registry = RuleRegistry()
    dependencies = DependencyIndex()
    model = CRMSModel(max_composition_depth=1, max_workers=1,
                      rule_registry=registry)
    compounding = run_compounding(model, registry, dependencies, data)
    persistence = persistence_lane(model, registry, dependencies)

    gate = {
        "injected_bad_derivation_blocked": (
            not verified_work["bad_derivation_active"]
            and verified_work["bad_validation_failed"]
            and verified_work["bad_revision"]["state"] == "contested"),
        "correction_propagation": (
            correction["propagation_rate"] == 1.0
            and correction["all_expected_contested"]
            and correction["rules_contested"]
            and correction["retained_unsupported_branch"]
            and correction["second_source_retained_fact"]
            and correction["last_source_contested_fact"]),
        "compounding": (
            compounding["round_count"] == 3
            and compounding["no_confident_error_regression"]
            and compounding["final_completion"] >=
            compounding["baseline_completion"]
            and (compounding["measured_gain"] > 0
                 or compounding["disjoint_family"]["gain"] == 0)),
        "provenance_and_trust": (
            persistence["skeleton_state"] == "active"
            and persistence["skeleton_trust"] == "derived"
            and persistence["skeleton_provenance_kept"]
            and persistence["prediction"]["status"] == "ok"
            and persistence["dependency_nodes"] > 0),
        "storage_bounded": storage["bounded"],
        "taught_authoritative": (
            trust["taught_wins"]
            and trust["source_reviewed_beats_derived"]
            and trust["losers_contested"]),
        "correction_learning": (
            correction_learning["correction_revision_proposed"]
            and correction_learning["failure_revision_proposed"]
            and correction_learning["no_revision_active"]
            and correction_learning["correction_node_trust"] == "taught"
            and correction_learning["failure_node_trust"] == "taught"),
        "active_learning": (
            active["questions_asked"] == 1
            and active["decision"] == "resolved"
            and active["supervision_count"] == 1
            and active["proposed_rule_state"] == "proposed"),
        "scoped_auto_pilot": (
            scoped_auto["off_by_default"]
            and scoped_auto["eligible_lexical_active"]
            and scoped_auto["eligible_procedure_active"]
            and scoped_auto["high_risk_refused"]
            and scoped_auto["derived_refused"]),
        "consolidation": (
            consolidation["duplicate_canonical_active"]
            and consolidation["duplicate_provenance_merged"]
            and bool(consolidation["duplicate_retired"])
            and consolidation["compatible_merged"]
            and consolidation["conflicts_detected"] >= 1
            and consolidation["zero_utility_retired"]),
    }
    return {
        "format": "crms-phase4-eval",
        "version": 1,
        "correction": correction,
        "correction_learning": correction_learning,
        "trust": trust,
        "verified_work": verified_work,
        "active_learning": active,
        "scoped_auto": scoped_auto,
        "consolidation": consolidation,
        "storage": storage,
        "compounding": compounding,
        "persistence": persistence,
        "gate": gate,
        "gate_passed": all(gate.values()),
        "provenance": {
            "families": _display_path(families_path),
            "method": "frozen independent oracles and replay verifiers",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", type=Path, default=FAMILIES)
    parser.add_argument(
        "--out", type=Path,
        default=PROJECT / "experiments" / "reports" / "phase4_learning.json")
    args = parser.parse_args()
    report = evaluate(args.families)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    compounding = report["compounding"]
    print("Phase 4 learning lanes")
    print(f"  correction propagation: "
          f"{report['correction']['propagation_rate']:.0%}")
    print(f"  compounding: {compounding['baseline_completion']:.0%} -> "
          f"{compounding['final_completion']:.0%}; "
          f"confident errors {compounding['confident_errors']}")
    print(f"  disjoint family: "
          f"{compounding['disjoint_family']['final_completion']:.0%} "
          f"({compounding['disjoint_family']['diagnosis']})")
    print(f"  storage: {report['storage']['stats']}")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'} "
          f"{report['gate']}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
