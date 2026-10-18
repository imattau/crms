"""Check example discovery of order-preserving duplicate removal.

Run from the project root with:
    python3 experiments/v1_97_stable_unique_learning.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    examples = [
        ([3, 1, 3, 2, 1], [3, 1, 2]),
        ([5, 5, 2, 5, 4, 2], [5, 2, 4]),
        ([0, -1, 0, -1, 7], [0, -1, 7]),
    ]
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    learned = model.teach("remove repeated values", examples)
    expected = [{"operation": "stable_unique", "parameters": {}}]
    if learned.status != "learned" or learned.procedure != expected:
        raise SystemExit(f"examples did not identify stable_unique: {learned}")
    prediction = model.predict("remove repeated values", [4, 2, 4, 1, 2, 4])
    if prediction.status != "ok" or prediction.output != [4, 2, 1]:
        raise SystemExit(f"held-out duplicate removal failed: {prediction}")

    # Unique-only demonstrations do not distinguish this rule from identity.
    ambiguous = CRMSModel(max_composition_depth=1, max_workers=1).teach(
        "remove repeated values", [([1, 2, 3], [1, 2, 3]),
                                   ([4, 5], [4, 5])])
    if ambiguous.status != "need_more_examples":
        raise SystemExit(f"identity ambiguity was not retained: {ambiguous}")

    first = (Step("first", {}),)
    equivalent = (
        ((Step("stable_unique", {}), Step("reverse", {}), Step("last", {})), first),
        ((Step("stable_unique", {}), Step("first", {})), first),
        ((Step("stable_unique", {}), Step("scale_k", {"k": -3}),
          Step("first", {})),
         (Step("scale_k", {"k": -3}), Step("first", {}))),
        ((Step("stable_unique", {}), Step("rotate_left_k", {"k": 1}),
          Step("last", {})), first),
        ((Step("stable_unique", {}), Step("repeat_each_k", {"k": 3}),
          Step("first", {})), first),
        ((Step("first", {}), Step("scale_k", {"k": 3}),
          Step("stable_unique", {})),
         (Step("first", {}), Step("scale_k", {"k": 3}))),
        ((Step("first", {}), Step("repeat_each_k", {"k": 3}),
          Step("stable_unique", {})), first),
    )
    probes = ([1, 2, 1, 3, 2], [4, 4, 5], [7], [])
    for program, expected_program in equivalent:
        expected_key = _semantic_key(expected_program)
        if _semantic_key(program) != expected_key:
            raise SystemExit(f"proven endpoint equivalence was not canonicalized: {program}")
        if any(_apply_procedure(program, values)
               != _apply_procedure(expected_program, values)
               for values in probes):
            raise SystemExit(f"endpoint rewrite changed behavior: {program}")

    # Uniformly repeating each value immediately before stable deduplication
    # has no effect; deduplication is also idempotent.
    unique = (Step("stable_unique", {}),)
    repeat_unique_aliases = [
        (Step("duplicate_each", {}), Step("stable_unique", {})),
        *((Step("repeat_each_k", {"k": copies}),
           Step("stable_unique", {})) for copies in (2, 3, 4)),
        (Step("stable_unique", {}), Step("stable_unique", {})),
        (Step("repeat_each_k", {"k": 3}), Step("stable_unique", {}),
         Step("stable_unique", {})),
    ]
    for program in repeat_unique_aliases:
        if _semantic_key(program) != _semantic_key(unique):
            raise SystemExit(
                f"repeat/idempotent deduplication alias was not canonicalized: {program}")
        if any(_apply_procedure(program, values)
               != _apply_procedure(unique, values) for values in probes):
            raise SystemExit(
                f"repeat/deduplication normalization changed behavior: {program}")

    # The generated add-then-deduplicate rule should resolve after its
    # contrastive example removes the drop-last alternatives.
    composition = CRMSModel(max_composition_depth=3, max_workers=1)
    examples_for_composition = [
        ([4, 3, 5, 10, 8, -1, 4], [12, 11, 13, 18, 16, 7]),
        ([-7, -9, 0], [1, -1, 8]),
    ]
    for inputs, outputs in examples_for_composition:
        composition_result = composition.teach(
            "add eight and remove repeats", [(inputs, outputs)])
    if (composition_result.status != "learned"
            or composition.predict("add eight and remove repeats",
                                   [2, 3, 2, -8]).output != [10, 11, 0]):
        raise SystemExit(
            "add-then-stable-deduplicate did not resolve after its probe")

    # Reversing before deduplication changes which distinct value is last.
    # This must not be merged with selecting the original first value.
    reversed_unique_last = (
        Step("reverse", {}), Step("stable_unique", {}), Step("last", {}))
    counterexample = [-16, 20, 4, -22, -16]
    if (_semantic_key(reversed_unique_last) == _semantic_key(first)
            or _apply_procedure(reversed_unique_last, counterexample)
            == _apply_procedure(first, counterexample)):
        raise SystemExit("order-sensitive reverse/deduplicate behavior was merged")

    repeated_then_first = (
        Step("first", {}), Step("repeat_each_k", {"k": 2}),
        Step("first", {}))
    singleton_then_repeated = (
        Step("first", {}), Step("repeat_each_k", {"k": 2}))
    if (_semantic_key(repeated_then_first)
            == _semantic_key(singleton_then_repeated)
            or _apply_procedure(repeated_then_first, [-2])
            == _apply_procedure(singleton_then_repeated, [-2])):
        raise SystemExit("endpoint selection after repetition lost list multiplicity")

    for copies in (2, 3, 4):
        for phase in range(1, copies):
            repeated_rotation = (
                Step("repeat_each_k", {"k": copies}),
                Step("rotate_left_k", {"k": phase}),
            )
            for endpoint in ("first", "last"):
                program = (*repeated_rotation, Step(endpoint, {}))
                if _semantic_key(program) != _semantic_key(first):
                    raise SystemExit(
                        f"partial repeated-run rotation was not canonicalized: {program}")
                if any(_apply_procedure(program, values)
                       != _apply_procedure(first, values)
                       for values in (*probes, [8, 9, 10])):
                    raise SystemExit(
                        f"partial repeated-run rotation changed behavior: {program}")

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "memory.json"
        persistent = CRMSModel(path, max_composition_depth=1, max_workers=1)
        persisted = persistent.teach("remove repeated values", examples)
        if persisted.status != "learned":
            raise SystemExit(f"persistent learning failed: {persisted}")
        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        restored.load()
        result = restored.predict("remove repeated values", [2, 2, 1, 2])
        if result.status != "ok" or result.output != [2, 1]:
            raise SystemExit(f"stable_unique did not persist: {result}")

    print("stable unique rule-learning diagnostic: PASS")
    print("example discovery, held-out order preservation, identity ambiguity, persistence: PASS")


if __name__ == "__main__":
    main()
