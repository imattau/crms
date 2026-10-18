"""Verify a discovered expression composes with an existing rule operation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def pair_examples(base: int):
    examples = []
    signed_pattern = [-4, 2, 0, -7, 3, 5, -1, 8]
    for row in range(5):
        start = (base + row) % len(signed_pattern)
        inputs = [signed_pattern[(start + index) % len(signed_pattern)]
                  for index in range(7 + row % 2)]
        examples.append((inputs, [left * left + right
                                  for left, right in zip(inputs, inputs[1:])]))
    return examples


def main() -> None:
    support_phrases = {
        "square the first value and add the second": 3,
        "add the second number to the first squared": 11,
        "for each pair take the first times itself plus the next": 19,
    }
    descriptor = {
        "operation": "map_window_expression",
        "expression": "(+ (* x x) y)",
        "stride": 1,
    }
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "composed-expression.json"
        model = CRMSModel(memory, max_composition_depth=2, max_workers=1)
        for phrase, base in support_phrases.items():
            if model.teach(phrase, pair_examples(base)).status != "no_fit":
                raise SystemExit(f"expression-support phrase unexpectedly fit: {phrase}")
        proposals = [item for item in model.propose_primitive_candidates()
                     if item["descriptor"].get("operation")
                     == "map_window_expression"]
        if len(proposals) != 1 or proposals[0]["descriptor"] != descriptor:
            raise SystemExit(f"unexpected expression proposal: {proposals}")
        model.accept_primitive_candidate(descriptor)

        target = "square then reverse adjacent pair results"
        examples = []
        for row in range(8):
            inputs = [(row * 13 + index * index * 7 + 3 * index * 5) % 37 - 18
                      for index in range(7 + row % 2)]
            outputs = [left * left + right
                       for left, right in zip(inputs, inputs[1:])][::-1]
            examples.append((inputs, outputs))
        learned = model.teach(target, examples)
        expected_procedure = [
            {"operation": "map_window_expression",
             "parameters": {"expression_code": 4876, "stride": 1}},
            {"operation": "reverse", "parameters": {}},
        ]
        if learned.status != "learned" or learned.procedure != expected_procedure:
            raise SystemExit(f"composed expression rule was not unique: {learned}")

        probe = [12, -5, 3, 8, -2]
        expected = [left * left + right
                    for left, right in zip(probe, probe[1:])][::-1]
        prediction = model.predict(target, probe)
        if prediction.status != "ok" or prediction.output != expected:
            raise SystemExit(f"composed expression prediction failed: {prediction}")

        restored = CRMSModel(memory, max_composition_depth=2, max_workers=1)
        if restored.accepted_primitive_candidates() != [descriptor]:
            raise SystemExit("composed expression primitive did not persist")
        if restored.predict(target, probe).output != expected:
            raise SystemExit("composed expression procedure did not persist")
        try:
            restored.revoke_primitive_candidate(descriptor)
        except ValueError as error:
            if target not in str(error):
                raise
        else:
            raise SystemExit("expression primitive was revoked while in use")

    print("expression composition: PASS")
    print("discovery, depth-two synthesis, execution, persistence, and "
          "dependency-protected revocation: PASS")


if __name__ == "__main__":
    main()
