"""Discover and learn an expression containing unary absolute value."""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_expression_discovery import propose_window_expression_primitives
from crms_model import CRMSModel


PHRASES = [
    "find the absolute difference of adjacent values",
    "take the magnitude of the first minus the next",
    "for each pair return how far apart the values are",
]
DESCRIPTOR = {
    "operation": "map_window_expression",
    "expression": "(abs (- x y))",
    "stride": 1,
}


def make_examples(variant: int):
    examples = []
    for row in range(6):
        inputs = [((variant + 2) * 17 + row * 11 + index * index * 5
                   + index * 13) % 53 - 26
                  for index in range(7 + row % 2)]
        examples.append((inputs, [abs(left - right)
                                  for left, right in zip(inputs, inputs[1:])]))
    return examples


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "absolute-expression.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        held_out = {}
        for variant, phrase in enumerate(PHRASES):
            examples = make_examples(variant)
            if model.teach(phrase, examples).status != "no_fit":
                raise SystemExit(f"absolute-difference phrase unexpectedly fit: {phrase}")
            held_out[phrase] = examples[-1]

        proposals = [item for item in model.propose_primitive_candidates()
                     if item["descriptor"].get("operation")
                     == "map_window_expression"]
        if (len(proposals) != 1 or proposals[0]["descriptor"] != DESCRIPTOR
                or not proposals[0]["held_out_valid"]
                or not proposals[0]["mdl_gate_passed"]):
            raise SystemExit(f"absolute expression was not uniquely proposed: {proposals}")

        corrupted = copy.deepcopy(model.no_fit_cases())
        for record in corrupted:
            index = record["proposal_split"]["held_out_indices"][0]
            record["examples"][index][1][0] += 1
        if propose_window_expression_primitives(
                corrupted, minimum_supporting_phrases=len(PHRASES)):
            raise SystemExit("absolute-expression proposal survived bad holdouts")

        model.accept_primitive_candidate(DESCRIPTOR)
        for phrase in PHRASES:
            learned = model.retry(phrase)
            if learned.status != "learned" or learned.procedure is None:
                raise SystemExit(f"absolute expression did not synthesize: {learned}")
            inputs, outputs = held_out[phrase]
            if model.predict(phrase, inputs).output != outputs:
                raise SystemExit(f"absolute-expression holdout failed for {phrase}")

        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        if restored.accepted_primitive_candidates() != [DESCRIPTOR]:
            raise SystemExit("absolute expression did not survive persistence")
        try:
            restored.revoke_primitive_candidate(DESCRIPTOR)
        except ValueError as error:
            if not any(phrase in str(error) for phrase in PHRASES):
                raise
        else:
            raise SystemExit("absolute expression was revoked while in use")

    print("absolute-expression discovery and learning: PASS")
    print("canonical proposal, holdout rejection, acceptance, synthesis, "
          "persistence, and revocation guard: PASS")


if __name__ == "__main__":
    main()
