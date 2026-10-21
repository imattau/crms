"""Phase 4 contract: corrections, verified work, active learning, compounding."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_active_learning import ActiveLearner, Hypothesis  # noqa: E402
from crms_dependency import DependencyIndex  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402
from crms_verified_work import (  # noqa: E402
    VerificationOutcome, VerifiedWork, learn_from_verified_work,
)
from run_phase4_eval import evaluate  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def module_contracts() -> None:
    # Taught evidence wins a conflict and source-reviewed beats derived.
    chosen = DependencyIndex.resolve_trust_conflict([
        {"id": "taught", "trust": "taught"},
        {"id": "derived", "trust": "derived"},
    ])
    require(chosen["selected"]["id"] == "taught",
            "taught evidence did not win")
    chosen = DependencyIndex.resolve_trust_conflict([
        {"id": "reviewed", "trust": "source-reviewed"},
        {"id": "derived", "trust": "derived"},
    ])
    require(chosen["selected"]["id"] == "reviewed",
            "source-reviewed evidence did not beat derived evidence")

    # One probe can separate two hypotheses; no probe is issued without a split.
    learner = ActiveLearner([
        Hypothesis("sum", lambda values: [sum(values)]),
        Hypothesis("double", lambda values: [2 * value for value in values]),
    ], cases=([1, 2],))
    question = learner.ask()
    require(question is not None
            and question.case == [1, 2]
            and sorted(question.outcomes) == [[2, 4], [3]],
            f"active learner picked the wrong probe: {question}")
    require(learner.record(question, [3], source="teacher:1").status
            == "resolved", "active learner did not resolve")
    unresolved = ActiveLearner([
        Hypothesis("same-a", lambda values: [sum(values)]),
        Hypothesis("same-b", lambda values: [sum(values)]),
    ], cases=([1, 2],))
    require(unresolved.ask() is None,
            "active learner asked an uninformative question")

    # A replay failure cannot validate a proposed rule.
    registry = RuleRegistry()
    dependencies = DependencyIndex()
    work = VerifiedWork(
        "replay-bad", "sum", "sum", "plan", ({"step_id": "s"},), [99],
        ({"kind": "oracle", "passed": True},))
    result = learn_from_verified_work(
        work, registry, dependencies,
        lambda item: VerificationOutcome(False, 1, 1, "oracle mismatch"),
        rule_id="replay-bad-rule")
    require(result.state == "proposed"
            and result.validation["passed"] is False,
            "a failed replay validated a rule")

    # The dependent rule follows its contested support through the registry.
    base = RuleRegistry()
    base.propose(rule_id="base", family="fact-frame",
                 statement="supported fact", trust="source-reviewed")
    base.validate("base", oracle="independent", passed=True, cases=1,
                  independent_sources=1)
    base.activate("base")
    base.propose(rule_id="child", family="task-plan",
                 statement="dependent plan", trust="derived",
                 dependencies=["base"])
    base.validate("child", oracle="independent", passed=True, cases=1,
                  independent_sources=1)
    base.activate("child")
    base.contest("base", reason="source retracted")
    require(base.get("child").state == "contested",
            "rule dependency did not propagate")

    # Storage pruning enforces the configured bound.
    bounded = DependencyIndex(max_nodes=10, max_edges=20)
    for number in range(30):
        bounded.add_node(f"work:{number}", "work", trust="derived")
    bounded.prune()
    require(bounded.stats()["within_bound"],
            f"dependency storage exceeded its bound: {bounded.stats()}")


def main() -> None:
    module_contracts()
    report = evaluate()
    require(report["gate_passed"],
            f"Phase 4 gate failed: {report['gate']}")
    require(report["compounding"]["round_count"] == 3,
            "compounding benchmark did not run three learning rounds")
    require(report["compounding"]["final_completion"] == 1.0
            and report["compounding"]["measured_gain"] == 1.0,
            "compounding benchmark did not measure a gain")
    require(not any(report["compounding"]["confident_errors"]),
            "compounding benchmark produced a confident error")
    require(report["compounding"]["plan_skeleton_transfer"]["transfer"],
            "verified plan skeleton did not transfer to a second family")
    require(report["compounding"]["disjoint_family"]["gain"] == 0.0
            and "plateau" in report["compounding"]["disjoint_family"]["diagnosis"],
            "disjoint-family plateau was not reported")
    require(report["correction"]["propagation_rate"] == 1.0,
            "correction propagation was not complete")
    require(report["correction_learning"]["correction_revision_proposed"]
            and report["correction_learning"]["failure_revision_proposed"]
            and report["correction_learning"]["no_revision_active"],
            "correction/failure learning did not create safe proposed revisions")
    require(report["verified_work"]["bad_derivation_active"] is False,
            "an injected bad derivation became active")
    require(report["scoped_auto"]["off_by_default"]
            and report["scoped_auto"]["eligible_lexical_active"]
            and report["scoped_auto"]["high_risk_refused"]
            and report["scoped_auto"]["derived_refused"],
            "scoped auto-accept pilot policy is wrong")
    require(report["active_learning"]["questions_asked"] == 1
            and report["active_learning"]["supervision_count"] == 1,
            "active learning did not ask and record one question")
    require(report["consolidation"]["duplicate_canonical_active"]
            and report["consolidation"]["conflicts_detected"] >= 1
            and report["consolidation"]["zero_utility_retired"],
            "consolidation lanes did not complete")
    require(report["persistence"]["skeleton_trust"] == "derived"
            and report["persistence"]["skeleton_state"] == "active"
            and report["persistence"]["prediction"]["status"] == "ok",
            "model copy lost trust, provenance, or behaviour")
    require(report["storage"]["bounded"],
            "dependency storage is not bounded")
    print("taught trust, active probing, and failed-replay refusal: PASS")
    print("100% correction propagation and rule dependency contest: PASS")
    print("verified-work rules, consolidation, and model-copy persistence: PASS")
    print("three-round compounding with held-out transfer and plateau: PASS")
    print("Phase 4 gate: PASS")


if __name__ == "__main__":
    main()
