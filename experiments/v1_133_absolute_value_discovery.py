"""Learn the absolute-value list rule, verify composition, and persist it.

Run from the project root with:
    python3 experiments/v1_133_absolute_value_discovery.py
"""

from __future__ import annotations

import sys
import tempfile
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = [([-7, 2, -3], [7, 2, 3]),
                ([4, -9, 1], [4, 9, 1]),
                ([0, -5], [0, 5])]
    learned = model.teach("make each value nonnegative", examples)
    expected = [{"operation": "absolute_values", "parameters": {}}]
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"absolute-value rule was not uniquely learned: {learned}")

    for values, output in (([], []), ([-12, 6, -1], [12, 6, 1]),
                           ([5, -8, 0], [5, 8, 0])):
        prediction = model.predict("make each value nonnegative", values)
        if prediction.status != "ok" or prediction.output != output:
            raise SystemExit(f"held-out magnitude prediction failed: {prediction}")

    # Absolute value commutes with order changes, but not with sorting. The
    # canonicalizer must collapse the proven alias without merging the latter.
    magnitude = Step("absolute_values", {})
    reverse = Step("reverse", {})
    rotate = Step("rotate_left_k", {"k": 2})
    sort = Step("sort_ascending", {})
    repeat = Step("repeat_each_k", {"k": 2})
    odd_positions = Step("keep_odd_positions", {})
    keep_odds = Step("keep_odds", {})
    multiples = Step("keep_multiples_k", {"k": 3})
    first = Step("first", {})
    drop_last = Step("drop_last", {})
    double = Step("double", {})
    negative_scale = Step("scale_k", {"k": -3})
    if _semantic_key((magnitude, reverse)) != _semantic_key((reverse, magnitude)):
        raise SystemExit("absolute value and reversal alias was not canonicalized")
    if _semantic_key((magnitude, rotate)) != _semantic_key((rotate, magnitude)):
        raise SystemExit("absolute value and rotation alias was not canonicalized")
    for structure in (repeat, odd_positions, keep_odds, multiples, first,
                      drop_last):
        if (_semantic_key((magnitude, structure))
                != _semantic_key((structure, magnitude))):
            raise SystemExit(
                f"absolute value did not commute with {structure.operation}")
    for scale in (double, negative_scale):
        if (_semantic_key((scale, magnitude))
                != _semantic_key((magnitude, double if scale is double else
                                  Step("scale_k", {"k": 3})))):
            raise SystemExit(
                f"absolute value did not normalize across {scale.operation}")
    if _semantic_key((magnitude, magnitude)) != _semantic_key((magnitude,)):
        raise SystemExit("repeated absolute value was not canonicalized")
    if _semantic_key((magnitude, sort)) == _semantic_key((sort, magnitude)):
        raise SystemExit("non-equivalent absolute-value/sort programs were merged")

    # Check every same-key collision in a small generated grammar against all
    # short lists over a signed alphabet. This is a regression guard against
    # accidental equivalences in the nonlinear fallback.
    operations = (magnitude, reverse, rotate, sort, Step("keep_evens", {}),
                  repeat, odd_positions, keep_odds, multiples, first, drop_last,
                  double, negative_scale)
    programs = ([(step,) for step in operations]
                + list(product(operations, repeat=2))
                + list(product(operations, repeat=3)))
    short_lists = [list(values) for length in range(5)
                   for values in product(range(-2, 3), repeat=length)]
    seen_by_key = {}
    for program in programs:
        key = _semantic_key(program)
        behavior = tuple(tuple(_apply_procedure(program, values))
                         for values in short_lists)
        prior = seen_by_key.get(key)
        if prior is not None and prior[0] != behavior:
            raise SystemExit(
                f"semantic-key collision: {prior[1]} vs {program}")
        seen_by_key[key] = behavior, program

    composed = CRMSModel(max_composition_depth=2, max_workers=1)
    compound = composed.teach(
        "magnitude values then reverse",
        [([-7, 2, -3], [3, 2, 7]),
         ([4, -9, 1], [1, 9, 4]),
         ([0, -5, 6], [6, 5, 0])])
    expected_compound = [expected[0], {"operation": "reverse", "parameters": {}}]
    if compound.status != "learned" or compound.procedure != expected_compound:
        raise SystemExit(f"magnitude/reversal composition failed: {compound}")
    held_out = composed.predict("magnitude values then reverse", [-11, 3, -2])
    if held_out.status != "ok" or held_out.output != [2, 3, 11]:
        raise SystemExit(f"held-out composition failed: {held_out}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "memory.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        prediction = restored.predict("make each value nonnegative", [-4, 0, 9])
        if prediction.status != "ok" or prediction.output != [4, 0, 9]:
            raise SystemExit(f"persisted absolute-value rule failed: {prediction}")

    print("absolute-value rule discovery diagnostic: PASS")
    print("unique learning, held-out transfer, exact canonicalization, composition, persistence: PASS")
    print(f"canonicalizer audit: {len(programs)} programs × {len(short_lists)} short lists, no collisions")


if __name__ == "__main__":
    main()
