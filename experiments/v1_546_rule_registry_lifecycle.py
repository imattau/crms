"""Check the governed rule registry lifecycle, rollback, and persistence.

Run with: python3 experiments/v1_546_rule_registry_lifecycle.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_rule_registry import RuleRegistry  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def propose_reverse(registry: RuleRegistry, rule_id: str = "reverse-phrase",
                    **kwargs) -> None:
    registry.propose(
        rule_id=rule_id,
        family="procedure",
        statement="reverse the list -> reverse()",
        scope="integer lists",
        payload={"operation": "reverse"},
        provenance=[{"source": "teacher:conversation"}],
        **kwargs,
    )


def main() -> None:
    registry = RuleRegistry()
    propose_reverse(registry)
    record = registry.get("reverse-phrase")
    require(record.state == "proposed" and not record.validated,
            "a proposed rule must not be usable")

    registry.validate(
        "reverse-phrase", oracle="heldout-list-parity", passed=True,
        cases=8, independent_sources=2, detail="8 unseen lists matched")
    require(registry.get("reverse-phrase").state == "validated",
            "passing validation did not validate the rule")

    registry.activate("reverse-phrase", mode="review", authoriser="user")
    require(registry.get("reverse-phrase").state == "active",
            "review activation failed")

    registry.record_use("reverse-phrase", success=True, saved_work=2)
    registry.record_use("reverse-phrase", success=False)
    utility = registry.get("reverse-phrase").utility
    require(utility["applications"] == 2 and utility["successes"] == 1
            and utility["corrections"] == 1 and utility["saved_work"] == 2,
            f"utility accounting is wrong: {utility}")

    # Rollback restores the prior transition each time: the two uses, then the
    # activation itself.
    for _ in range(3):
        registry.rollback("reverse-phrase")
    restored = registry.get("reverse-phrase")
    require(restored.state == "validated"
            and restored.utility["applications"] == 0,
            "rollback did not restore the pre-activation state")

    # A failing revalidation of an active rule contests it, not silently keeps it.
    registry.activate("reverse-phrase", mode="review")
    registry.record_use("reverse-phrase", success=True, saved_work=3)
    registry.validate(
        "reverse-phrase", oracle="heldout-list-parity", passed=False,
        cases=3, independent_sources=1, detail="counterexample found")
    require(registry.get("reverse-phrase").state == "contested",
            "failed revalidation of an active rule did not contest it")

    # Self-validation is refused.
    try:
        registry.validate(
            "reverse-phrase", oracle="self", passed=True,
            cases=10, independent_sources=10)
    except ValueError as error:
        require("not independent" in str(error),
                f"self-validation failed with the wrong error: {error}")
    else:
        raise SystemExit("self-validation was accepted")

    # Scoped auto-acceptance is off by default and refuses high-risk families.
    registry.propose(
        rule_id="auto-lexical", family="lexical",
        statement="flip the array -> reverse()", scope="integer lists")
    registry.validate(
        "auto-lexical", oracle="heldout-list-parity", passed=True,
        cases=5, independent_sources=2)
    try:
        registry.activate("auto-lexical", mode="scoped-auto")
    except ValueError as error:
        require("disabled" in str(error),
                f"disabled auto-accept failed with the wrong error: {error}")
    else:
        raise SystemExit("scoped auto-accept ran while disabled")

    registry.allow_scoped_auto = True
    registry.activate("auto-lexical", mode="scoped-auto", authoriser="policy")
    require(registry.get("auto-lexical").acceptance_mode == "scoped-auto",
            "eligible scoped auto-accept did not activate")

    registry.propose(
        rule_id="auto-fact-frame", family="fact-frame",
        statement="X designed Y", scope="biography")
    registry.validate(
        "auto-fact-frame", oracle="source-disjoint", passed=True,
        cases=9, independent_sources=3)
    try:
        registry.activate("auto-fact-frame", mode="scoped-auto")
    except ValueError as error:
        require("not eligible" in str(error),
                f"high-risk auto-accept failed with the wrong error: {error}")
    else:
        raise SystemExit("a fact-frame rule was auto-accepted")

    # Derived rules cannot auto-activate even with strong validation.
    registry.propose(
        rule_id="auto-derived", family="procedure",
        statement="verified plan -> procedure", trust="derived")
    registry.validate(
        "auto-derived", oracle="plan-checker", passed=True,
        cases=10, independent_sources=2)
    try:
        registry.activate("auto-derived", mode="scoped-auto")
    except ValueError as error:
        require("derived" in str(error),
                f"derived auto-accept failed with the wrong error: {error}")
    else:
        raise SystemExit("a derived rule was auto-accepted")

    # Correction propagation: contest the dependency, and its dependent follows.
    registry.propose(
        rule_id="base-frame", family="fact-frame",
        statement="X created Y", scope="computing")
    registry.propose(
        rule_id="dependent-plan", family="task-plan",
        statement="creator question -> creator plan", scope="computing",
        dependencies=["base-frame"])
    affected = registry.contest(
        "base-frame", reason="source retracted",
        evidence=[{"source": "teacher:conversation"}])
    require(registry.get("base-frame").state == "contested"
            and registry.get("dependent-plan").state == "contested",
            f"correction did not propagate: {[row.id for row in affected]}")
    require({row.id for row in affected} == {"base-frame", "dependent-plan"},
            "correction propagated to the wrong rule set")

    # Retirement also contests dependents.
    registry.propose(
        rule_id="retire-base", family="fact-frame", statement="X owns Y")
    registry.propose(
        rule_id="retire-child", family="task-plan",
        statement="ownership plan", dependencies=["retire-base"])
    affected = registry.retire("retire-base", reason="superseded")
    require(registry.get("retire-base").state == "retired"
            and registry.get("retire-child").state == "contested",
            "retirement did not retire the rule and contest its dependent")

    # Duplicate audit and health.
    registry.propose(
        rule_id="duplicate-one", family="lexical", statement="same words",
        scope="scope-a")
    registry.propose(
        rule_id="duplicate-two", family="lexical", statement="same words",
        scope="scope-a")
    issues = registry.audit()
    require(any(issue["kind"] == "duplicate"
                and set(issue["rule_ids"]) == {"duplicate-one", "duplicate-two"}
                for issue in issues),
            f"duplicate audit missed the group: {issues}")
    health = registry.health()
    require(health["by_state"]["proposed"] >= 2
            and health["duplicate_groups"],
            f"health summary is wrong: {health}")

    # Persistence round-trip preserves lifecycle, utility, history, and policy.
    with tempfile.TemporaryDirectory(prefix="crms-rule-registry-") as folder:
        path = Path(folder) / "rules.sqlite"
        registry.save(path)
        restored = RuleRegistry.load(path)
        require(len(restored) == len(registry),
                "persistence lost rules")
        restored_reverse = restored.get("reverse-phrase")
        require(restored_reverse.state == "contested"
                and restored_reverse.utility["applications"] == 1
                and restored_reverse.utility["saved_work"] == 3,
                "persistence lost lifecycle or utility state")
        require(restored.get("auto-lexical").acceptance_mode == "scoped-auto"
                and restored.allow_scoped_auto,
                "persistence lost acceptance policy")
        require(any(entry["action"] in {"contest", "validation-failed"}
                    for entry in restored_reverse.history),
                "persistence lost rule history")
        restored.retire("auto-lexical", reason="test rollback history")
        require(restored.get("auto-lexical").state == "retired",
                "loaded registry cannot transition a rule")

    print("rule lifecycle, validation, and self-validation refusal: PASS")
    print("scoped auto-accept gates and derived-rule refusal: PASS")
    print("correction propagation, retirement, and duplicate audit: PASS")
    print("rollback, utility accounting, persistence, and policy round-trip: PASS")


if __name__ == "__main__":
    main()
