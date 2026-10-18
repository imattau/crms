"""Check numeric-slot transfer corroborated across distinct learned frames."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def demos(amount: int):
    inputs = ([1, 4, -2], [5, -3, 8], [0, 6, -7], [9, 2, 1])
    return [(list(values), list(reversed([value + amount for value in values])))
            for values in inputs]


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    phrases = {
        "add 1 to each value then reverse the list": 1,
        "increase each value by 2 before reversing it": 2,
    }
    for phrase, amount in phrases.items():
        learned = model.teach(phrase, demos(amount))
        require(learned.status == "learned"
                and [step["operation"] for step in learned.procedure]
                == ["add_k", "reverse"],
                f"source phrase did not learn the shared scaffold: {phrase}: {learned}")

    query = "add 5 to each value then reverse the list"
    retrieved, conflict, sources, template, trace = (
        model._retrieve_parameterized_procedure(query))
    require(not conflict and retrieved is not None
            and [(step.operation, step.parameters) for step in retrieved]
            == [("add_k", {"k": 5}), ("reverse", {})]
            and set(sources) == set(phrases)
            and template == "add <number> to each value then reverse the list"
            and trace and trace[0]["numeric_bindings"][0]["parameter_value"] == 5,
            "independent successful frames did not corroborate numeric-slot transfer")
    prediction = model.predict(query, [3, -1, 7])
    require(prediction.status == "ok" and prediction.output == [12, 4, 8]
            and set(prediction.evidence_phrases) == set(phrases),
            f"cross-frame grounded transfer failed at runtime: {prediction}")

    # A same-scaffold success with an inconsistent surface number/parameter
    # mapping must not be allowed to vote for transfer.
    inconsistent = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, amount in (
            ("remove 1 from each value then reverse the list", -1),
            ("increase each value by 2 before reversing it", 2)):
        learned = inconsistent.teach(phrase, demos(amount))
        require(learned.status == "learned",
                f"inconsistent-mapping control failed to learn {phrase}: {learned}")
    blocked, blocked_conflict, *_details = (
        inconsistent._retrieve_parameterized_procedure(
            "remove 5 from each value then reverse the list"))
    require(blocked is None and blocked_conflict,
            "conflicting slot-to-parameter mappings were silently transferred")

    fixed = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase in ("add 1 to each value then reverse the list",
                   "increase each value by 1 before reversing it"):
        require(fixed.teach(phrase, demos(1)).status == "learned",
                "constant-slot control did not learn")
    blocked, blocked_conflict, *_details = (
        fixed._retrieve_parameterized_procedure(query))
    require(blocked is None and blocked_conflict,
            "non-varying parameters incorrectly licensed a novel value")

    print("cross-frame scaffold transfer diagnostic: PASS")
    print("independent language frames, successful procedure alignment, conflict abstention, constant-slot guard: PASS")


if __name__ == "__main__":
    main()
