"""Exercise count canonicalization against executable bounded inputs."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_model import Step, _apply_procedure, _semantic_key


COUNT = Step("count_values", {})
PREFIXES = (
    Step("identity", {}), Step("reverse", {}),
    Step("sort_ascending", {}), Step("sort_descending", {}),
    Step("sort_by_magnitude", {}), Step("rotate_left_k", {"k": 2}),
    Step("add_k", {"k": -3}), Step("scale_k", {"k": -2}),
    Step("double", {}), Step("square_values", {}),
    Step("absolute_values", {}), Step("add_position", {}),
    Step("add_first", {}), Step("subtract_first", {}),
    Step("cumulative_sum", {}),
)
SUFFIXES = (
    Step("identity", {}), Step("reverse", {}),
    Step("sort_ascending", {}), Step("sort_descending", {}),
    Step("sort_by_magnitude", {}), Step("rotate_left_k", {"k": -3}),
    Step("stable_unique", {}), Step("first", {}), Step("last", {}),
    Step("keep_odd_positions", {}), Step("cumulative_sum", {}),
    Step("absolute_values", {}), Step("sum_values", {}),
)
INPUTS = [list(values) for length in range(5)
          for values in itertools.product((-2, 0, 3), repeat=length)]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    equivalents = 0
    for prefix in PREFIXES:
        for suffix in SUFFIXES:
            procedure = (prefix, COUNT, suffix)
            require(_semantic_key(procedure) == _semantic_key((COUNT,)),
                    f"count equivalence did not canonicalize: {procedure}")
            for values in INPUTS:
                expected = _apply_procedure((COUNT,), values)
                actual = _apply_procedure(procedure, values)
                require(actual == expected,
                        f"key merged different outputs for {values}: "
                        f"{procedure} -> {actual}, count -> {expected}")
                equivalents += 1

    values = [1, 1, 2]
    distinct = (
        (Step("stable_unique", {}), COUNT),
        (COUNT, Step("add_k", {"k": 1})),
        (Step("keep_even_positions", {}), COUNT),
        (Step("first", {}), COUNT),
    )
    for procedure in distinct:
        require(_semantic_key(procedure) != _semantic_key((COUNT,)),
                f"a behavior-changing count procedure was merged: {procedure}")
        require(_apply_procedure(procedure, values)
                != _apply_procedure((COUNT,), values),
                f"the negative control does not distinguish {procedure}")

    print(f"count-preserving equivalences match runtime on {equivalents} cases: PASS")
    print("length-changing and value-changing count compositions remain distinct: PASS")
    print("scope: bounded exhaustive check over lists of length 0–4 and values {-2,0,3}")


if __name__ == "__main__":
    main()
