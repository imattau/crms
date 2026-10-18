"""Check that the bounded search's length pruning never rejects real paths."""

from __future__ import annotations

import random
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, _apply_procedure, _list_length_can_reach,
)


def main() -> None:
    model = CRMSModel(max_composition_depth=4, max_workers=1)
    lists = [[]]
    for length in range(1, 6):
        lists.extend((list(range(-2, -2 + length)),
                      [0] * length,
                      [(-1) ** index * (index + 1) for index in range(length)]))

    # Exhaustively check every one- and two-step path over the configured rule
    # library for representative input lists, then sample depth-three paths.
    for values, first, second in product(lists, model._steps, model._steps):
        output = _apply_procedure((first, second), values)
        if not _list_length_can_reach(len(values), len(output), 2,
                                      model.max_repeat, can_sum=True):
            raise SystemExit(
                f"pruned a real two-step length path: {values}, {first}, {second}"
            )

    rng = random.Random(115)
    for _ in range(2500):
        values = rng.choice(lists)
        procedure = tuple(rng.choice(model._steps) for _ in range(3))
        output = _apply_procedure(procedure, values)
        if not _list_length_can_reach(len(values), len(output), 3,
                                      model.max_repeat, can_sum=True):
            raise SystemExit(
                f"pruned a real sampled three-step length path: {procedure}"
            )

    if any(_list_length_can_reach(0, 1, steps, model.max_repeat)
           for steps in range(5)):
        raise SystemExit("length analysis allowed elements to be created from empty")
    if not _list_length_can_reach(0, 1, 1, model.max_repeat,
                                  can_sum=True):
        raise SystemExit("sum output length from an empty input was pruned")
    if not _list_length_can_reach(0, 3, 2, model.max_repeat,
                                  can_sum=True):
        raise SystemExit("sum followed by repetition length was pruned")
    if _list_length_can_reach(5, 6, 1, model.max_repeat):
        raise SystemExit("one step incorrectly allowed a non-repeat length increase")
    if not _list_length_can_reach(5, 6, 2, model.max_repeat):
        raise SystemExit("filter-then-repeat length path was pruned")

    print("length reachability pruning diagnostic: PASS")
    print("all one/two-step paths, 2500 depth-three samples, safe controls: PASS")


if __name__ == "__main__":
    main()
