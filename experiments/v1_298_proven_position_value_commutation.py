"""Canonicalize a proved pointwise-map/position-selector commutation.

Objective: collapse exact aliases so recombination search does not mistake
the same procedure for distinct behaviors.
Setup: compare absolute-value mapping before and after every-kth-position
selection; the selector depends only on ordinal positions.
Metrics: canonical semantic keys and exact runtime outputs.
Failure modes: equivalent procedures retain separate keys or normalization
changes an output for any finite input checked here.
Definition of success: both orders share a semantic key and produce identical
outputs over exhaustive short inputs and seeded wider lists.

Run from the project root with:
    python3 experiments/v1_298_proven_position_value_commutation.py
"""

from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _apply_procedure, _semantic_key


def main() -> None:
    absolute = Step("absolute_values", {})
    positional = Step("keep_every_kth_position", {"k": 6})
    left_to_right = (absolute, positional)
    right_to_left = (positional, absolute)
    if _semantic_key(left_to_right) != _semantic_key(right_to_left):
        raise SystemExit("proved commutation did not share a semantic key")

    inputs = [list(values)
              for length in range(7)
              for values in itertools.product(range(-2, 3), repeat=length)]
    rng = random.Random(298)
    inputs.extend([[rng.randint(-1_000, 1_000)
                    for _ in range(rng.randint(0, 30))]
                   for _ in range(1_000)])
    for values in inputs:
        if (_apply_procedure(left_to_right, values)
                != _apply_procedure(right_to_left, values)):
            raise SystemExit(f"runtime commutation failed for {values}")

    print("proven position/value commutation: PASS")
    print(f"same_semantic_key=True; runtime_inputs={len(inputs)}")


if __name__ == "__main__":
    main()
