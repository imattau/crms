"""Check bounded memoization preserves semantic procedure keys.

Run from the project root with:
    python3 experiments/v1_142_semantic_key_cache.py
"""

from __future__ import annotations

import random
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import crms_model
from crms_model import Step, _cached_semantic_key, _semantic_key


def main() -> None:
    vocabulary = (
        Step("scale_k", {"k": -2}), Step("add_k", {"k": 3}),
        Step("reverse", {}), Step("rotate_left_k", {"k": 1}),
        Step("keep_multiples_k", {"k": 3}),
        Step("keep_greater_than_first", {}),
        Step("repeat_each_k", {"k": 2}), Step("first", {}),
        Step("sort_by_magnitude", {}), Step("cumulative_sum", {}),
    )
    programs = [tuple(program) for depth in range(5)
                for program in product(vocabulary, repeat=depth)]
    rng = random.Random(142)
    programs.extend(tuple(rng.choice(vocabulary)
                          for _ in range(rng.randint(1, 6)))
                    for _ in range(1_000))

    cached_helper = crms_model._cached_semantic_key
    uncached_helper = lambda key: crms_model._semantic_key_uncached(
        tuple(Step(operation, dict(parameters))
              for operation, parameters in key))
    _cached_semantic_key.cache_clear()
    crms_model._cached_semantic_key = uncached_helper
    try:
        expected = [_semantic_key(program) for program in programs]
    finally:
        crms_model._cached_semantic_key = cached_helper

    _cached_semantic_key.cache_clear()
    actual = [_semantic_key(program) for program in programs]
    if actual != expected:
        mismatch = next(index for index, pair in enumerate(zip(actual, expected))
                        if pair[0] != pair[1])
        raise SystemExit(f"cached key differs at program {programs[mismatch]!r}")
    repeated = [_semantic_key(program) for program in programs[:100]]
    if repeated != actual[:100]:
        raise SystemExit("repeated cached lookup changed a semantic key")

    mutable = [Step("scale_k", {"k": 2})]
    first_key = _semantic_key(mutable)
    mutable[0].parameters["k"] = 3
    second_key = _semantic_key(mutable)
    if first_key == second_key:
        raise SystemExit("mutated procedure reused a stale cache entry")

    info = _cached_semantic_key.cache_info()
    if info.maxsize != 131_072 or info.currsize > info.maxsize or info.hits == 0:
        raise SystemExit(f"unexpected cache bounds or reuse: {info}")

    print("semantic-key memoization diagnostic: PASS")
    print(f"cached/uncached parity: {len(programs):,} programs; "
          f"runtime hits={info.hits}, entries={info.currsize}/{info.maxsize}; "
          "mutable-parameter invalidation: PASS")


if __name__ == "__main__":
    main()
