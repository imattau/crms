"""Discover order-sensitive compositions of positional selection and rotation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=2)
    first_input = [13, 20, 8, 9, 15, 2, 7, 6, 4]
    second_input = [22, 19, 5, 3, 10, 6, 17, 12]
    select_then_rotate = model.teach(
        "keep odd positions then rotate left one",
        [(first_input, [8, 15, 7, 4, 13]),
         (second_input, [5, 10, 17, 22])])
    rotate_then_select = model.teach(
        "rotate left one then keep odd positions",
        [(first_input, [20, 9, 2, 6, 13]),
         (second_input, [19, 3, 6, 12])])
    expected_first = [
        {"operation": "keep_odd_positions", "parameters": {}},
        {"operation": "rotate_left_k", "parameters": {"k": 1}},
    ]
    expected_second = [
        {"operation": "rotate_left_k", "parameters": {"k": 1}},
        {"operation": "keep_odd_positions", "parameters": {}},
    ]
    if select_then_rotate.status != "learned" or select_then_rotate.procedure != expected_first:
        raise SystemExit(f"select-then-rotate was not learned: {select_then_rotate}")
    if rotate_then_select.status != "learned" or rotate_then_select.procedure != expected_second:
        raise SystemExit(f"rotate-then-select was not learned: {rotate_then_select}")

    held_out = [31, 18, 6, 20, 14, 9, 25]
    first_result = model.predict("keep odd positions then rotate left one", held_out)
    second_result = model.predict("rotate left one then keep odd positions", held_out)
    if (first_result.status != "ok" or first_result.output != [6, 14, 25, 31]
            or second_result.status != "ok"
            or second_result.output != [18, 20, 9, 31]):
        raise SystemExit(f"rotation/selection order transfer failed: "
                         f"{first_result}, {second_result}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=2)
        restored.load(path)
        if (restored.predict("keep odd positions then rotate left one", held_out).output
                != [6, 14, 25, 31]
                or restored.predict("rotate left one then keep odd positions", held_out).output
                != [18, 20, 9, 31]):
            raise SystemExit("rotation/selection order changed after persistence")

    print("positional rotation composition diagnostic: PASS")
    print("both operation orders, held-out distinction, exact learning, persistence: PASS")


if __name__ == "__main__":
    main()
