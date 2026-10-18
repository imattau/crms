"""Discover and compose a prefix-accumulation rule from demonstrations.

Run from the project root with:
    python3 experiments/v1_127_cumulative_sum_discovery.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _semantic_key


def main() -> None:
    expected = [{"operation": "cumulative_sum", "parameters": {}}]
    examples = [([1, 2, 3], [1, 3, 6]),
                ([3, -2, 4], [3, 1, 5]),
                ([], []), ([5], [5])]
    split_translation = (Step("add_k", {"k": 2}),
                         Step("add_k", {"k": 4}),
                         Step("add_k", {"k": 2}),
                         Step("cumulative_sum", {}))
    combined_translation = (Step("add_k", {"k": 8}),
                            Step("cumulative_sum", {}))
    if _semantic_key(split_translation) != _semantic_key(combined_translation):
        raise SystemExit("affine steps around cumulative sum were not normalized")

    # A singleton cannot distinguish accumulation from identity or other
    # singleton-preserving rules. Adding a mixed-sign sequence resolves it.
    ambiguity = CRMSModel(max_composition_depth=1, max_workers=1)
    first = ambiguity.teach("running total", [([5], [5])])
    if first.status != "need_more_examples":
        raise SystemExit(f"singleton evidence selected a rule: {first}")
    learned = ambiguity.teach("running total", examples[:3])
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"cumulative sum was not uniquely learned: {learned}")

    for values, output in [([10, -3, 2], [10, 7, 9]), ([], []),
                           ([7], [7]), ([-2, -5, 3], [-2, -7, -4])]:
        prediction = ambiguity.predict("running total", values)
        if prediction.status != "ok" or prediction.output != output:
            raise SystemExit(f"held-out cumulative sum failed: {prediction}")

    # The learned primitive must compose with a separately taught procedure.
    composed = CRMSModel(max_composition_depth=1, max_workers=1)
    if composed.teach("running total", examples).status != "learned":
        raise SystemExit("cumulative sum component failed to learn")
    doubling = composed.teach("double every value", [([1, 2], [2, 4]),
                                                       ([3, -1], [6, -2])])
    if doubling.status != "learned":
        raise SystemExit(f"double component failed to learn: {doubling}")
    prediction = composed.predict(
        "running total, then double every value", [2, 1, -3])
    if prediction.status != "ok" or prediction.output != [4, 6, 0]:
        raise SystemExit(f"cumulative sum composition failed: {prediction}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "memory.json"
        ambiguity.save(path)
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        prediction = restored.predict("running total", [4, -1, 2])
        if prediction.status != "ok" or prediction.output != [4, 3, 5]:
            raise SystemExit(f"persisted cumulative sum failed: {prediction}")

    print("cumulative sum discovery diagnostic: PASS")
    print("ambiguity, mixed-sign and edge cases, composition, held-out use, persistence: PASS")


if __name__ == "__main__":
    main()
