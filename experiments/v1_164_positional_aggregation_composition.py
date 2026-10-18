"""Learn aggregation over position-selected values and verify singleton laws."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _semantic_key


def main() -> None:
    model = CRMSModel(max_composition_depth=2)
    examples = [
        ([4, 11, 7, 2, 15, 1, 9, 6], [35]),
        ([10, 3, 12, 7, 5, 20, 8, 14, 1], [36]),
    ]
    learned = model.teach("sum odd-position values", examples)
    expected = [
        {"operation": "keep_odd_positions", "parameters": {}},
        {"operation": "sum_values", "parameters": {}},
    ]
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"aggregation over selected positions was not learned: {learned}")
    held_out = [3, 10, -2, 5, 7, -4, 6]
    prediction = model.predict("sum odd-position values", held_out)
    if prediction.status != "ok" or prediction.output != [14]:
        raise SystemExit(f"position-selected aggregate did not transfer: {prediction}")

    total = Step("sum_values", {})
    odd = Step("keep_odd_positions", {})
    even = Step("keep_even_positions", {})
    stride = Step("keep_every_kth_position", {"k": 3})
    if _semantic_key((total, odd)) != _semantic_key((total,)):
        raise SystemExit("odd-position selection after summation was not canonicalized")
    if (_semantic_key((total, even)) != ("always_empty",)
            or _semantic_key((total, stride)) != ("always_empty",)):
        raise SystemExit("positional filter after singleton reduction has a wrong key")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=2)
        restored.load(path)
        result = restored.predict("sum odd-position values", held_out)
        if result.status != "ok" or result.output != [14]:
            raise SystemExit("selected-value aggregation changed after persistence")

    print("positional aggregation composition diagnostic: PASS")
    print("exact learning, held-out transfer, singleton laws, persistence: PASS")


if __name__ == "__main__":
    main()
