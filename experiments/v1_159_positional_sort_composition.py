"""Discover order-sensitive compositions of positional selection and sorting."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=2)
    inputs = [
        [9, 2, 8, 1, 7, 4, 6, 3, 5],
        [17, 20, 11, 14, 13, 16, 15, 12, 19, 10],
    ]
    select_then_sort_examples = [
        (inputs[0], [5, 6, 7, 8, 9]),
        (inputs[1], [11, 13, 15, 17, 19]),
    ]
    sort_then_select_examples = [
        (inputs[0], [1, 3, 5, 7, 9]),
        (inputs[1], [10, 12, 14, 16, 19]),
    ]
    selected = model.teach("sort values at odd positions", select_then_sort_examples)
    sorted_first = model.teach(
        "sort values then select odd positions", sort_then_select_examples)
    expected_selected = [
        {"operation": "keep_odd_positions", "parameters": {}},
        {"operation": "sort_ascending", "parameters": {}},
    ]
    expected_sorted_first = [
        {"operation": "sort_ascending", "parameters": {}},
        {"operation": "keep_odd_positions", "parameters": {}},
    ]
    if selected.status != "learned" or selected.procedure != expected_selected:
        raise SystemExit(f"select-then-sort was not learned: {selected}")
    if (sorted_first.status != "learned"
            or sorted_first.procedure != expected_sorted_first):
        raise SystemExit(f"sort-then-select was not learned: {sorted_first}")

    held_out = [5, 100, 1, 20, 60, 2, 7, 3]
    selected_result = model.predict("sort values at odd positions", held_out)
    sorted_result = model.predict("sort values then select odd positions", held_out)
    if (selected_result.status != "ok" or selected_result.output != [1, 5, 7, 60]
            or sorted_result.status != "ok"
            or sorted_result.output != [1, 3, 7, 60]):
        raise SystemExit(f"order-sensitive sort transfer failed: "
                         f"{selected_result}, {sorted_result}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=2)
        restored.load(path)
        if (restored.predict("sort values at odd positions", held_out).output
                != [1, 5, 7, 60]
                or restored.predict("sort values then select odd positions", held_out).output
                != [1, 3, 7, 60]):
            raise SystemExit("sort/selection order changed after persistence")

    print("positional sort composition diagnostic: PASS")
    print("both operation orders, held-out distinction, exact learning, persistence: PASS")


if __name__ == "__main__":
    main()
