"""Search short programs for unsound semantic-key collisions.

Run from the project root with:
    python3 experiments/v1_118_semantic_key_collision_audit.py
"""

from __future__ import annotations

from collections import defaultdict
from itertools import product
from random import Random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _apply_procedure, _contrastive_probe, _semantic_key,
)


def main() -> None:
    model = CRMSModel(max_workers=1)
    probes = [list(values) for size in range(3)
              for values in product(range(-2, 3), repeat=size)]
    rng = Random(118)
    probes.extend([[rng.randint(-30, 30) for _ in range(rng.randint(0, 8))]
                   for _ in range(80)])

    # Search may reuse an extension key when equal semantic prefixes continue
    # with the same step. Check that this congruence holds behaviorally across
    # the full current one-step grammar for representative rewritten prefixes.
    extension_prefix_pairs = (
        (
            (Step("rotate_left_k", {"k": -2}),
             Step("rotate_left_k", {"k": 2}),
             Step("keep_every_kth_position", {"k": 6})),
            (Step("keep_every_kth_position", {"k": 6}),),
        ),
        (
            (Step("absolute_values", {}), Step("scale_k", {"k": -1})),
            (Step("scale_k", {"k": -1}),
             Step("absolute_values", {}), Step("scale_k", {"k": -1})),
        ),
    )
    for left, right in extension_prefix_pairs:
        if _semantic_key(left) != _semantic_key(right):
            raise SystemExit("extension fixture prefixes are not equivalent")
        for step in model._steps:
            if any(_apply_procedure(left + (step,), values)
                   != _apply_procedure(right + (step,), values)
                   for values in probes):
                raise SystemExit(
                    f"equal prefixes diverged after extension by {step}")

    # Regression: deduplication after reversing preserves the reversed order,
    # so its last item is not generally the original first item.
    counterexample = [-16, 20, 4, -22, -16]
    reversed_unique_last = (Step("reverse", {}), Step("stable_unique", {}),
                            Step("last", {}))
    first = (Step("first", {}),)
    if (_semantic_key(reversed_unique_last) == _semantic_key(first)
            or _apply_procedure(reversed_unique_last, counterexample)
            == _apply_procedure(first, counterexample)):
        raise SystemExit("reverse → stable_unique → last was unsafely reduced to first")

    canceled_rotations = (
        Step("rotate_left_k", {"k": -2}),
        Step("rotate_left_k", {"k": 2}),
        Step("keep_every_kth_position", {"k": 6}),
    )
    positional_filter = (Step("keep_every_kth_position", {"k": 6}),)
    if (_semantic_key(canceled_rotations) != _semantic_key(positional_filter)
            or any(_apply_procedure(canceled_rotations, values)
                   != _apply_procedure(positional_filter, values)
                   for values in probes)):
        raise SystemExit("canceled rotations before positional filtering were not canonicalized")

    negative_magnitude = (Step("absolute_values", {}),
                          Step("scale_k", {"k": -1}))
    equivalent_negative_magnitude = (
        Step("scale_k", {"k": -1}), Step("absolute_values", {}),
        Step("scale_k", {"k": -1}))
    if (_semantic_key(negative_magnitude)
            != _semantic_key(equivalent_negative_magnitude)
            or any(_apply_procedure(negative_magnitude, values)
                   != _apply_procedure(equivalent_negative_magnitude, values)
                   for values in probes)):
        raise SystemExit("absolute-value scale rewrite missed an exact alias")

    squared_shift = (Step("square_values", {}), Step("add_k", {"k": -8}))
    signless_square_aliases = (
        (Step("absolute_values", {}), Step("square_values", {}),
         Step("add_k", {"k": -8})),
        (Step("square_values", {}), Step("absolute_values", {}),
         Step("add_k", {"k": -8})),
        (Step("scale_k", {"k": -1}), Step("square_values", {}),
         Step("add_k", {"k": -8})),
    )
    for alias in signless_square_aliases:
        if _semantic_key(alias) != _semantic_key(squared_shift):
            raise SystemExit("absolute-value/square alias was not canonicalized")
        if any(_apply_procedure(alias, values)
               != _apply_procedure(squared_shift, values) for values in probes):
            raise SystemExit("absolute-value/square normalization changed behavior")
    # Absolute value after a non-sign-invariant shift is not a no-op.
    shifted_absolute = (Step("square_values", {}), Step("add_k", {"k": -8}),
                        Step("absolute_values", {}))
    if (_semantic_key(shifted_absolute) == _semantic_key(squared_shift)
            or _apply_procedure(shifted_absolute, [0])
            == _apply_procedure(squared_shift, [0])):
        raise SystemExit("post-shift absolute value was unsafely removed")
    negative_after_square = (Step("square_values", {}),
                             Step("scale_k", {"k": -1}),
                             Step("add_k", {"k": -8}))
    if (_semantic_key(negative_after_square) == _semantic_key(squared_shift)
            or _apply_procedure(negative_after_square, [1])
            == _apply_procedure(squared_shift, [1])):
        raise SystemExit("negative scale after square was unsafely removed")

    square_free_filter_then_square = (
        Step("keep_multiples_k", {"k": 5}), Step("square_values", {}))
    square_then_square_free_filter = (
        Step("square_values", {}), Step("keep_multiples_k", {"k": 5}))
    if (_semantic_key(square_free_filter_then_square)
            != _semantic_key(square_then_square_free_filter)
            or any(_apply_procedure(square_free_filter_then_square, values)
                   != _apply_procedure(square_then_square_free_filter, values)
                   for values in probes)):
        raise SystemExit("square-free divisibility filter did not commute with square")
    square_then_square_modulus = (
        Step("square_values", {}), Step("keep_multiples_k", {"k": 25}))
    if (_semantic_key(square_then_square_modulus)
            != _semantic_key(square_free_filter_then_square)
            or any(_apply_procedure(square_then_square_modulus, values)
                   != _apply_procedure(square_free_filter_then_square, values)
                   for values in probes)):
        raise SystemExit("square divisibility preimage used the wrong modulus")
    non_square_free_filter = (
        Step("keep_multiples_k", {"k": 4}), Step("square_values", {}))
    square_then_non_square_free_filter = (
        Step("square_values", {}), Step("keep_multiples_k", {"k": 4}))
    if (_semantic_key(non_square_free_filter)
            == _semantic_key(square_then_non_square_free_filter)
            or _apply_procedure(non_square_free_filter, [2])
            == _apply_procedure(square_then_non_square_free_filter, [2])):
        raise SystemExit("non-square-free divisibility filter was merged unsafely")
    square_then_sixteen = (
        Step("square_values", {}), Step("keep_multiples_k", {"k": 16}))
    if (_semantic_key(non_square_free_filter)
            != _semantic_key(square_then_sixteen)
            or any(_apply_procedure(non_square_free_filter, values)
                   != _apply_procedure(square_then_sixteen, values)
                   for values in probes)):
        raise SystemExit("non-square-free square preimage was not canonicalized")
    constrained_square = (
        Step("keep_multiples_k", {"k": 4}), Step("square_values", {}),
        Step("keep_multiples_k", {"k": 9}))
    combined_input_filter = (
        Step("keep_multiples_k", {"k": 12}), Step("square_values", {}))
    if (_semantic_key(constrained_square)
            != _semantic_key(combined_input_filter)
            or any(_apply_procedure(constrained_square, values)
                   != _apply_procedure(combined_input_filter, values)
                   for values in probes)):
        raise SystemExit("pre/post square filters did not reduce to their LCM")

    summed_and_shifted = (Step("sum_values", {}), Step("add_k", {"k": -4}))
    sum_aliases = (
        (Step("reverse", {}), Step("sum_values", {}),
         Step("add_k", {"k": -4})),
        (Step("sort_ascending", {}), Step("sum_values", {}),
         Step("add_k", {"k": -4})),
        (Step("sum_values", {}), Step("sum_values", {}),
         Step("add_k", {"k": -4})),
        (Step("sum_values", {}), Step("add_k", {"k": -4}),
         Step("sum_values", {})),
        (Step("sum_values", {}), Step("keep_odd_positions", {}),
         Step("add_k", {"k": -4})),
    )
    for alias in sum_aliases:
        if _semantic_key(alias) != _semantic_key(summed_and_shifted):
            raise SystemExit("sum permutation/singleton alias was not canonicalized")
        if any(_apply_procedure(alias, values)
               != _apply_procedure(summed_and_shifted, values)
               for values in probes):
            raise SystemExit("sum alias normalization changed behavior")
    multiplicity_sensitive_sum = (
        Step("stable_unique", {}), Step("sum_values", {}))
    if (_semantic_key(multiplicity_sensitive_sum)
            == _semantic_key((Step("sum_values", {}),))
            or _apply_procedure(multiplicity_sensitive_sum, [2, 2])
            == _apply_procedure((Step("sum_values", {}),), [2, 2])):
        raise SystemExit("stable_unique was incorrectly commuted across sum")

    scaled_even_filter = (
        Step("scale_k", {"k": 4}), Step("keep_evens", {}),
        Step("subtract_first", {}))
    scaled_relative = (
        Step("scale_k", {"k": 4}), Step("subtract_first", {}))
    if (_semantic_key(scaled_even_filter) != _semantic_key(scaled_relative)
            or any(_apply_procedure(scaled_even_filter, values)
                   != _apply_procedure(scaled_relative, values)
                   for values in probes)):
        raise SystemExit("even filter made redundant by scale was not removed")
    scale_then_modulus = (
        Step("scale_k", {"k": 2}), Step("keep_multiples_k", {"k": 6}))
    modulus_then_scale = (
        Step("keep_multiples_k", {"k": 3}), Step("scale_k", {"k": 2}))
    if (_semantic_key(scale_then_modulus) != _semantic_key(modulus_then_scale)
            or any(_apply_procedure(scale_then_modulus, values)
                   != _apply_procedure(modulus_then_scale, values)
                   for values in probes)):
        raise SystemExit("scaled divisibility preimage was not canonicalized")

    position_translation = (
        Step("rotate_left_k", {"k": 3}),
        Step("keep_every_kth_position", {"k": 5}),
        Step("add_k", {"k": 9}),
    )
    translation_before_positions = (
        Step("add_k", {"k": 9}),
        Step("rotate_left_k", {"k": 3}),
        Step("keep_every_kth_position", {"k": 5}),
    )
    if (_semantic_key(position_translation)
            != _semantic_key(translation_before_positions)
            or any(_apply_procedure(position_translation, values)
                   != _apply_procedure(translation_before_positions, values)
                   for values in probes)):
        raise SystemExit("constant translation did not commute with positional selection")

    positional_unique = (
        Step("keep_every_kth_position", {"k": 6}),
        Step("stable_unique", {}), Step("add_k", {"k": -10}))
    positional_without_unique = (
        Step("keep_every_kth_position", {"k": 6}),
        Step("add_k", {"k": -10}))
    probe, outputs = _contrastive_probe(
        [positional_unique, positional_without_unique])
    if (probe is None or outputs is None or len(probe) != 12
            or len({tuple(output) for output in outputs}) != 2
            or _apply_procedure(positional_unique, probe)
            == _apply_procedure(positional_without_unique, probe)):
        raise SystemExit("contrastive search missed duplicate selected positions")

    absolute_rotation = (
        Step("absolute_values", {}), Step("rotate_left_k", {"k": 1}))
    absolute_split_rotations = (
        Step("rotate_left_k", {"k": 3}), Step("absolute_values", {}),
        Step("rotate_left_k", {"k": -2}))
    if (_semantic_key(absolute_rotation)
            != _semantic_key(absolute_split_rotations)
            or any(_apply_procedure(absolute_rotation, values)
                   != _apply_procedure(absolute_split_rotations, values)
                   for values in probes)):
        raise SystemExit("rotations around absolute value were not combined")

    learner = CRMSModel(max_composition_depth=3, max_workers=1)
    for values in ([1, -6, 9, 7, -1, -4, -3], [0, 0]):
        expected = [value * value - 8 for value in values]
        learned = learner.teach("square then subtract eight",
                                [(values, expected)])
    if (learned.status != "learned"
            or learner.predict("square then subtract eight", [2, -3]).output
            != [-4, 1]):
        raise SystemExit("square/shift composition did not generalize after its probe")

    # Contiguous pointwise affine operations are reducible even inside
    # conservative sequence-sensitive keys; they must not disappear from the
    # candidate grammar or fragment equivalent procedures into false classes.
    affine_aliases = (
        ((Step("add_k", {"k": 2}), Step("add_k", {"k": 4}),
          Step("add_k", {"k": 2}), Step("cumulative_sum", {})),
         (Step("add_k", {"k": 8}), Step("cumulative_sum", {}))),
        ((Step("drop_first", {}), Step("add_k", {"k": 8}),
          Step("add_k", {"k": 1}), Step("rotate_left_k", {"k": 4})),
         (Step("drop_first", {}), Step("add_k", {"k": 9}),
          Step("rotate_left_k", {"k": 4}))),
        ((Step("add_k", {"k": -9}), Step("adjacent_difference", {}),
          Step("add_k", {"k": -10}), Step("add_k", {"k": -5})),
         (Step("adjacent_difference", {}), Step("add_k", {"k": -15}))),
        ((Step("double", {}), Step("adjacent_difference", {})),
         (Step("adjacent_difference", {}), Step("double", {}))),
        ((Step("keep_multiples_k", {"k": 4}),
          Step("add_k", {"k": -9}), Step("rotate_left_k", {"k": -2}),
          Step("drop_last", {})),
         (Step("keep_multiples_k", {"k": 4}),
          Step("rotate_left_k", {"k": -2}), Step("drop_last", {}),
          Step("add_k", {"k": -9}))),
        ((Step("scale_k", {"k": -5}), Step("rotate_left_k", {"k": -3}),
          Step("cumulative_sum", {}), Step("add_k", {"k": 4})),
         (Step("rotate_left_k", {"k": -3}), Step("cumulative_sum", {}),
          Step("scale_k", {"k": -5}), Step("add_k", {"k": 4}))),
    )
    for left, right in affine_aliases:
        if _semantic_key(left) != _semantic_key(right):
            raise SystemExit(f"contiguous affine run was not canonicalized: {left}")
        if any(_apply_procedure(left, values) != _apply_procedure(right, values)
               for values in probes):
            raise SystemExit(f"affine-run rewrite changed behavior: {left}")

    repeated_filtered_rotation = (
        Step("repeat_each_k", {"k": 2}),
        Step("keep_multiples_k", {"k": 6}),
        Step("rotate_left_k", {"k": 3}),
        Step("keep_greater_than_first", {}),
    )
    aligned_filtered_rotation = (
        Step("keep_multiples_k", {"k": 6}),
        Step("repeat_each_k", {"k": 2}),
        Step("rotate_left_k", {"k": 2}),
        Step("keep_greater_than_first", {}),
    )
    if _semantic_key(repeated_filtered_rotation) != _semantic_key(
            aligned_filtered_rotation):
        raise SystemExit("repeat/filter/rotation alias was not canonicalized")
    for size in range(5):
        for values in product(range(-3, 4), repeat=size):
            values = list(values)
            if (_apply_procedure(repeated_filtered_rotation, values)
                    != _apply_procedure(aligned_filtered_rotation, values)):
                raise SystemExit(
                    f"repeat/filter/rotation rewrite changed behavior on {values}")

    # Regression: affine arithmetic before vs. after add_first is equivalent
    # when all value filters have already selected the same first survivor.
    filtered_relative_left = (
        Step("keep_multiples_k", {"k": 6}), Step("scale_k", {"k": 4}),
        Step("add_k", {"k": 10}), Step("add_first", {}),
    )
    filtered_relative_right = (
        Step("keep_multiples_k", {"k": 6}), Step("add_first", {}),
        Step("add_k", {"k": 5}), Step("scale_k", {"k": 4}),
    )
    if _semantic_key(filtered_relative_left) != _semantic_key(
            filtered_relative_right):
        raise SystemExit("filtered input-relative affine alias was not canonicalized")
    for size in range(5):
        for values in product(range(-3, 4), repeat=size):
            values = list(values)
            if (_apply_procedure(filtered_relative_left, values)
                    != _apply_procedure(filtered_relative_right, values)):
                raise SystemExit(
                    "filtered input-relative rewrite changed behavior "
                    f"on {values}")

    rotated_subtraction = (
        Step("rotate_left_k", {"k": -3}), Step("subtract_first", {}),
        Step("scale_k", {"k": 4}), Step("keep_multiples_k", {"k": 5}),
    )
    scaled_rotation = (
        Step("scale_k", {"k": 4}), Step("rotate_left_k", {"k": -3}),
        Step("subtract_first", {}), Step("keep_multiples_k", {"k": 5}),
    )
    invertible_post_filter_scale = (
        Step("rotate_left_k", {"k": -3}), Step("subtract_first", {}),
        Step("keep_multiples_k", {"k": 5}), Step("scale_k", {"k": 4}),
    )
    expected_key = _semantic_key(rotated_subtraction)
    if any(_semantic_key(program) != expected_key for program in (
            scaled_rotation, invertible_post_filter_scale)):
        raise SystemExit("rotated subtraction/filter affine alias was not canonicalized")
    for size in range(5):
        for values in product(range(-3, 4), repeat=size):
            values = list(values)
            expected = _apply_procedure(rotated_subtraction, values)
            if any(_apply_procedure(program, values) != expected for program in (
                    scaled_rotation, invertible_post_filter_scale)):
                raise SystemExit(
                    "rotated subtraction/filter rewrite changed behavior "
                    f"on {values}")

    # A non-invertible scale must not move across the modular filter.
    noninvertible = (
        Step("rotate_left_k", {"k": -3}), Step("subtract_first", {}),
        Step("keep_multiples_k", {"k": 5}), Step("scale_k", {"k": 5}),
    )
    if _semantic_key(noninvertible) == expected_key:
        raise SystemExit("non-invertible post-filter scale was merged unsafely")

    repeated_rotated_relative = (
        Step("keep_multiples_k", {"k": 6}),
        Step("repeat_each_k", {"k": 2}),
        Step("rotate_left_k", {"k": 3}),
        Step("keep_greater_than_first", {}),
    )
    rotation_before_repeat = (
        Step("keep_multiples_k", {"k": 6}),
        Step("rotate_left_k", {"k": 1}),
        Step("repeat_each_k", {"k": 2}),
        Step("keep_greater_than_first", {}),
    )
    if _semantic_key(repeated_rotated_relative) != _semantic_key(
            rotation_before_repeat):
        raise SystemExit("rotation/repetition relative-filter alias was not canonicalized")
    for size in range(5):
        for values in product(range(-3, 4), repeat=size):
            values = list(values)
            if (_apply_procedure(repeated_rotated_relative, values)
                    != _apply_procedure(rotation_before_repeat, values)):
                raise SystemExit(
                    "rotation/repetition rewrite changed behavior "
                    f"on {values}")

    operations = model._steps
    collisions = 0
    for depth in (1, 2, 3):
        representatives: dict[tuple, tuple[Step, ...]] = {}
        for program in product(operations, repeat=depth):
            key = _semantic_key(program)
            previous = representatives.get(key)
            if previous is None:
                representatives[key] = program
                continue
            collisions += 1
            for values in probes:
                left = _apply_procedure(previous, values)
                right = _apply_procedure(program, values)
                if left != right:
                    raise SystemExit(
                        "FALSE_EQUIVALENCE\n"
                        f"prior: {previous!r}\nprogram: {program!r}\n"
                        f"input: {values!r}\noutputs: {left!r} vs {right!r}")
    print("semantic-key collision audit: PASS")
    print(f"depths=1..3, probes={len(probes)}, checked_collisions={collisions}")


if __name__ == "__main__":
    main()
