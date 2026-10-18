"""Check that bounded program search never commits partial results.

Run from the project root with:
    python3 experiments/v1_75_bounded_composition_search.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def check(depth: int, budget: int) -> None:
    model = CRMSModel(max_composition_depth=depth, max_search_expansions=budget,
                      max_workers=1)
    instruction = f"budgeted depth {depth}"
    result = model.teach(instruction, [([4, 1, 7, 2], [7, 4, 1, 2])])
    if (result.status != "search_incomplete" or result.search_complete
            or result.search_expansions > budget
            or instruction in model.list_rules()
            or len(model._examples.get(instruction, [])) != 1):
        raise SystemExit(f"partial search was not safely reported at depth {depth}: {result}")


def main() -> None:
    check(1, 1)
    check(2, 100)
    check(3, 25)
    check(4, 100)

    with tempfile.TemporaryDirectory() as directory:
        memory = Path(directory) / "memory.json"
        model = CRMSModel(max_composition_depth=3,
                          max_search_expansions=1234, max_workers=1)
        model.save(memory)
        restored = CRMSModel(memory, max_composition_depth=3,
                             max_search_expansions=1234, max_workers=1)
        if restored.max_search_expansions != 1234:
            raise SystemExit("search budget did not survive persistence")
        widened = CRMSModel(memory, max_composition_depth=3,
                             max_search_expansions=2000, max_workers=1)
        if widened.max_search_expansions != 2000:
            raise SystemExit("wider search budget could not reopen persisted memory")
        try:
            CRMSModel(memory, max_composition_depth=3,
                      max_search_expansions=1233, max_workers=1)
        except ValueError:
            pass
        else:
            raise SystemExit("narrower search budget loaded silently")

    print("bounded composition search diagnostic: PASS")
    print("depth budgets, explicit incomplete status, no partial commit, configuration persistence: PASS")


if __name__ == "__main__":
    main()
