"""Check a bounded fallback for mixed value/position filter candidates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel, Step, _apply_procedure


def main() -> None:
    target = (Step("keep_multiples_k", {"k": 5}),
              Step("keep_even_positions", {}))
    inputs = [[5, 10, 15], [1, 5, 10, 15], [5, 10, 15, 20]]
    examples = [(values, _apply_procedure(target, values)) for values in inputs]
    model = CRMSModel(max_composition_depth=3, max_workers=1)
    result = model.teach("keep multiples then keep even positions", examples)

    target_steps = [
        {"operation": step.operation, "parameters": step.parameters}
        for step in target
    ]
    if target_steps not in (result.candidate_procedures or []):
        raise SystemExit(f"mixed filter was missing from the candidate set: {result}")
    if result.status != "need_more_examples" or model._procedures:
        raise SystemExit(f"ambiguous mixed-filter evidence was committed: {result}")

    # All-empty observations do not identify the structure of the filter.
    # Avoid expanding the special family in that low-information case.
    empty_examples = [([1, 2, 3], []), ([4, 5, 6], [])]
    if model._mixed_position_filter_candidates(empty_examples):
        raise SystemExit("all-empty evidence activated the mixed-filter fallback")

    held_out = [([1, 5, 10, 15, 20], [10, 20]),
                ([5, 10, 15, 20, 25, 30], [10, 20, 30])]
    if any(_apply_procedure(target, values) != expected
           for values, expected in held_out):
        raise SystemExit("mixed filter target produced an incorrect held-out result")

    print("mixed value/position filter fallback diagnostic: PASS")
    print("candidate retained, ambiguity abstained, empty-output gate and held-out semantics: PASS")


if __name__ == "__main__":
    main()
