"""Check exact canonicalization of rotations around add-first transforms."""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def add_first_program(before: int, after: tuple[int, ...], *,
                      rotation: int = 1) -> tuple[Step, ...]:
    steps = []
    if before:
        steps.append(Step("add_k", {"k": before}))
    steps.extend((Step("rotate_left_k", {"k": rotation}),
                  Step("add_first", {})))
    steps.extend(Step("add_k", {"k": value}) for value in after)
    return tuple(steps)


def main() -> None:
    target = add_first_program(-7, ())
    aliases = [
        target,
        add_first_program(-10, (6,)),
        add_first_program(-9, (4,)),
        add_first_program(-8, (2,)),
        add_first_program(-6, (-2,)),
        add_first_program(-5, (-4,)),
        add_first_program(0, (-10, -4)),
        add_first_program(-4, (-6,)),
        add_first_program(0, (-8, -6)),
        add_first_program(-3, (-8,)),
        add_first_program(0, (-6, -8)),
        add_first_program(-2, (-10,)),
        add_first_program(0, (-4, -10)),
        add_first_program(0, (-9, -5)),
        add_first_program(0, (-7, -7)),
        add_first_program(0, (-5, -9)),
    ]
    expected_key = _semantic_key(target)
    if any(_semantic_key(program) != expected_key for program in aliases):
        raise SystemExit("equivalent affine/rotation programs were not canonicalized")

    probes = [list(values) for length in range(6)
              for values in itertools.product(range(-2, 3), repeat=length)]
    rng = random.Random(48)
    probes.extend([[rng.randint(-30, 30) for _ in range(rng.randint(0, 12))]
                   for _ in range(500)])
    for values in probes:
        expected = _apply_procedure(target, values)
        if any(_apply_procedure(program, values) != expected for program in aliases):
            raise SystemExit(f"canonicalized aliases differ on {values}")

    different_anchor = add_first_program(-7, (), rotation=2)
    different_offset = add_first_program(-7, (-1,))
    if (_semantic_key(different_anchor) == expected_key
            or _semantic_key(different_offset) == expected_key):
        raise SystemExit("distinct anchor or offset was merged")

    scaled_target = (
        Step("double", {}), Step("add_k", {"k": -3}),
        Step("rotate_left_k", {"k": 1}), Step("add_first", {}),
        Step("scale_k", {"k": -2}), Step("add_k", {"k": 1}),
    )
    scaled_alias = (
        Step("add_k", {"k": -1}), Step("rotate_left_k", {"k": 1}),
        Step("add_first", {}), Step("scale_k", {"k": -4}),
        Step("add_k", {"k": 5}),
    )
    if _semantic_key(scaled_target) != _semantic_key(scaled_alias):
        raise SystemExit("affine scaling around add-first was not normalized")
    if any(_apply_procedure(scaled_target, values)
           != _apply_procedure(scaled_alias, values) for values in probes):
        raise SystemExit("scaled canonical aliases differ on a concrete list")

    examples = [([-16, -17, -6, 9, 3], _apply_procedure(target, [-16, -17, -6, 9, 3])),
                ([0, 0, 1], _apply_procedure(target, [0, 0, 1]))]
    # The demonstrated target is a three-operation rule. At depth three the
    # complete search fits the configured budget and tests learning directly.
    model = CRMSModel(max_composition_depth=3, max_workers=1)
    result = model.teach("generated rotated add-first", examples)
    learned = model._procedures.get("generated rotated add-first")
    if result.status != "learned" or learned is None:
        raise SystemExit(f"equivalent candidate family stayed ambiguous: {result}")
    if _semantic_key(learned) != expected_key:
        raise SystemExit("learned behavior does not match the demonstrated rule")
    held_out = [[], [3], [5, -2, 8, 1], [-4, 7, -9, 2, 0, 6]]
    if any(model.predict("generated rotated add-first", values).output
           != _apply_procedure(target, values) for values in held_out):
        raise SystemExit("canonicalized learned rule failed on held-out lists")

    depth_four = CRMSModel(max_composition_depth=4, max_workers=1)
    depth_four_result = depth_four.teach("depth-four rotated add-first", examples)
    learned_depth_four = depth_four._procedures.get("depth-four rotated add-first")
    if (depth_four_result.status != "learned" or learned_depth_four is None
            or _semantic_key(learned_depth_four) != expected_key):
        raise SystemExit(f"complete depth-four search missed the target: {depth_four_result}")
    if any(depth_four.predict("depth-four rotated add-first", values).output
           != _apply_procedure(target, values) for values in held_out):
        raise SystemExit("depth-four learned rule failed on held-out lists")

    # A deliberately tiny cap still has to abstain without committing a
    # partial fit, even though the default bounded search completes this case.
    bounded = CRMSModel(max_composition_depth=4, max_workers=1,
                        max_search_expansions=1)
    bounded_result = bounded.teach("low-budget rotated add-first", examples)
    if (bounded_result.status != "search_incomplete"
            or bounded_result.search_complete
            or "low-budget rotated add-first" in bounded._procedures):
        raise SystemExit("incomplete depth-four search was treated as complete")

    print("rotated add-first canonicalization diagnostic: PASS")
    print("equivalent candidates, depth-three/depth-four learning, held-out lists, bounded abstention: PASS")


if __name__ == "__main__":
    main()
