"""Check discovery of order-sensitive two- and three-step procedures.

The teacher-side procedure labels below generate demonstrations only; the
learner receives instruction strings and input/output lists. Evaluation uses
behavioral equivalence, since the learner may return a different but
equivalent canonical procedure.

Run from the project root with:
    python3 experiments/v1_13_composed_rule_discovery_diagnostic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


TRAINING_INPUTS = [
    [1, 9, 3, 6, 4, 12, 2],
    [-8, 2, -3, 11, 0, -1, 7, -5],
    [2, -4, 5, 0, 3],
]
HELD_OUT_INPUTS = [[], [8, -3, 0, 5], [11, 2, -7]]

PROGRAMS = [
    (
        "return the smallest value",
        2,
        (Step("sort_ascending", {}), Step("first", {})),
    ),
    (
        "shift odd values and keep them",
        2,
        (Step("add_k", {"k": 1}), Step("keep_evens", {})),
    ),
    (
        "shift odd values and keep the first",
        3,
        (Step("add_k", {"k": 1}), Step("keep_evens", {}),
         Step("first", {})),
    ),
]


def main() -> None:
    failures = []
    for instruction, depth, target in PROGRAMS:
        model = CRMSModel(max_composition_depth=depth, max_workers=1)
        examples = [
            (values, _apply_procedure(target, values))
            for values in TRAINING_INPUTS
        ]
        learned = model.teach(instruction, examples)
        behavior_matches = (
            learned.status == "learned"
            and _semantic_key(tuple(
                Step(item["operation"], item["parameters"])
                for item in learned.procedure
            )) == _semantic_key(target)
        )
        held_out_matches = behavior_matches and all(
            model.predict(instruction, values).output
            == _apply_procedure(target, values)
            for values in HELD_OUT_INPUTS
        )
        print(
            f"{instruction}: status={learned.status}, "
            f"steps={len(learned.procedure or [])}, "
            f"candidates={learned.candidate_count}, "
            f"held_out={'PASS' if held_out_matches else 'FAIL'}, "
            f"procedure={learned.procedure}"
        )
        if not held_out_matches:
            failures.append(instruction)

    print(f"composed_programs={len(PROGRAMS)} failures={len(failures)}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
