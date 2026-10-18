"""Check discovery of filters relative to the first input value.

Run from the project root with:
    python3 experiments/v1_74_relational_filter_discovery.py
"""

from __future__ import annotations

import sys
import random
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def check_rule(operation: str,
               examples: list[tuple[list[int], list[int]]],
               held_out: list[tuple[list[int], list[int]]]) -> None:
    instruction = f"relational filter {operation}"
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    result = model.teach(instruction, examples)
    if result.status != "learned":
        raise SystemExit(f"{operation} did not learn uniquely: {result}")
    if (not result.procedure or len(result.procedure) != 1
            or result.procedure[0]["operation"] != operation):
        raise SystemExit(f"{operation} learned an unexpected procedure: {result}")
    for values, expected in held_out:
        prediction = model.predict(instruction, values)
        if prediction.status != "ok" or prediction.output != expected:
            raise SystemExit(f"{operation} failed held-out {values}: {prediction}")
    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "memory.json"
        model.save(memory)
        restored = CRMSModel(memory, max_composition_depth=1, max_workers=1)
        for values, expected in held_out:
            prediction = restored.predict(instruction, values)
            if prediction.status != "ok" or prediction.output != expected:
                raise SystemExit(f"{operation} failed after reload: {prediction}")


def main() -> None:
    check_rule(
        "keep_greater_than_first",
        [([3, 2, 5, 1], [5]), ([-2, -5, 0, 4], [0, 4])],
        [([], []), ([6, 3, 8, 5, 2], [8]), ([0, -3, 0, 1], [1])])
    check_rule(
        "keep_less_than_first",
        [([3, 2, 5, 1], [2, 1]), ([-2, -5, 0, 4], [-5])],
        [([], []), ([6, 3, 8, 5, 2], [3, 5, 2]), ([0, -3, 0, 1], [-3])])

    rng = random.Random(41)
    for depth, target in (
            (2, (Step("keep_greater_than_first", {}), Step("first", {}))),
            (3, (Step("add_k", {"k": 2}),
                 Step("keep_less_than_first", {}), Step("last", {})))):
        examples = []
        while len(examples) < 12:
            values = [rng.randint(-12, 12)
                      for _ in range(rng.randint(5, 9))]
            if len(set(values)) < 4:
                continue
            examples.append((values, _apply_procedure(target, values)))
        instruction = f"relational endpoint depth {depth}"
        model = CRMSModel(max_composition_depth=depth, max_workers=1)
        result = model.teach(instruction, examples)
        if (result.status != "learned"
                or _semantic_key(model._procedures[instruction])
                != _semantic_key(target)):
            raise SystemExit(f"depth-{depth} relational composition ambiguous: {result}")
        held_out = [[-9, 2, 4, 7, 0, 5], [1, -6, -2, 8, 3]]
        for values in held_out:
            expected = _apply_procedure(target, values)
            if model.predict(instruction, values).output != expected:
                raise SystemExit(f"depth-{depth} composition failed held-out {values}")
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "memory.json"
            model.save(memory)
            restored = CRMSModel(memory, max_composition_depth=depth,
                                 max_workers=1)
            if any(restored.predict(instruction, values).output
                   != _apply_procedure(target, values) for values in held_out):
                raise SystemExit(f"depth-{depth} composition failed after reload")

    unshifted = (Step("keep_greater_than_first", {}), Step("first", {}))
    shifted = (Step("add_k", {"k": 2}), *unshifted)
    if _semantic_key(unshifted) == _semantic_key(shifted):
        raise SystemExit("semantic key discarded an affine output transformation")

    print("relational filter discovery diagnostic: PASS")
    print("one-step and bounded composition learning, held-out generalization, persistence, order preservation, empty input: PASS")


if __name__ == "__main__":
    main()
