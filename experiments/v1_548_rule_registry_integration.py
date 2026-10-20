"""Learned procedures are mirrored into the governed rule registry.

Run with: python3 experiments/v1_548_rule_registry_integration.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_model import CRMSModel  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def teach_reverse(model: CRMSModel) -> None:
    result = model.teach("reverse the list", [
        ([1, 2, 3], [3, 2, 1]),
        ([5, 0, -2], [-2, 0, 5]),
    ])
    require(result.status == "learned",
            f"reverse did not learn: {result.status} {result.request}")


def main() -> None:
    registry = RuleRegistry()
    model = CRMSModel(max_composition_depth=1, rule_registry=registry)
    teach_reverse(model)
    rules = registry.records(family="procedure")
    require(len(rules) == 1 and rules[0].state == "active",
            f"learned procedure was not registered and activated: {rules}")
    record = rules[0]
    require(record.validation is not None
            and record.validation["oracle"] == "stored-demonstration-parity"
            and record.validation["passed"]
            and record.validation["cases"] == 2,
            f"rule validation record is wrong: {record.validation}")
    require(record.payload["instruction"] == "reverse the list"
            and record.payload["origin"] == "crms_model"
            and record.utility["applications"] == 0,
            f"rule payload or initial utility is wrong: {record.payload}")

    prediction = model.predict("reverse the list", [4, 7])
    require(prediction.status == "ok" and prediction.output == [7, 4],
            f"prediction changed: {prediction}")
    require(registry.get(record.id).utility["applications"] == 1,
            "a successful prediction was not recorded as rule use")

    # Re-teaching with more evidence revises the same rule instead of duplicating it.
    result = model.teach("reverse the list", [([9, 1], [1, 9])])
    require(result.status == "learned", f"extra example did not commit: {result.status}")
    require(len(registry.records(family="procedure")) == 1 and
            registry.get(record.id).payload["example_count"] == 3,
            "re-teaching duplicated the rule or lost the new example")
    require(any(item["action"] == "revise"
                for item in registry.get(record.id).history),
            "re-teaching did not record a revision")

    # A model loaded with an empty registry reconstructs active rules from memory.
    with tempfile.TemporaryDirectory(prefix="crms-rule-integration-") as folder:
        root = Path(folder)
        memory_path = root / "rules.json"
        registry_path = root / "registry.sqlite"
        model.save(memory_path)
        registry.save(registry_path)

        loaded_model = CRMSModel(
            memory_path, max_composition_depth=1,
            rule_registry=RuleRegistry.load(registry_path))
        loaded_rule = loaded_model.rule_registry.records(family="procedure")[0]
        require(loaded_rule.state == "active"
                and loaded_rule.utility["applications"] == 1,
                "registry state or utility was lost across reload")

        empty_registry_model = CRMSModel(
            memory_path, max_composition_depth=1,
            rule_registry=RuleRegistry())
        synced = empty_registry_model.rule_registry.records(family="procedure")
        require(len(synced) == 1 and synced[0].state == "active",
                f"an empty registry was not reconstructed from memory: {synced}")

        # Forgetting the procedure retires the rule; re-learning creates a
        # versioned successor rather than reviving a retired record.
        require(empty_registry_model.forget("reverse the list"),
                "forget did not remove the learned procedure")
        require(empty_registry_model.rule_registry.get(synced[0].id).state
                == "retired",
                "forgetting a procedure did not retire its rule")
        teach_reverse(empty_registry_model)
        successors = [
            item for item in empty_registry_model.rule_registry.records(
                family="procedure") if item.state == "active"]
        require(len(successors) == 1 and successors[0].id != synced[0].id,
                f"re-learning did not create a versioned successor: {successors}")

        # A model without a registry keeps its original API and creates no records.
        plain_model = CRMSModel(max_composition_depth=1)
        teach_reverse(plain_model)
        require(plain_model.predict("reverse the list", [2, 3]).output == [3, 2],
                "a model without a registry changed behaviour")
        require(plain_model.rule_health() is None,
                "a model without a registry reported rule health")

    print("learned procedure registered, validated, and activated: PASS")
    print("successful use and re-teaching update one rule: PASS")
    print("reload, registry reconstruction, retirement, and successor: PASS")
    print("models without a registry keep their behaviour: PASS")


if __name__ == "__main__":
    main()
