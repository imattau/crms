"""Measure cold and warm semantic-key cost across deterministic grammar slices.

This is a microbenchmark of the current canonicalizer, not a projection for
future operations. Run with: python3 experiments/v1_175_semantic_key_scaling.py
"""

from __future__ import annotations

from itertools import product
from random import Random
from statistics import median
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import OPERATIONS, Step, _cached_semantic_key, _semantic_key


PARAMETER_DEFAULTS = {
    "add_k": {"k": 2},
    "scale_k": {"k": 2},
    "keep_multiples_k": {"k": 3},
    "rotate_left_k": {"k": 2},
    "repeat_each_k": {"k": 2},
    "keep_every_kth_position": {"k": 3},
}


def _sample_procedures(operation_names: list[str], count: int,
                       seed: int) -> list[tuple[Step, ...]]:
    rng = Random(seed)
    steps = [Step(name, PARAMETER_DEFAULTS.get(name, {}))
             for name in operation_names]
    procedures: dict[tuple, tuple[Step, ...]] = {}

    def retain(procedure: tuple[Step, ...]) -> None:
        key = tuple((step.operation, tuple(sorted(step.parameters.items())))
                    for step in procedure)
        procedures[key] = procedure

    # Include every one-step operation and all ordered pairs, then sample
    # longer mixed sequences. The set removes duplicates from short grammar
    # slices, where the requested sample can exceed the available space.
    for step in steps:
        retain((step,))
    for procedure in product(steps, repeat=2):
        retain(procedure)
    target = max(count, len(procedures))
    while len(procedures) < target:
        width = rng.choice((2, 3, 4))
        retain(tuple(rng.choice(steps) for _ in range(width)))
    return [procedures[key] for key in sorted(procedures, key=repr)[:target]]


def _measure(procedures: list[tuple[Step, ...]]) -> tuple[float, float, int, int]:
    cold_runs: list[float] = []
    warm_runs: list[float] = []
    cold_cache = None
    for _ in range(3):
        _cached_semantic_key.cache_clear()
        start = perf_counter()
        cold_keys = [_semantic_key(procedure) for procedure in procedures]
        cold_runs.append(perf_counter() - start)
        cold_cache = _cached_semantic_key.cache_info()

        start = perf_counter()
        warm_keys = [_semantic_key(procedure) for procedure in procedures]
        warm_runs.append(perf_counter() - start)
        if cold_keys != warm_keys:
            raise SystemExit("semantic keys changed between cold and warm runs")
    assert cold_cache is not None
    return (median(cold_runs), median(warm_runs),
            cold_cache.misses, cold_cache.hits)


def main() -> None:
    # Operation names are sorted so grammar slices and results are stable.
    names = sorted(OPERATIONS)
    if len(names) < 8:
        raise SystemExit(f"semantic-key benchmark needs at least 8 operations, found {len(names)}")
    print("semantic-key scaling microbenchmark (current grammar only; 3-run medians)")
    print("operations procedures cold_us/proc warm_us/proc misses hits")
    operation_counts = sorted({min(count, len(names))
                               for count in (8, 16, 24, len(names))})
    for operation_count in operation_counts:
        selected = names[:operation_count]
        requested = 4000
        procedures = _sample_procedures(selected, requested, 175 + operation_count)
        cold, warm, misses, hits = _measure(procedures)
        size = len(procedures)
        print(f"{operation_count:10d} {size:11d} "
              f"{cold * 1e6 / size:12.2f} {warm * 1e6 / size:12.2f} "
              f"{misses:6d} {hits:6d}")


if __name__ == "__main__":
    main()
