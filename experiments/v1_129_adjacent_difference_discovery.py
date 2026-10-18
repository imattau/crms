"""Learn adjacent differences and compose the rule with prefix accumulation.

Run from the project root with:
    python3 experiments/v1_129_adjacent_difference_discovery.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    expected = [{"operation": "adjacent_difference", "parameters": {}}]
    examples = [([1, 4, 2, 10], [3, -2, 8]),
                ([5, -1, -3], [-6, -2]), ([], []), ([9], [])]

    # A singleton-to-empty example also fits deletion and filtering rules.
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    ambiguous = model.teach("adjacent gaps", [([9], [])])
    if ambiguous.status != "need_more_examples":
        raise SystemExit(f"singleton evidence selected a rule: {ambiguous}")
    learned = model.teach("adjacent gaps", examples[:3])
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"adjacent difference was not uniquely learned: {learned}")

    for values, output in [([10, -3, 2], [-13, 5]), ([], []),
                           ([7], []), ([-4, -9, 1], [-5, 10])]:
        prediction = model.predict("adjacent gaps", values)
        if prediction.status != "ok" or prediction.output != output:
            raise SystemExit(f"held-out adjacent difference failed: {prediction}")

    # Compose two example-learned operators through the existing language path.
    composed = CRMSModel(max_composition_depth=1, max_workers=1)
    if composed.teach("adjacent gaps", examples).status != "learned":
        raise SystemExit("adjacent difference component failed to learn")
    totals = composed.teach(
        "running total", [([1, 2, 3], [1, 3, 6]),
                          ([3, -2, 4], [3, 1, 5]), ([], [])])
    if totals.status != "learned":
        raise SystemExit(f"cumulative sum component failed to learn: {totals}")
    prediction = composed.predict(
        "adjacent gaps, then running total", [4, 7, 2, 10])
    if prediction.status != "ok" or prediction.output != [3, -2, 6]:
        raise SystemExit(f"difference/total composition failed: {prediction}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "memory.json"
        model.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        prediction = restored.predict("adjacent gaps", [2, 8, -1])
        if prediction.status != "ok" or prediction.output != [6, -9]:
            raise SystemExit(f"persisted adjacent difference failed: {prediction}")

    print("adjacent difference discovery diagnostic: PASS")
    print("ambiguity, edge cases, mixed-sign transfer, learned composition, persistence: PASS")


if __name__ == "__main__":
    main()
