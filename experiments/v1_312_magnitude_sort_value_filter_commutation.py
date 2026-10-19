"""Check stable magnitude sorting commutes with value-only filters.

Objective: reduce recombination aliases using an exact stable-order law.
Setup: compare stable magnitude sorting before/after parity and multiples filters.
Metrics: canonical keys and exact outputs, plus noncommuting negative controls.
Failure modes: equivalent pairs retain distinct keys or an unsafe pair merges.
Definition of success: safe pairs share keys and outputs on exhaustive and
seeded inputs; first-relative and positional filters remain distinct.
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
    magnitude_sort = Step("sort_by_magnitude", {})
    filters = [Step("keep_evens", {}), Step("keep_odds", {})]
    filters.extend(Step("keep_multiples_k", {"k": k}) for k in range(1, 7))
    inputs = [
        list(values)
        for length in range(6)
        for values in itertools.product(range(-3, 4), repeat=length)
    ]
    rng = random.Random(312)
    inputs.extend(
        [rng.randint(-100, 100) for _ in range(rng.randint(0, 50))]
        for _ in range(1_000)
    )

    for value_filter in filters:
        sort_then_filter = (magnitude_sort, value_filter)
        filter_then_sort = (value_filter, magnitude_sort)
        require(_semantic_key(sort_then_filter) == _semantic_key(filter_then_sort),
                f"value filter did not canonicalize with magnitude sort: {value_filter}")
        for values in inputs:
            require(_apply_procedure(sort_then_filter, values)
                    == _apply_procedure(filter_then_sort, values),
                    f"magnitude/filter outputs differ: {value_filter}, {values}")

    values = [-10, 1, 2]
    first_relative = Step("keep_greater_than_first", {})
    left, right = (magnitude_sort, first_relative), (first_relative, magnitude_sort)
    require(_semantic_key(left) != _semantic_key(right)
            and _apply_procedure(left, values) != _apply_procedure(right, values),
            "first-relative counterexample was incorrectly normalized")

    values = [-2, 3, 1]
    positional = Step("keep_even_positions", {})
    left, right = (magnitude_sort, positional), (positional, magnitude_sort)
    require(_semantic_key(left) != _semantic_key(right)
            and _apply_procedure(left, values) != _apply_procedure(right, values),
            "positional counterexample was incorrectly normalized")

    print("magnitude-sort/value-filter commutation diagnostic: PASS")
    print(f"safe_filters={len(filters)}; runtime_inputs_per_filter={len(inputs)}")
    print("first-relative and positional counterexamples remain distinct: PASS")


if __name__ == "__main__":
    main()
