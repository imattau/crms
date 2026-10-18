"""Audit failed examples and propose held-out-checked window primitives.

This diagnostic clusters persisted no-fit records, anti-unifies output length
and adjacent input-value relations, and compares a compact schema against the
literal example encoding. Proposals remain advisory and do not enter the rule
library.
"""
from __future__ import annotations

import copy
import json
from random import Random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crms_model import CRMSModel, _proposal_split_indices
from crms_primitive_discovery import (
    _delta_bits, _gamma_bits, _signed_integer_bits,
    propose_window_binary_primitives,
)


def pair_sums(xs: list[int]) -> list[int]:
    return [left + right for left, right in zip(xs, xs[1:])]


NOVEL_TASK_INPUTS = {
    "add neighboring values": [
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        [-2, 4, 6, -1, 8, 3, -5, 7, 0, 9, -4],
        [3, -1, 2, 8, -6, 5, 4, -3, 7, 1],
    ],
    "sum adjacent numbers": [
        [5, 7, -2, 1, 9, -4, 3, 6, 0, -1, 8],
        [-3, 6, 2, 4, -8, 5, 1, 7, -2, 9, 0, 3],
        [0, -4, 5, 2, -7, 8, 1, 6, -3, 10],
    ],
    "combine consecutive entries": [
        [4, -1, 8, 0, 3, -5, 6, 2, -7, 9, 1],
        [-6, 2, 5, -3, 7, 0, 4, -8, 10, 1],
        [9, 3, -4, 6, 2, -1, 5, 8, -2, 0, 7, -5],
    ],
}
def append_reverse(xs: list[int]) -> list[int]:
    return list(xs) + list(reversed(xs))


def nonoverlapping_pair_sums(xs: list[int]) -> list[int]:
    return [xs[index] + xs[index + 1]
            for index in range(0, len(xs) - 1, 2)]


NOVEL_TASKS = {
    phrase: [(xs, pair_sums(xs)) for xs in inputs]
    for phrase, inputs in NOVEL_TASK_INPUTS.items()
}
NOVEL_TASKS["append reversed values"] = [
    (xs, append_reverse(xs)) for xs in (
        [2, 5, -1, 8, 3, -4],
        [-7, 0, 6, 2, 9, -3, 1],
        [4, -2, 11, 3, 0, 7, -5, 8],
    )
]


def main() -> None:
    if ([_gamma_bits(value) for value in range(1, 5)] != [1, 3, 3, 5]
            or [_delta_bits(value) for value in range(1, 5)] != [1, 4, 4, 5]
            or [_signed_integer_bits(value) for value in (-1, 0, 1)]
            != [3, 1, 3]):
        raise SystemExit("description-length prefix code has unexpected lengths")

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "model.json"
        model = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        for phrase, examples in NOVEL_TASKS.items():
            result = model.teach(phrase, examples)
            if result.status != "no_fit":
                raise SystemExit(f"novel fixture did not produce no_fit: {phrase}: {result.status}")
        records = model.no_fit_cases()
        if len(records) != 4 or any(record["instruction"] in model.list_rules()
                                    for record in records):
            raise SystemExit("no-fit archive lost records or promoted a rule")
        if any(record["proposal_split"] != _proposal_split_indices(
                record["examples"]) for record in records):
            raise SystemExit("no-fit records did not preserve content-stable splits")
        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        records = restored.no_fit_cases()
        if len(records) != 4 or records != model.no_fit_cases():
            raise SystemExit("no-fit archive did not survive persistence")
        wider_grammar = CRMSModel(
            memory, max_composition_depth=1, max_workers=1, max_scale=6)
        if (len(wider_grammar.no_fit_cases()) != 4
                or wider_grammar.propose_primitive_candidates()):
            raise SystemExit("stale failures seeded discovery under a wider grammar")
        legacy_memory = Path(directory) / "legacy-model.json"
        legacy_payload = json.loads(memory.read_text(encoding="utf-8"))
        for record in legacy_payload["no_fit_cases"]:
            record.pop("proposal_split")
            record.pop("candidate_space_signature")
        legacy_memory.write_text(json.dumps(legacy_payload), encoding="utf-8")
        legacy = CRMSModel(legacy_memory, max_composition_depth=1, max_workers=1)
        if (len(legacy.no_fit_cases()) != 4
                or any(record["proposal_split"] != _proposal_split_indices(
                    record["examples"]) for record in legacy.no_fit_cases())
                or legacy.propose_primitive_candidates()):
            raise SystemExit("legacy no-fit records migrated unsafely into proposals")

        proposals = restored.propose_primitive_candidates()
        if len(proposals) != 1 or proposals[0]["descriptor"]["operator"] != "add":
            raise SystemExit(f"anti-unification missed adjacent addition: {proposals}")
        proposal = proposals[0]
        cost = proposal.get("search_cost_estimate", {})
        choices = len(restored._steps)
        expected_before = sum(
            choices ** depth
            for depth in range(1, restored.max_composition_depth + 1))
        expected_after = sum(
            (choices + 1) ** depth
            for depth in range(1, restored.max_composition_depth + 1))
        if (cost.get("step_choices_before") != choices
                or cost.get("step_choices_after_acceptance") != choices + 1
                or cost.get("raw_procedure_sequences_before") != expected_before
                or cost.get("raw_procedure_sequences_after") != expected_after
                or cost.get("raw_sequence_growth_upper_bound")
                != expected_after - expected_before
                or cost.get("runtime_prediction") is not False):
            raise SystemExit(f"proposal omitted its bounded search-cost estimate: {cost}")
        if (proposal["kind"] != "primitive_proposal"
                or not proposal["artifact_id"].startswith(
                    "primitive-proposal-v1-")
                or len(proposal["lineage"]) != 3
                or restored.retrieve_primitive_proposal(
                    proposal["artifact_id"]) != proposal):
            raise SystemExit("primitive proposal artifact/lineage was not retrievable")
        order_probe = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase, examples in NOVEL_TASKS.items():
            if order_probe.teach(phrase, list(reversed(examples))).status != "no_fit":
                raise SystemExit("reordered no-fit fixture unexpectedly fit")
        reversed_proposals = order_probe.propose_primitive_candidates()
        if (len(reversed_proposals) != 1
                or reversed_proposals[0]["artifact_id"] != proposal["artifact_id"]):
            raise SystemExit("primitive artifact identity changed with example order")
        stale_probe = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        stale_probe.forget("sum adjacent numbers")
        if stale_probe.retrieve_primitive_proposal(proposal["artifact_id"]) is not None:
            raise SystemExit("primitive artifact resolved after lineage changed")
        try:
            stale_probe.accept_primitive_proposal(proposal["artifact_id"])
        except ValueError as error:
            if "stale" not in str(error):
                raise
        else:
            raise SystemExit("stale primitive proposal artifact was accepted")
        changed_probe = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        new_input = [4, 8, -2, 1, 9, 0]
        changed_result = changed_probe.teach(
            "sum adjacent numbers", [(new_input, pair_sums(new_input))])
        changed_proposals = changed_probe.propose_primitive_candidates()
        if (changed_result.status != "no_fit" or len(changed_proposals) != 1
                or changed_proposals[0]["artifact_id"] == proposal["artifact_id"]
                or changed_probe.retrieve_primitive_proposal(
                    proposal["artifact_id"]) is not None):
            raise SystemExit(
                "primitive artifact did not invalidate when source examples changed")
        permuted_records = copy.deepcopy(records)
        for record in permuted_records:
            record["examples"].reverse()
            record["proposal_split"] = _proposal_split_indices(
                record["examples"])
        permuted_proposals = propose_window_binary_primitives(permuted_records)
        baseline_raw_proposals = propose_window_binary_primitives(records)
        if permuted_proposals != baseline_raw_proposals:
            raise SystemExit(
                "reordering demonstrations changed the primitive proposal")
        descriptor = proposal["descriptor"]
        if (descriptor["operation"] != "map_window_binary"
                or descriptor["window_width"] != 2
                or descriptor["left_offset"] != 0
                or descriptor["right_offset"] != 1
                or descriptor["stride"] != 1):
            raise SystemExit(f"adjacent-sum schema was wrong: {descriptor}")
        if (not proposal["held_out_valid"] or not proposal["mdl_gate_passed"]
                or proposal["description_length_gain_bits"] <= 0
                or proposal["training_examples"] != 6
                or proposal["held_out_examples"] != 3
                or proposal["excluded_instructions"] != ["append reversed values"]):
            raise SystemExit(f"primitive proposal failed held-out/MDL gates: {proposal}")

        delta_proposals = propose_window_binary_primitives(
            records, integer_code="delta")
        if (len(delta_proposals) != 1
                or delta_proposals[0]["descriptor"] != descriptor
                or not delta_proposals[0]["mdl_gate_passed"]
                or delta_proposals[0]["description_length_gain_bits"] <= 0):
            raise SystemExit(f"primitive proposal was code-sensitive: {delta_proposals}")
        try:
            propose_window_binary_primitives(records, integer_code="unknown")
        except ValueError:
            pass
        else:
            raise SystemExit("unknown description-length code was accepted")

        corrupted_holdout = copy.deepcopy(records)
        held_out_index = corrupted_holdout[0]["proposal_split"][
            "held_out_indices"][0]
        corrupted_holdout[0]["examples"][held_out_index][1][0] += 1
        filtered_proposals = propose_window_binary_primitives(corrupted_holdout)
        if filtered_proposals:
            raise SystemExit("candidate passed a corrupted held-out cluster")

        # Changing a valid held-out example must not change the training MDL
        # score: holdout is a validation gate, not part of model fitting.
        changed_holdout = copy.deepcopy(records)
        new_input = [13, -8, 6, 4, -2, 17]
        held_out_index = changed_holdout[0]["proposal_split"][
            "held_out_indices"][0]
        changed_holdout[0]["examples"][held_out_index] = (
            new_input, pair_sums(new_input))
        changed_proposals = propose_window_binary_primitives(changed_holdout)
        if (len(changed_proposals) != 1
                or changed_proposals[0]["description_length_bits_baseline"]
                != proposal["description_length_bits_baseline"]
                or changed_proposals[0]["description_length_bits_candidate"]
                != proposal["description_length_bits_candidate"]):
            raise SystemExit("held-out data leaked into the description-length score")

        # A second independent transformation has a shorter, strided output:
        # each disjoint adjacent pair contributes one sum.
        rng = Random(1742)
        strided_inputs = [
            [rng.randint(-20, 20) for _ in range(rng.randint(8, 16))]
            for _ in range(12)
        ]
        strided_examples = [(xs, nonoverlapping_pair_sums(xs))
                            for xs in strided_inputs]
        strided_records = [
            {"instruction": phrase,
             "examples": copy.deepcopy(strided_examples),
             "proposal_split": {"training_indices": list(range(11)),
                                "held_out_indices": [11]}}
            for phrase in ("sum pairs without overlap", "add disjoint neighbors",
                           "combine successive pairs")
        ]
        strided_proposals = propose_window_binary_primitives(strided_records)
        strided_matches = [candidate for candidate in strided_proposals
                           if candidate["descriptor"]["stride"] == 2
                           and candidate["descriptor"]["operator"] == "add"
                           and candidate["descriptor"]["left_offset"] == 0
                           and candidate["descriptor"]["right_offset"] == 1]
        if (len(strided_proposals) != 1 or len(strided_matches) != 1
                or strided_matches[0]["descriptor"]["window_width"] != 2
                or not strided_matches[0]["held_out_valid"]):
            raise SystemExit(f"strided pair-sum schema was not discovered: {strided_proposals}")

        # Exercise a different binary operator on overlapping windows. This
        # helps detect a proposal search that only memorizes the addition case.
        product_rng = Random(1743)
        product_inputs = [
            [product_rng.randint(-9, 9) for _ in range(product_rng.randint(8, 15))]
            for _ in range(12)
        ]
        product_examples = [
            (xs, [left * right for left, right in zip(xs, xs[1:])])
            for xs in product_inputs
        ]
        product_records = [
            {"instruction": phrase,
             "examples": copy.deepcopy(product_examples),
             "proposal_split": {"training_indices": list(range(11)),
                                "held_out_indices": [11]}}
            for phrase in ("multiply neighboring values", "product of adjacent entries",
                           "multiply consecutive numbers")
        ]
        product_proposals = propose_window_binary_primitives(product_records)
        product_matches = [candidate for candidate in product_proposals
                           if candidate["descriptor"]["operator"] == "multiply"
                           and candidate["descriptor"]["window_width"] == 2
                           and candidate["descriptor"]["left_offset"] == 0
                           and candidate["descriptor"]["right_offset"] == 1
                           and candidate["descriptor"]["stride"] == 1]
        if (len(product_proposals) != 1 or len(product_matches) != 1
                or not product_matches[0]["held_out_valid"]):
            raise SystemExit(f"neighbor-product schema was not discovered: {product_proposals}")

        # A proposal is evidence for a candidate primitive, not an installed
        # operation or a learned procedure. The production library stays fixed.
        if (descriptor["operation"] in {step.operation for step in restored._steps}
                or len(restored.list_rules())):
            raise SystemExit("report-only proposal changed the active rule library")
        literal_size = proposal["literal_example_bytes"]
        compressed_size = proposal["schema_plus_inputs_bytes"]

        # Replacing a failed phrase with examples that fit a current rule clears
        # its stale no-fit status; forgetting removes its archived record too.
        corrected = restored.teach(
            "add neighboring values",
            [([1, 2, 3], [3, 2, 1]), ([4, 1, 2], [2, 1, 4])],
            replace=True)
        if corrected.status != "learned" or len(restored.no_fit_cases()) != 3:
            raise SystemExit("corrected teaching did not clear the old failure record")
        restored.forget("sum adjacent numbers")
        if len(restored.no_fit_cases()) != 2:
            raise SystemExit("forget did not remove its no-fit record")

        retained_examples = restored.no_fit_cases()[0]["examples"]
        for index in range(CRMSModel.NO_FIT_RECORD_LIMIT + 1):
            restored._remember_no_fit(f"bounded failure {index}",
                                      [(list(retained_examples[0][0]),
                                        list(retained_examples[0][1]))])
        retained = restored.no_fit_cases()
        if (len(retained) != CRMSModel.NO_FIT_RECORD_LIMIT
                or retained[0]["instruction"] != "bounded failure 1"):
            raise SystemExit("no-fit archive cap/oldest-first eviction failed")

    print("no-fit primitive discovery diagnostic: PASS")
    print(f"records={len(records)} candidate={descriptor} held_out=PASS "
          f"serialized_bytes={literal_size}->{compressed_size}")
    print(f"training description length: "
          f"{proposal['description_length_bits_baseline']}->"
          f"{proposal['description_length_bits_candidate']} bits "
          f"(gain={proposal['description_length_gain_bits']})")
    print(f"Elias-delta sensitivity: same candidate, "
          f"gain={delta_proposals[0]['description_length_gain_bits']} bits")
    print("strided sums and overlapping products, persistence, no rule promotion, "
          "replacement, forgetting: PASS")


if __name__ == "__main__":
    main()
