"""Sweep the bounded local-expression grammar with positive and holdout negatives."""
from __future__ import annotations

import copy
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_expression_discovery import propose_window_expression_primitives
from crms_model import CRMSModel


SPECS = [
    (2, "(+ (* x x) y)", lambda w: w[0] * w[0] + w[1], [
        "square the first value and add the second",
        "add the second number to the first squared",
        "for each pair, take the first times itself plus the next",
    ]),
    (2, "(- (* x y) x)", lambda w: w[0] * w[1] - w[0], [
        "multiply the pair then subtract the first",
        "take the first times the second less the first value",
        "for each pair, subtract the left value from their product",
    ]),
    (3, "(+ (* x y) z)", lambda w: w[0] * w[1] + w[2], [
        "multiply the first two values and add the third",
        "add the last value to the first two multiplied",
        "for each triple, multiply first by second then add third",
    ]),
    (3, "(* (+ x y) z)", lambda w: (w[0] + w[1]) * w[2], [
        "add the first two values then multiply by the third",
        "multiply the last value by the sum of the first two",
        "for each triple, sum first and second then scale by third",
    ]),
    (3, "(- (* x x) z)", lambda w: w[0] * w[0] - w[2], [
        "square the first value then subtract the third",
        "subtract the last value from the first squared",
        "for each triple, take first times itself less third",
    ]),
]


def make_examples(width: int, variant: int, formula):
    examples = []
    for row in range(6):
        inputs = [((variant + 1) * 13 + (row + 2) * 7
                   + index * index * 3 + index * 11) % 47 - 23
                  for index in range(width + 4 + row % 2)]
        outputs = [formula(inputs[index:index + width])
                   for index in range(len(inputs) - width + 1)]
        examples.append((inputs, outputs))
    return examples


def main() -> None:
    total_clusters = 0
    with tempfile.TemporaryDirectory() as directory:
        for case_index, (width, expression, formula, phrases) in enumerate(SPECS):
            memory = Path(directory) / f"grammar-{case_index}.json"
            model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
            held_out = {}
            for variant, phrase in enumerate(phrases):
                examples = make_examples(width, variant, formula)
                result = model.teach(phrase, examples)
                if result.status != "no_fit":
                    raise SystemExit(f"target unexpectedly fit the old grammar: {phrase}")
                held_out[phrase] = examples[-1]
            total_clusters += len(phrases)

            candidates = [item for item in model.propose_primitive_candidates()
                          if item["descriptor"].get("operation")
                          == "map_window_expression"]
            if (len(candidates) != 1
                    or candidates[0]["descriptor"].get("expression") != expression
                    or candidates[0]["descriptor"].get("window_width", 2) != width
                    or not candidates[0]["held_out_valid"]
                    or not candidates[0]["mdl_gate_passed"]):
                raise SystemExit(
                    f"grammar case {expression} was not recovered uniquely: "
                    f"{[item['descriptor'] for item in candidates]}")

            corrupted = copy.deepcopy(model.no_fit_cases())
            for record in corrupted:
                index = record["proposal_split"]["held_out_indices"][0]
                record["examples"][index][1][0] += 1
            if propose_window_expression_primitives(
                    corrupted, minimum_supporting_phrases=len(phrases)):
                raise SystemExit(f"corrupted holdouts passed for {expression}")

            descriptor = candidates[0]["descriptor"]
            model.accept_primitive_candidate(descriptor)
            for phrase in phrases:
                learned = model.retry(phrase)
                if learned.status != "learned":
                    raise SystemExit(f"accepted expression did not learn {phrase}")
                inputs, outputs = held_out[phrase]
                if model.predict(phrase, inputs).output != outputs:
                    raise SystemExit(f"held-out behavior failed for {phrase}")
            restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
            if restored.accepted_primitive_candidates() != [descriptor]:
                raise SystemExit(f"accepted expression did not persist: {expression}")

    print(f"expression grammar coverage: PASS; {len(SPECS)} formulas, "
          f"{total_clusters} phrase clusters, two window widths")
    print("held-out corruption rejection, explicit acceptance, procedure "
          "synthesis, and persistence: PASS")


if __name__ == "__main__":
    main()
