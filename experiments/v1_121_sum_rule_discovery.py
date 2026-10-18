"""Learn and compose a reduction rule from numeric demonstrations.

Run from the project root with:
    python3 experiments/v1_121_sum_rule_discovery.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = [([1, 2, 3], [6]), ([-4, 1], [-3]), ([], [0])]
    learned = model.teach("sum the values", examples)
    expected = [{"operation": "sum_values", "parameters": {}}]
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"sum rule was not uniquely learned: {learned}")
    held_out = model.predict("sum the values", [10, -3, 2])
    if held_out.status != "ok" or held_out.output != [9]:
        raise SystemExit(f"sum rule failed held-out values: {held_out}")
    empty = model.predict("sum the values", [])
    if empty.status != "ok" or empty.output != [0]:
        raise SystemExit(f"empty sum did not use the documented identity: {empty}")

    # A singleton example cannot distinguish reduction from endpoint/identity
    # behavior. The learner must retain ambiguity until empty and multi-item
    # evidence establishes the reducing rule.
    ambiguity = CRMSModel(max_composition_depth=1, max_workers=1)
    first = ambiguity.teach("reduce", [([4], [4])])
    if first.status != "need_more_examples":
        raise SystemExit(f"singleton evidence incorrectly selected a rule: {first}")
    resolved = ambiguity.teach("reduce", [([], [0]), ([2, 5], [7])])
    if (resolved.status != "learned"
            or resolved.procedure != expected):
        raise SystemExit(f"contrastive aggregation evidence failed: {resolved}")

    # Learned components compose through the same explicit connective path as
    # existing list operations.
    composed = CRMSModel(max_composition_depth=1, max_workers=1)
    if composed.teach("sum values", examples).status != "learned":
        raise SystemExit("sum component failed to learn")
    if composed.teach("double the result", [([3, 1], [6, 2]),
                                             ([-2, 5], [-4, 10])]).status != "learned":
        raise SystemExit("double component failed to learn")
    composition = composed.predict(
        "sum values, then double the result", [2, -5, 6])
    if composition.status != "ok" or composition.output != [6]:
        raise SystemExit(f"sum/double language composition failed: {composition}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "memory.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        persisted = restored.predict("sum the values", [8, -1])
        if persisted.status != "ok" or persisted.output != [7]:
            raise SystemExit(f"sum rule failed after persistence: {persisted}")

    print("sum rule discovery diagnostic: PASS")
    print("example discovery, empty-input behavior, ambiguity, composed instruction, held-out prediction, persistence: PASS")


if __name__ == "__main__":
    main()
