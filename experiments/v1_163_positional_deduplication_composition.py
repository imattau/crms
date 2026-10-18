"""Discover order-sensitive positional-selection/deduplication programs."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=2)
    first = [4, 2, 4, 5, 2, 5, 9, 4]
    second = [7, 3, 6, 7, 5, 3, 8, 6, 5]
    select_then_deduplicate = model.teach(
        "deduplicate odd-position values",
        [(first, [4, 2, 9]), (second, [7, 6, 5, 8])])
    deduplicate_then_select = model.teach(
        "take odd positions after deduplicating",
        [(first, [4, 5]), (second, [7, 6, 8])])
    expected_first = [
        {"operation": "keep_odd_positions", "parameters": {}},
        {"operation": "stable_unique", "parameters": {}},
    ]
    expected_second = [
        {"operation": "stable_unique", "parameters": {}},
        {"operation": "keep_odd_positions", "parameters": {}},
    ]
    if (select_then_deduplicate.status != "learned"
            or select_then_deduplicate.procedure != expected_first):
        raise SystemExit(f"select-then-deduplicate was not learned: "
                         f"{select_then_deduplicate}")
    if (deduplicate_then_select.status != "learned"
            or deduplicate_then_select.procedure != expected_second):
        raise SystemExit(f"deduplicate-then-select was not learned: "
                         f"{deduplicate_then_select}")

    held_out = [8, 4, 8, 2, 5, 2, 9, 4]
    first_result = model.predict("deduplicate odd-position values", held_out)
    second_result = model.predict("take odd positions after deduplicating", held_out)
    if (first_result.status != "ok" or first_result.output != [8, 5, 9]
            or second_result.status != "ok" or second_result.output != [8, 2, 9]):
        raise SystemExit(f"deduplication/selection order transfer failed: "
                         f"{first_result}, {second_result}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=2)
        restored.load(path)
        if (restored.predict("deduplicate odd-position values", held_out).output
                != [8, 5, 9]
                or restored.predict("take odd positions after deduplicating", held_out).output
                != [8, 2, 9]):
            raise SystemExit("deduplication/selection order changed after persistence")

    print("positional deduplication composition diagnostic: PASS")
    print("both operation orders, held-out distinction, exact learning, persistence: PASS")


if __name__ == "__main__":
    main()
