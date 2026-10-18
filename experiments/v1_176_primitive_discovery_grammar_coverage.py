"""Measure held-out recovery over a seeded slice of the proposal grammar.

Run from the project root with:
    python3 experiments/v1_176_primitive_discovery_grammar_coverage.py

This evaluates the report-only proposer on synthetic data sampled from its
declared binary-window grammar. It is grammar coverage, not natural-language
or independent-corpus validation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from random import Random

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_primitive_discovery import propose_window_binary_primitives


TARGETS = (
    ("add", 2, 0, 1, 1),
    ("add", 2, 0, 1, 2),
    ("add", 3, 0, 2, 1),
    ("add", 3, 0, 2, 2),
    ("subtract", 2, 0, 1, 1),
    ("subtract", 2, 1, 0, 1),
    ("subtract", 3, 2, 0, 2),
    ("multiply", 2, 0, 1, 1),
    ("multiply", 3, 0, 2, 2),
    ("maximum", 2, 0, 1, 1),
    ("maximum", 3, 0, 2, 1),
    ("minimum", 2, 0, 1, 2),
    ("minimum", 3, 1, 2, 2),
)

PHRASE_CLUSTERS = (
    ("add each pair of adjacent values", "sum neighboring numbers",
     "total every consecutive pair"),
    ("sum non-overlapping pairs of values", "add values in successive pairs",
     "total every other adjacent pair"),
    ("sum values two positions apart", "add each value to the one two places later",
     "total entries separated by one item"),
    ("sum every other pair two places apart", "add values two positions apart, stepping by two",
     "total first and third values in each overlapping triple"),
    ("subtract each next value from its predecessor", "take the following number away from each value",
     "find the drop from one adjacent number to the next"),
    ("subtract each value from the next one", "find the increase between neighboring values",
     "calculate next minus previous for each pair"),
    ("subtract the first value in each triple from the third, stepping by two",
     "compare values two places apart and take earlier from later",
     "find every other two-position increase"),
    ("multiply every pair of adjacent values", "find products of neighboring numbers",
     "multiply each value by the next one"),
    ("multiply values two places apart, moving two places each time",
     "take the product of the first and third values in each triple",
     "multiply every other pair separated by one item"),
    ("keep the larger value from each neighboring pair", "choose the maximum of adjacent numbers",
     "select the greater value in every consecutive pair"),
    ("keep the larger value two places apart", "choose the greater of the first and third values in each triple",
     "take every other maximum across a two-position gap"),
    ("keep the smaller value in each non-overlapping pair", "find minima of successive pairs",
     "choose the lesser value, then move to the next pair"),
    ("find the smaller of the last two values in each triple, stepping by two",
     "choose the lower value in each overlapping pair of later entries",
     "take every other minimum between neighboring values"),
)

OPERATORS = {
    "add": lambda left, right: left + right,
    "subtract": lambda left, right: left - right,
    "multiply": lambda left, right: left * right,
    "maximum": max,
    "minimum": min,
}


def apply_target(spec: tuple[str, int, int, int, int],
                 values: list[int]) -> list[int]:
    operator, width, left_offset, right_offset, stride = spec
    last_start = len(values) - width
    return [OPERATORS[operator](values[index + left_offset],
                                values[index + right_offset])
            for index in range(0, last_start + 1, stride)]


def make_records() -> list[dict]:
    rng = Random(176)
    records = []
    for target, phrases in zip(TARGETS, PHRASE_CLUSTERS, strict=True):
        for phrase in phrases:
            examples = []
            for _ in range(12):
                values = [rng.randint(-30, 30)
                          for _ in range(rng.randint(8, 16))]
                examples.append((values, apply_target(target, values)))
            records.append({
                "instruction": phrase,
                "examples": examples,
                "proposal_split": {
                    "training_indices": list(range(10)),
                    "held_out_indices": [10, 11],
                },
            })
    return records


def make_out_of_grammar_records() -> list[dict]:
    rng = Random(1760)
    records = []
    unsupported_phrases = (
        "append the reversed list to the end",
        "copy the sequence backwards after its original values",
        "concatenate the input with its reverse",
    )
    for phrase in unsupported_phrases:
        examples = []
        for _ in range(12):
            values = [rng.randint(-30, 30)
                      for _ in range(rng.randint(8, 16))]
            examples.append((values, values + list(reversed(values))))
        records.append({
            "instruction": phrase,
            "examples": examples,
            "proposal_split": {
                "training_indices": list(range(10)),
                "held_out_indices": [10, 11],
            },
        })
    return records


def main() -> None:
    records = make_records()
    expected = {
        ("map_window_binary", operator, width, left, right, stride)
        for operator, width, left, right, stride in TARGETS
    }
    all_code_results = {}
    for code in ("gamma", "delta"):
        proposals = propose_window_binary_primitives(
            records, integer_code=code)
        found = {
            (proposal["descriptor"]["operation"],
             proposal["descriptor"]["operator"],
             proposal["descriptor"]["window_width"],
             proposal["descriptor"]["left_offset"],
             proposal["descriptor"]["right_offset"],
             proposal["descriptor"]["stride"])
            for proposal in proposals
        }
        if found != expected:
            missing, extra = sorted(expected - found), sorted(found - expected)
            raise SystemExit(f"{code} grammar recovery mismatch; "
                             f"missing={missing}, extra={extra}")
        if any(not proposal["held_out_valid"]
               or not proposal["mdl_gate_passed"]
               or proposal["description_length_gain_bits"] <= 0
               for proposal in proposals):
            raise SystemExit(f"{code} emitted an invalid/ungated proposal")
        all_code_results[code] = found
        gains = [proposal["description_length_gain_bits"]
                 for proposal in proposals]
        print(f"{code}: recovered {len(found)}/{len(expected)} schemas; "
              f"MDL gain range={min(gains)}..{max(gains)} bits")

    if all_code_results["gamma"] != all_code_results["delta"]:
        raise SystemExit("schema recovery changed with the universal code")
    unsupported_records = make_out_of_grammar_records()
    for code in ("gamma", "delta"):
        unsupported = propose_window_binary_primitives(
            unsupported_records, integer_code=code)
        if unsupported:
            raise SystemExit(f"{code} proposed an out-of-grammar pattern: {unsupported}")
    print(f"grammar coverage: PASS; {len(records)} phrase clusters, "
          f"{sum(len(record['examples']) for record in records)} examples, "
          f"{len(TARGETS)} target schemas")
    print("out-of-grammar negative control: PASS; no proposals for 3 phrase clusters")


if __name__ == "__main__":
    main()
