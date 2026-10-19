"""Check safe stable-unique commutations and retain known counterexamples.

Objective: reduce recombination aliases only for exactly proved laws.
Setup: compare stable deduplication against injective value maps, value filters,
and total sorting; include operations that must not be canonicalized.
Metrics: semantic-key equality and exact procedure outputs.
Failure modes: a valid law keeps separate keys, or an unsafe pair merges.
Definition of success: safe pairs share keys and outputs on exhaustive and
seeded inputs, while zero-scaling and position-selection pairs stay distinct.
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _apply_procedure, _semantic_key


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    unique = Step("stable_unique", {})
    commuting = [
        Step("double", {}),
        Step("scale_k", {"k": -3}),
        Step("scale_k", {"k": 2}),
        Step("add_k", {"k": 7}),
        Step("add_first", {}),
        Step("subtract_first", {}),
        Step("keep_evens", {}),
        Step("keep_odds", {}),
        Step("keep_multiples_k", {"k": 3}),
        Step("keep_greater_than_first", {}),
        Step("keep_less_than_first", {}),
        Step("sort_ascending", {}),
        Step("sort_descending", {}),
    ]
    pairs = [((unique, operation), (operation, unique))
             for operation in commuting]

    values_to_check = [
        list(values)
        for length in range(6)
        for values in itertools.product(range(-2, 3), repeat=length)
    ]
    rng = random.Random(311)
    values_to_check.extend(
        [rng.randint(-50, 50) for _ in range(rng.randint(0, 40))]
        for _ in range(500)
    )

    for before, after in pairs:
        require(_semantic_key(before) == _semantic_key(after),
                f"safe pair did not canonicalize: {before} vs {after}")
        for values in values_to_check:
            require(_apply_procedure(before, values)
                    == _apply_procedure(after, values),
                    f"safe pair changed output: {before}, {after}, {values}")

    unsafe = [
        (Step("scale_k", {"k": 0}), [1, 2]),
        (Step("keep_even_positions", {}), [1, 2, 1, 3]),
        (Step("keep_odd_positions", {}), [1, 2, 1, 3]),
        (Step("keep_every_kth_position", {"k": 2}), [1, 2, 1, 3]),
    ]
    for operation, values in unsafe:
        left, right = (operation, unique), (unique, operation)
        require(_semantic_key(left) != _semantic_key(right),
                f"unsafe pair was merged: {left} vs {right}")
        require(_apply_procedure(left, values) != _apply_procedure(right, values),
                f"counterexample input did not distinguish {operation}: {values}")

    print("stable-unique commutation diagnostic: PASS")
    print(f"safe_pairs={len(pairs)}; runtime_inputs_per_pair={len(values_to_check)}")
    print(f"unsafe_counterexamples={len(unsafe)}; zero-scale and position selectors kept distinct")


if __name__ == "__main__":
    main()
