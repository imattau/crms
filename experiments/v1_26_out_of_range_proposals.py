"""Check bounded no-fit proposals are exact, explanatory, and uncommitted.

Run from the project root with:
    python3 experiments/v1_26_out_of_range_proposals.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1,
                      max_add=5, max_scale=5, max_repeat=4)
    cases = [
        ("shift", [( [1, 3], [8, 10])], "add_k", {"k": 7}),
        ("multiply", [([2, 3], [14, 21])], "scale_k", {"k": 7}),
        ("repeat", [([1, 2], [1, 1, 1, 1, 1, 2, 2, 2, 2, 2])],
         "repeat_each_k", {"k": 5}),
        ("divisibility filter", [([7, 10, 14, 21], [7, 14, 21]),
                                 ([28, 6, 35, 49], [28, 35, 49])],
         "keep_multiples_k", {"k": 7}),
        ("rotate", [([1, 2, 3, 4, 5], [3, 4, 5, 1, 2]),
                    ([10, 11, 12, 13, 14, 15], [11, 12, 13, 14, 15, 10])],
         "rotate_left_k", {"k": 7}),
    ]
    for instruction, examples, operation, parameters in cases:
        result = model.teach(instruction, examples)
        if result.status != "no_fit" or not result.proposed_procedures:
            raise SystemExit(f"missing proposal for {instruction}: {result}")
        if not any(len(proc) == 1 and proc[0]["operation"] == operation
                   and proc[0]["parameters"] == parameters
                   for proc in result.proposed_procedures):
            raise SystemExit(f"expected {operation} proposal: {result}")
        if instruction in model._procedures:
            raise SystemExit(f"proposal was incorrectly committed: {instruction}")

    contradictory = model.teach("bad data", [([1, 2], [8, 10]),
                                                ([1, 2], [8, 11])])
    if contradictory.proposed_procedures:
        raise SystemExit(f"inconsistent evidence got a proposal: {contradictory}")

    in_range = model.teach("ordinary shift", [([1, 3], [5, 7])])
    if in_range.status != "learned" or in_range.proposed_procedures:
        raise SystemExit(f"in-range rule should learn normally: {in_range}")

    ambiguous = model.teach("ambiguous point", [([1], [7])])
    if ambiguous.status != "no_fit" or len(ambiguous.proposed_procedures or []) < 2:
        raise SystemExit(f"single point should preserve alternatives: {ambiguous}")

    long_input = list(range(20))
    underspecified_rotation = model.teach(
        "periodic rotation", [(long_input, long_input[7:] + long_input[:7])])
    if (underspecified_rotation.status != "no_fit"
            or not any(candidate[0]["operation"] == "rotate_left_k"
                       for candidate in (underspecified_rotation.proposed_procedures or []))):
        raise SystemExit("periodic rotation did not preserve bounded exact alternatives")

    weak_filter = model._propose_out_of_range_rules(
        [([7, 14], [7, 14])])
    if any(procedure[0].operation == "keep_multiples_k"
           for procedure in weak_filter):
        raise SystemExit("unchanged examples weakly proposed a divisibility filter")

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "rules.json"
        limited = CRMSModel(max_composition_depth=1, max_workers=1,
                            max_modulus=6)
        first = ([7, 10, 14, 21], [7, 14, 21])
        second = ([28, 6, 35, 49], [28, 35, 49])
        if limited.teach("multiples of seven", [first]).status != "no_fit":
            raise SystemExit("out-of-range modulus unexpectedly entered the search")
        limited.save(memory)
        try:
            CRMSModel(memory, max_composition_depth=1,
                      max_workers=1, max_modulus=5)
        except ValueError:
            pass
        else:
            raise SystemExit("narrower search bounds loaded a wider memory")
        widened = CRMSModel(memory, max_composition_depth=1,
                            max_workers=1, max_modulus=7)
        learned = widened.teach("multiples of seven", [second])
        procedure = widened._procedures.get("multiples of seven")
        held_out = widened.predict("multiples of seven", [14, 15, 21, 22])
        if (learned.status != "learned" or procedure is None
                or procedure[0].operation != "keep_multiples_k"
                or procedure[0].parameters != {"k": 7}
                or held_out.output != [14, 21]):
            raise SystemExit("widened bounds did not learn the previously proposed modulus")
        restored = CRMSModel(memory, max_composition_depth=1,
                             max_workers=1, max_modulus=7)
        if restored.predict("multiples of seven", [14, 15, 21]).output != [14, 21]:
            raise SystemExit("widened rule or search configuration did not persist")

    print("out-of-range proposal diagnostic: PASS")
    print("exact bounded parameter proposals for rotation and divisibility, no automatic commit, evidence gates, contradiction guard, and ambiguity: PASS")


if __name__ == "__main__":
    main()
