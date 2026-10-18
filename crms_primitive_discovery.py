"""Bounded, report-only primitive proposals from CRMS no-fit records.

The proposal grammar models output lists as binary operations over a local
two- or three-value window, with a bounded stride. Candidate-specific clusters
allow unrelated no-fit records to coexist without suppressing a proposal.
"""
from __future__ import annotations

import json
from typing import Any, Callable


_BINARY_OPERATORS: dict[str, Callable[[int, int], int]] = {
    "add": lambda left, right: left + right,
    "subtract": lambda left, right: left - right,
    "multiply": lambda left, right: left * right,
    "maximum": max,
    "minimum": min,
    # Python's integer remainder semantics, including negative operands.
    "modulo": lambda left, right: left % right,
}


def propose_window_binary_primitives(
        no_fit_records: list[dict[str, Any]], *,
        minimum_supporting_phrases: int = 2,
        integer_code: str = "gamma",
        ) -> list[dict[str, Any]]:
    """Propose schemas from per-phrase splits captured in no-fit records.

    Training examples alone determine the candidate cluster and description
    length. All held-out examples for that training-supported cluster must then
    validate the candidate. Each proposal needs support from multiple distinct
    phrases and a shorter training-data code under the explicit prefix code
    below. Nothing is added to a model.
    """
    if not isinstance(integer_code, str) or integer_code not in {"gamma", "delta"}:
        raise ValueError("integer_code must be 'gamma' or 'delta'")
    if (type(minimum_supporting_phrases) is not int
            or minimum_supporting_phrases < 2):
        raise ValueError("minimum_supporting_phrases must be at least two")

    records = []
    for record in no_fit_records:
        parsed_record = _parse_record(record)
        if parsed_record is not None:
            records.append(parsed_record)

    proposals = []
    for window_width in (2, 3):
        offset_pairs = [(left, right)
                        for left in range(window_width)
                        for right in range(window_width)]
        for name, operation in _BINARY_OPERATORS.items():
            for left_offset, right_offset in offset_pairs:
                if (name in {"add", "multiply", "maximum", "minimum"}
                        and left_offset > right_offset):
                    continue
                for stride in range(1, window_width + 1):
                    def apply(inputs: list[int]) -> list[int]:
                        last_start = len(inputs) - window_width
                        return [operation(inputs[index + left_offset],
                                          inputs[index + right_offset])
                                for index in range(0, last_start + 1, stride)]

                    def matches(rows: list[tuple[list[int], list[int]]]) -> bool:
                        try:
                            return all(output == apply(inputs)
                                       for inputs, output in rows)
                        except (ArithmeticError, OverflowError):
                            # A zero divisor or another undefined candidate
                            # evaluation cannot support this proposal.
                            return False

                    training_cluster = []
                    validation_failed = False
                    for record in records:
                        examples = record["examples"]
                        split = record["proposal_split"]
                        training = [examples[index]
                                    for index in split["training_indices"]]
                        held_out = [examples[index]
                                    for index in split["held_out_indices"]]
                        if (len(training) < 2 or not held_out
                                or not matches(training)):
                            continue
                        training_cluster.append(record)
                        if not matches(held_out):
                            validation_failed = True

                    phrases = sorted({record["instruction"]
                                      for record in training_cluster})
                    if (len(phrases) < minimum_supporting_phrases
                            or validation_failed):
                        continue
                    descriptor = {
                        "operation": "map_window_binary",
                        "operator": name,
                        "window_width": window_width,
                        "left_offset": left_offset,
                        "right_offset": right_offset,
                        "stride": stride,
                    }
                    training_payload = [
                        {"instruction": record["instruction"],
                         "examples": [record["examples"][index]
                                      for index in record["proposal_split"]["training_indices"]]}
                        for record in training_cluster
                    ]
                    input_payload = [
                        {"instruction": record["instruction"],
                         "inputs": [record["examples"][index][0]
                                    for index in record["proposal_split"]["training_indices"]]}
                        for record in training_cluster
                    ]
                    literal_bits = _literal_training_bits(
                        training_payload, integer_code)
                    schema_bits = _schema_description_bits(
                        name, window_width, left_offset, right_offset, stride)
                    candidate_bits = schema_bits + _candidate_training_bits(
                        input_payload, integer_code)
                    if candidate_bits >= literal_bits:
                        continue
                    literal_size = len(json.dumps(
                        training_payload, separators=(",", ":")))
                    compressed_payload = {"primitive": descriptor,
                                          "cases": input_payload}
                    compressed_size = len(json.dumps(
                        compressed_payload, separators=(",", ":")))
                    proposals.append({
                        "descriptor": descriptor,
                        "supporting_instructions": phrases,
                        "excluded_instructions": sorted({
                            record["instruction"] for record in records
                            if record["instruction"] not in phrases
                        }),
                        "training_examples": sum(
                            len(record["proposal_split"]["training_indices"])
                            for record in training_cluster),
                        "held_out_examples": sum(
                            len(record["proposal_split"]["held_out_indices"])
                            for record in training_cluster),
                        "held_out_valid": True,
                        "integer_code": integer_code,
                        "description_length_bits_baseline": literal_bits,
                        "description_length_bits_candidate": candidate_bits,
                        "description_length_gain_bits": literal_bits - candidate_bits,
                        "mdl_gate_passed": True,
                        "literal_example_bytes": literal_size,
                        "schema_plus_inputs_bytes": compressed_size,
                    })
    return proposals


def _gamma_bits(value: int) -> int:
    """Elias gamma code length for a positive integer."""
    if type(value) is not int or value < 1:
        raise ValueError("gamma code accepts positive integers only")
    return 2 * value.bit_length() - 1


def _delta_bits(value: int) -> int:
    """Elias delta code length for a positive integer."""
    if type(value) is not int or value < 1:
        raise ValueError("delta code accepts positive integers only")
    width = value.bit_length()
    return _gamma_bits(width) + width - 1


def _positive_bits(value: int, code: str) -> int:
    return _gamma_bits(value) if code == "gamma" else _delta_bits(value)


def _signed_integer_bits(value: int, code: str = "gamma") -> int:
    """Universal-code length after signed-to-positive zigzag mapping."""
    zigzag = 2 * value if value >= 0 else -2 * value - 1
    return _positive_bits(zigzag + 1, code)


def _integer_list_bits(values: list[int], code: str) -> int:
    return _positive_bits(len(values) + 1, code) + sum(
        _signed_integer_bits(value, code) for value in values)


def _phrase_bits(phrase: str, code: str) -> int:
    encoded = phrase.encode("utf-8")
    return _positive_bits(len(encoded) + 1, code) + 8 * len(encoded)


def _literal_training_bits(records: list[dict[str, Any]], code: str) -> int:
    """Encode phrase labels and literal training input/output pairs."""
    total = _positive_bits(len(records) + 1, code)
    for record in records:
        examples = record["examples"]
        total += _phrase_bits(record["instruction"], code)
        total += _positive_bits(len(examples) + 1, code)
        for inputs, outputs in examples:
            total += (_integer_list_bits(inputs, code)
                      + _integer_list_bits(outputs, code))
    return total


def _schema_description_bits(operator: str, window_width: int,
                             left_offset: int, right_offset: int,
                             stride: int) -> int:
    """Fixed-width code for the declared bounded window grammar.

    Two bits identify the window-map family; three select one of six
    operators; one selects width 2/3; two bits encode each offset in 0..2;
    two bits encode stride in 1..3.
    """
    operator_names = tuple(_BINARY_OPERATORS)
    if (operator not in operator_names or window_width not in (2, 3)
            or not 0 <= left_offset < window_width
            or not 0 <= right_offset < window_width
            or not 1 <= stride <= window_width):
        raise ValueError("schema is outside the declared primitive code")
    return 2 + 3 + 1 + 2 + 2 + 2


def _candidate_training_bits(records: list[dict[str, Any]], code: str) -> int:
    """Encode phrase-to-schema associations and inputs; outputs are derived."""
    total = _positive_bits(len(records) + 1, code)
    for record in records:
        total += _phrase_bits(record["instruction"], code)
        total += 1  # phrase is associated with the shared candidate schema
        inputs = record["inputs"]
        total += _positive_bits(len(inputs) + 1, code)
        total += sum(_integer_list_bits(values, code) for values in inputs)
    return total


def _parse_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    phrase = record.get("instruction")
    examples = record.get("examples")
    split = record.get("proposal_split")
    if (not isinstance(phrase, str) or not phrase
            or not isinstance(examples, list)
            or not isinstance(split, dict)
            or set(split) != {"training_indices", "held_out_indices"}
            or not isinstance(split["training_indices"], list)
            or not isinstance(split["held_out_indices"], list)
            or len(split["training_indices"]) < 2
            or not split["held_out_indices"]
            or any(type(index) is not int
                   for index in (*split["training_indices"],
                                 *split["held_out_indices"]))):
        return None
    parsed = []
    for example in examples:
        if (not isinstance(example, (list, tuple)) or len(example) != 2
                or not isinstance(example[0], (list, tuple))
                or not isinstance(example[1], (list, tuple))
                or any(type(value) is not int
                       for value in (*example[0], *example[1]))):
            return None
        parsed.append((list(example[0]), list(example[1])))
    indices = [*split["training_indices"], *split["held_out_indices"]]
    if (sorted(indices) != list(range(len(parsed)))
            or len(indices) != len(set(indices))):
        return None
    return {
        "instruction": phrase,
        "examples": parsed,
        "proposal_split": split,
    }
