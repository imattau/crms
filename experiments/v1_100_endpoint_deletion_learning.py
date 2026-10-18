"""Check discovery and persistence of endpoint-deletion list rules."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def main() -> None:
    examples = {
        "remove the first item": [
            ([3, 9, 1, 7], [9, 1, 7]),
            ([-4, 2, 8], [2, 8]),
            ([1, 2, 1, 3, 2], [2, 1, 3, 2]),
        ],
        "remove the last item": [
            ([3, 9, 1, 7], [3, 9, 1]),
            ([-4, 2, 8], [-4, 2]),
            ([1, 2, 1, 3, 2], [1, 2, 1, 3]),
        ],
    }
    held_out = [[], [5], [0, -3, 11, 2, 8]]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "rules.json"
        model = CRMSModel(path, max_composition_depth=1, max_workers=1)
        for instruction, pairs in examples.items():
            learned = model.teach(instruction, pairs)
            expected_operation = ("drop_first" if "first" in instruction
                                  else "drop_last")
            if (learned.status != "learned" or not learned.procedure
                    or learned.procedure[0]["operation"] != expected_operation):
                raise SystemExit(f"failed to learn {instruction}: {learned}")
            for values in held_out:
                expected = values[1:] if expected_operation == "drop_first" else values[:-1]
                result = model.predict(instruction, values)
                if result.status != "ok" or result.output != expected:
                    raise SystemExit(f"held-out {instruction} failed on {values}: {result}")

        restored = CRMSModel(path, max_composition_depth=1, max_workers=1)
        for instruction, expected_operation in (
                ("remove the first item", "drop_first"),
                ("remove the last item", "drop_last")):
            result = restored.predict(instruction, [6, 1, 4])
            expected = [1, 4] if expected_operation == "drop_first" else [6, 1]
            if result.status != "ok" or result.output != expected:
                raise SystemExit(f"{expected_operation} did not persist: {result}")

    composed_examples = []
    target = (Step("double", {}), Step("keep_greater_than_first", {}),
              Step("drop_last", {}))
    for values in ([1, 2, 3, 4], [3, 8, 1, 9, 4],
                   [-2, 5, 0, 7], [8, 3, 9, -1, 6]):
        composed_examples.append((list(values), _apply_procedure(target, list(values))))
    composed = CRMSModel(max_composition_depth=3, max_workers=1).teach(
        "double then keep greater than first then remove last", composed_examples)
    if composed.status != "learned" or composed.procedure != [
            {"operation": "double", "parameters": {}},
            {"operation": "keep_greater_than_first", "parameters": {}},
            {"operation": "drop_last", "parameters": {}},
    ]:
        raise SystemExit(f"endpoint deletion composition was not discovered: {composed}")

    first = (Step("first", {}),)
    equivalents = (
        ((Step("first", {}), Step("repeat_each_k", {"k": 2}),
          Step("drop_first", {})), first),
        ((Step("repeat_each_k", {"k": 4}), Step("drop_last", {}),
          Step("first", {})), first),
        ((Step("repeat_each_k", {"k": 3}), Step("drop_first", {}),
          Step("last", {})), (Step("last", {}),)),
    )
    probes = [[], [7], [2, 4, 6], [5, 1, 5, -2]]
    for program, expected_program in equivalents:
        if _semantic_key(program) != _semantic_key(expected_program):
            raise SystemExit(f"exact repeated-endpoint deletion not canonicalized: {program}")
        if any(_apply_procedure(program, values)
               != _apply_procedure(expected_program, values)
               for values in probes):
            raise SystemExit(f"endpoint deletion rewrite changed behavior: {program}")
    endpoint_aliases = (
        ((Step("rotate_left_k", {"k": 1}), Step("drop_last", {})),
         (Step("drop_first", {}),)),
        ((Step("rotate_left_k", {"k": -1}), Step("drop_first", {})),
         (Step("drop_last", {}),)),
        ((Step("reverse", {}), Step("drop_first", {}), Step("reverse", {})),
         (Step("drop_last", {}),)),
    )
    for program, expected_program in endpoint_aliases:
        if _semantic_key(program) != _semantic_key(expected_program):
            raise SystemExit(f"endpoint rotation identity not canonicalized: {program}")
        if any(_apply_procedure(program, values)
               != _apply_procedure(expected_program, values)
               for values in probes):
            raise SystemExit(f"endpoint alias rewrite changed behavior: {program}")
    non_equivalent = (Step("first", {}), Step("repeat_each_k", {"k": 3}),
                      Step("drop_first", {}))
    if _semantic_key(non_equivalent) == _semantic_key(first):
        raise SystemExit("multi-copy singleton deletion was unsafely merged")

    print("endpoint deletion learning diagnostic: PASS")
    print("first/last discovery, empty/singleton/held-out behavior, persistence, relational composition: PASS")


if __name__ == "__main__":
    main()
