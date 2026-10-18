"""Check discovery, composition, edge cases, and persistence for input-relative rules.

Run from the project root with:
    python3 experiments/v1_27_input_relative_rules.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def resolve_with_demonstrated_rule(model: CRMSModel, instruction: str,
                                  result, target: tuple[Step, ...]):
    """Answer bounded ambiguity probes from the explicitly taught behavior."""
    for _ in range(8):
        if result.status == "learned":
            return result
        probe = result.contrastive_input
        if result.status != "need_more_examples" or probe is None:
            return result
        expected = _apply_procedure(target, probe)
        if expected not in (result.candidate_outputs or []):
            raise SystemExit(
                f"contrastive probe omitted the demonstrated behavior: {result}")
        result = model.teach(instruction, [(probe, expected)])
    return result


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    add_examples = [
        ([2, 5, -1], [4, 7, 1]),
        ([-3, 4, 8], [-6, 1, 5]),
        ([1, 3, 5, 7], [2, 4, 6, 8]),
    ]
    subtract_examples = [
        ([2, 5, -1], [0, 3, -3]),
        ([-3, 4, 8], [0, 7, 11]),
        ([1, 3, 5, 7], [0, 2, 4, 6]),
    ]
    add_instruction = "add the first value to each value"
    subtract_instruction = "subtract the first value from each value"
    add_target = (Step("add_first", {}),)
    subtract_target = (Step("subtract_first", {}),)
    additions = model.teach(add_instruction, add_examples)
    additions = resolve_with_demonstrated_rule(
        model, add_instruction, additions, add_target)
    subtractions = model.teach(subtract_instruction, subtract_examples)
    subtractions = resolve_with_demonstrated_rule(
        model, subtract_instruction, subtractions, subtract_target)
    if additions.status != "learned" or additions.procedure[0]["operation"] != "add_first":
        raise SystemExit(f"add-first rule not discovered: {additions}")
    if (subtractions.status != "learned"
            or subtractions.procedure[0]["operation"] != "subtract_first"):
        raise SystemExit(f"subtract-first rule not discovered: {subtractions}")

    held_out = [7, -2, 3]
    if model.predict("add the first value to each value", held_out).output != [14, 5, 10]:
        raise SystemExit("add-first held-out prediction failed")
    if model.predict("subtract the first value from each value", held_out).output != [0, -9, -4]:
        raise SystemExit("subtract-first held-out prediction failed")
    if model.predict("add the first value to each value", []).output != []:
        raise SystemExit("empty-list behavior failed")

    composed = model.teach("reverse and add the first value to each value", [
        ([2, 5, -1], [1, 7, 4]),
        ([-3, 4, 8], [5, 1, -6]),
        ([1, 3, 5, 7], [8, 6, 4, 2]),
    ])
    if composed.status != "learned":
        raise SystemExit(f"input-relative composition failed: {composed}")
    if model.predict("reverse and add the first value to each value", [4, 1, 9]).output != [13, 5, 8]:
        raise SystemExit("composed held-out prediction failed")

    relative_filter = CRMSModel(max_composition_depth=2, max_workers=1)
    rule = (Step("add_first", {}),
            Step("keep_multiples_k", {"k": 3}))
    filter_examples = [[1, 2, 4], [2, -1, 4], [-3, 1, 5],
                       [1, 5, 8, 2], [0, 3, 6, 1]]
    learned_filter = relative_filter.teach(
        "add the first value to each value then keep multiples of three",
        [(values, _apply_procedure(rule, values)) for values in filter_examples],
    )
    if (learned_filter.status != "learned"
            or relative_filter.predict(
                "add the first value to each value then keep multiples of three",
                [7, 4, -1],
            ).output != [6]):
        raise SystemExit(f"input-relative modular rule was not learned: {learned_filter}")

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "input-relative.json"
        model.save(memory)
        restored = CRMSModel(memory, max_composition_depth=2, max_workers=1)
        result = restored.predict("subtract the first value from each value", held_out)
    if result.output != [0, -9, -4]:
        raise SystemExit(f"input-relative persistence failed: {result}")

    equivalent = (
        Step("add_k", {"k": 9}),
        Step("add_first", {}),
        Step("scale_k", {"k": -3}),
        Step("subtract_first", {}),
    )
    canonical = (Step("scale_k", {"k": -3}),
                 Step("subtract_first", {}))
    if _semantic_key(equivalent) != _semantic_key(canonical):
        raise SystemExit("input-relative affine equivalence was not canonicalized")
    for values in ([4, 1, 9], [-7, 2], [], [0, 1, 2, 3]):
        if _apply_procedure(equivalent, list(values)) != _apply_procedure(canonical, list(values)):
            raise SystemExit(f"algebraic canonicalization changed behavior on {values}")
    shift_then_repeat = (
        Step("subtract_first", {}), Step("add_k", {"k": 4}),
        Step("repeat_each_k", {"k": 2}),
    )
    repeat_then_shift = (
        Step("subtract_first", {}), Step("repeat_each_k", {"k": 2}),
        Step("add_k", {"k": 4}),
    )
    if _semantic_key(shift_then_repeat) != _semantic_key(repeat_then_shift):
        raise SystemExit("affine/repetition equivalence was not canonicalized")
    for values in ([4, 1, 9], [-7, 2], [], [0, 1, 2, 3]):
        if _apply_procedure(shift_then_repeat, list(values)) != _apply_procedure(repeat_then_shift, list(values)):
            raise SystemExit(f"repetition canonicalization changed behavior on {values}")
    filtered_by_two_moduli = (
        Step("add_first", {}), Step("keep_evens", {}),
        Step("keep_multiples_k", {"k": 3}),
    )
    filtered_by_six = (
        Step("add_first", {}), Step("keep_multiples_k", {"k": 6}),
    )
    reversed_filter_order = (
        Step("add_first", {}), Step("keep_multiples_k", {"k": 3}),
        Step("keep_evens", {}),
    )
    if not (_semantic_key(filtered_by_two_moduli)
            == _semantic_key(filtered_by_six)
            == _semantic_key(reversed_filter_order)):
        raise SystemExit("input-relative modular-filter equivalence failed")
    unrestricted_after_scale = (
        Step("add_first", {}), Step("scale_k", {"k": 3}),
        Step("keep_multiples_k", {"k": 3}),
    )
    without_redundant_filter = (
        Step("add_first", {}), Step("scale_k", {"k": 3}),
    )
    if _semantic_key(unrestricted_after_scale) != _semantic_key(without_redundant_filter):
        raise SystemExit("redundant input-relative filter was not removed")
    for values in ([4, 1, 9], [-7, 2], [], [0, 1, 2, 3]):
        if _apply_procedure(filtered_by_two_moduli, list(values)) != _apply_procedure(filtered_by_six, list(values)):
            raise SystemExit(f"modular canonicalization changed behavior on {values}")

    print("input-relative rule diagnostic: PASS")
    print("two discovered primitives, held-out inputs, empty list, composition, modular filtering, persistence, affine equivalence: PASS")


if __name__ == "__main__":
    main()
