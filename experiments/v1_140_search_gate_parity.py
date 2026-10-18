"""Check incremental search gates against the original prefix predicates.

Run from the project root with:
    python3 experiments/v1_140_search_gate_parity.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _RELATIONAL_ENDPOINT_OPERATIONS,
    _RELATIONAL_FILTER_OPERATIONS, _extend_search_signature,
    _position_sequence_extension_allowed, _sequence_extension_signature,
)


def main() -> None:
    model = CRMSModel(max_composition_depth=4, max_workers=1)
    rng = random.Random(140)
    prefixes: list[tuple[Step, ...]] = [()]
    prefixes.extend((step,) for step in model._steps)
    prefixes.extend(tuple(rng.choice(model._steps)
                          for _ in range(rng.randint(2, 6)))
                    for _ in range(2_000))

    checked = 0
    for prefix in prefixes:
        signature = _sequence_extension_signature(prefix)
        has_relational = any(
            step.operation in _RELATIONAL_FILTER_OPERATIONS
            for step in prefix)
        for next_step in model._steps:
            expected_allowed = (
                (not has_relational
                 or next_step.operation in _RELATIONAL_ENDPOINT_OPERATIONS)
                and _position_sequence_extension_allowed(prefix, next_step))
            actual = _extend_search_signature(signature, next_step)
            if (actual is not None) != expected_allowed:
                raise SystemExit(
                    f"gate mismatch for {prefix!r} + {next_step!r}: "
                    f"expected {expected_allowed}, got {actual}")
            if expected_allowed and actual != _sequence_extension_signature(
                    prefix + (next_step,)):
                raise SystemExit(
                    f"signature mismatch for {prefix!r} + {next_step!r}")
            checked += 1

    print("incremental search-gate parity diagnostic: PASS")
    print(f"all {checked:,} operation extensions match the prefix rules: PASS")


if __name__ == "__main__":
    main()
