"""Discover order-sensitive compositions of positional selection and reversal."""

from __future__ import annotations

import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=2)
    select_then_reverse_examples = [
        ([10, 3, 12, 7, 5, 20, 8, 14, 1], [1, 8, 5, 12, 10]),
        ([21, 4, 18, 6, 9, 15, 2, 5], [2, 9, 18, 21]),
    ]
    reverse_then_select_examples = [
        ([10, 3, 12, 7, 5, 20, 8, 14, 1], [1, 8, 5, 12, 10]),
        ([21, 4, 18, 6, 9, 15, 2, 5], [5, 15, 6, 4]),
    ]
    first = model.teach(
        "reverse the odd-positioned values", select_then_reverse_examples)
    second = model.teach(
        "take odd positions after reversing", reverse_then_select_examples)
    expected_first = [
        {"operation": "keep_odd_positions", "parameters": {}},
        {"operation": "reverse", "parameters": {}},
    ]
    expected_second = [
        {"operation": "reverse", "parameters": {}},
        {"operation": "keep_odd_positions", "parameters": {}},
    ]
    if first.status != "learned" or first.procedure != expected_first:
        raise SystemExit(f"select-then-reverse was not learned: {first}")
    if second.status != "learned" or second.procedure != expected_second:
        raise SystemExit(f"reverse-then-select was not learned: {second}")

    held_out = [35, 18, 20, 17, 14, 13, 12, 11]
    first_result = model.predict("reverse the odd-positioned values", held_out)
    second_result = model.predict("take odd positions after reversing", held_out)
    if (first_result.status != "ok" or first_result.output != [12, 14, 20, 35]
            or second_result.status != "ok"
            or second_result.output != [11, 13, 17, 18]):
        raise SystemExit(f"order-sensitive transfer failed: {first_result}, {second_result}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=2)
        restored.load(path)
        if (restored.predict("reverse the odd-positioned values", held_out).output
                != [12, 14, 20, 35]
                or restored.predict("take odd positions after reversing", held_out).output
                != [11, 13, 17, 18]):
            raise SystemExit("order-sensitive compositions changed after persistence")

    print("positional reversal composition diagnostic: PASS")
    print("both operation orders, held-out distinction, exact learning, persistence: PASS")


if __name__ == "__main__":
    main()
