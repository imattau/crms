"""Check discovery and held-out behavior across the configured primitive space.

Every procedure is inferred only from two input/output examples. The phrase
contains no operation label, and the verification compares behavior rather
than requiring the same syntactic representative. Inputs deliberately vary in
order so identity, reverse, and sorting are distinguishable.

Run from the project root with:
    python3 experiments/v1_12_primitive_discovery_diagnostic.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, _apply_step, _semantic_key


TRAINING_INPUTS = [
    [1, 9, 3, 6, 4, 12, 2],
    [-8, 2, -3, 11, 0, -1, 7, -5],
    [4, 7, 4, -2, 7],
    [3, -5, 8, 1],
]
HELD_OUT_INPUTS = [
    [],
    [5, -2, 0, 3, 8],
    [17, -11, 6, 1],
]


def main() -> None:
    search = CRMSModel(max_composition_depth=1, max_workers=1)
    failures = []
    family_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for index, target_step in enumerate(search._steps):
        instruction = f"operation case {index:03d} transform values"
        examples = [
            (values, _apply_step(target_step, values))
            for values in TRAINING_INPUTS
        ]
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        learned = model.teach(instruction, examples)
        correct = learned.status == "learned"
        if correct:
            inferred = model._procedures[instruction]
            correct = _semantic_key(inferred) == _semantic_key((target_step,))
            if correct:
                correct = all(
                    model.predict(instruction, values).output
                    == _apply_step(target_step, values)
                    for values in HELD_OUT_INPUTS
                )

        family_counts[target_step.operation][1] += 1
        family_counts[target_step.operation][0] += bool(correct)
        if not correct:
            failures.append((target_step, learned.status, learned.candidate_count))

    print("CRMS primitive rule-discovery diagnostic")
    print(f"steps={len(search._steps)} held_out_lists={len(HELD_OUT_INPUTS)}")
    for operation, (passed, total) in sorted(family_counts.items()):
        print(f"{operation}: {passed}/{total}")
    print(f"overall={len(search._steps) - len(failures)}/{len(search._steps)}")
    if failures:
        print(f"failures={failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
