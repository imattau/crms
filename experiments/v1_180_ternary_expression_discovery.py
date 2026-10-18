"""Check held-out discovery and acceptance of a three-position expression."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def examples(base: int):
    pairs = []
    for row in range(5):
        values = [base + row * 5 + ((index * index * 3 + index * 7
                                     + row * 11) % 31) - 12
                  for index in range(7 + row % 2)]
        outputs = [left * left + third
                   for left, _middle, third in
                   zip(values, values[1:], values[2:])]
        pairs.append((values, outputs))
    return pairs


def main() -> None:
    phrases = {
        "square the first value and add the third": 3,
        "combine first squared with third in each triple": 11,
        "for every three values add the last to the first squared": 19,
    }
    expected = {
        "operation": "map_window_expression",
        "expression": "(+ (* x x) z)",
        "stride": 1,
        "window_width": 3,
    }
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "ternary.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        held_out = {}
        for phrase, base in phrases.items():
            training = examples(base)
            if model.teach(phrase, training).status != "no_fit":
                raise SystemExit(f"ternary fixture unexpectedly fit: {phrase}")
            held_out[phrase] = training[-1]

        proposals = [item for item in model.propose_primitive_candidates()
                     if item["descriptor"].get("operation")
                     == "map_window_expression"]
        matches = [item for item in proposals if item["descriptor"] == expected]
        if (len(matches) != 1 or not matches[0]["held_out_valid"]
                or not matches[0]["mdl_gate_passed"]):
            raise SystemExit(f"three-position expression was not uniquely proposed: {proposals}")
        model.accept_primitive_candidate(expected)
        for phrase in phrases:
            learned = model.retry(phrase)
            if (learned.status != "learned" or learned.procedure is None
                    or learned.procedure[0]["operation"] != "map_window_expression"):
                raise SystemExit(f"ternary rule did not synthesize: {learned}")
            inputs, outputs = held_out[phrase]
            if model.predict(phrase, inputs).output != outputs:
                raise SystemExit(f"ternary rule failed held-out prediction: {phrase}")

        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        if restored.accepted_primitive_candidates() != [expected]:
            raise SystemExit("three-position primitive did not persist")
        phrase = next(iter(phrases))
        inputs = [4, -3, 8, 2, -5]
        outputs = [left * left + third
                   for left, _middle, third in
                   zip(inputs, inputs[1:], inputs[2:])]
        if restored.predict(phrase, inputs).output != outputs:
            raise SystemExit("persisted ternary expression predicted incorrectly")

    print("ternary expression discovery and learning: PASS")
    print("three-cluster holdout/MDL proposal, explicit acceptance, synthesis, "
          "held-out prediction, and persistence: PASS")


if __name__ == "__main__":
    main()
