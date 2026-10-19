"""Check magnitude ordering and squaring share one exact normal form.

Objective: reduce recombination aliases around a nonlinear value operation.
Setup: compare magnitude-sort/square orders with square/numeric-ascending order.
Metrics: semantic keys and exact runtime outputs.
Failure modes: a proved order retains a separate key or changes any output.
Definition of success: all three forms share a key and output on exhaustive
short inputs and seeded wider lists.
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _apply_procedure, _semantic_key


def main() -> None:
    magnitude = Step("sort_by_magnitude", {})
    square = Step("square_values", {})
    ascending = Step("sort_ascending", {})
    procedures = [
        (magnitude, square),
        (square, magnitude),
        (square, ascending),
    ]
    canonical = _semantic_key(procedures[0])
    if any(_semantic_key(procedure) != canonical for procedure in procedures[1:]):
        raise SystemExit("magnitude-sort/square forms did not canonicalize")

    values_to_check = [
        list(values)
        for length in range(7)
        for values in itertools.product(range(-2, 3), repeat=length)
    ]
    rng = random.Random(313)
    values_to_check.extend(
        [rng.randint(-10**6, 10**6) for _ in range(rng.randint(0, 40))]
        for _ in range(2_000)
    )
    for values in values_to_check:
        outputs = [_apply_procedure(procedure, values)
                   for procedure in procedures]
        if outputs[0] != outputs[1] or outputs[1] != outputs[2]:
            raise SystemExit(f"sorting/squaring outputs differ for {values}: {outputs}")

    print("magnitude-order/square commutation diagnostic: PASS")
    print(f"same_semantic_key=True; runtime_inputs={len(values_to_check)}")


if __name__ == "__main__":
    main()
