"""Measure whether process sharding helps packed VSA case scoring.

The benchmark uses the real 1,000-dimensional packed vectors and reports both
fresh-pool and reused-pool timings. Each worker receives its shard, so transfer
cost is included. It does not modify CRMS runtime behavior.

Run from the project root with:
    python3 experiments/v1_20_parallel_retrieval_diagnostic.py
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import median
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step


def packed_similarity(left: tuple[int, int], right: tuple[int, int],
                      dimension: int = 1000) -> float:
    left_positive, left_nonzero = left
    right_positive, right_nonzero = right
    common = left_nonzero & right_nonzero
    same_bits = left_positive ^ right_positive
    same = common & ~same_bits
    different = common & same_bits
    return (same.bit_count() - different.bit_count()) / dimension


def score_shard(args):
    records, query_position, query_order, alpha = args
    best_score = float("-inf")
    best_phrase = ""
    for phrase, phrase_position, phrase_order in records:
        score = ((1 - alpha) * packed_similarity(query_position, phrase_position)
                 + alpha * packed_similarity(query_order, phrase_order))
        if score > best_score or (score == best_score and phrase < best_phrase):
            best_score, best_phrase = score, phrase
    return best_score, best_phrase


def timed(fn, repeats=3):
    samples = []
    result = None
    for _ in range(repeats):
        start = perf_counter()
        result = fn()
        samples.append(perf_counter() - start)
    return median(samples), result


def suffix(index: int) -> str:
    tokens = []
    for _ in range(5):
        index, digit = divmod(index, 10)
        tokens.append(f"marker{digit}")
    return " ".join(tokens)


def main() -> None:
    count = 50_000
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    procedure = (Step("reverse", {}),)
    for index in range(count):
        model._procedures[f"reverse the list {suffix(index)}"] = procedure

    query_tokens = model._instruction_sequence("reverse the list")
    # Warm every candidate's packed vectors exactly as a common-token VSA query
    # does, then time only independent per-case similarity and local top-1.
    model._retrieve_vsa_procedure("reverse the list")
    query_position, query_order = model._vsa_encoder.encode_packed(query_tokens)
    records = [
        (phrase, *model._vsa_phrase_cache[phrase])
        for phrase in model._procedures
    ]

    serial_seconds, serial = timed(lambda: score_shard(
        (records, query_position, query_order, model.vsa_alpha)))
    print(f"packed vector case scoring: cases={count}; "
          f"serial={serial_seconds:.4f}s; result={serial[1]}")

    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    for workers in (2, 4):
        if workers > available:
            continue
        shards = [records[index::workers] for index in range(workers)]
        args = [(shard, query_position, query_order, model.vsa_alpha)
                for shard in shards]

        def fresh_pool():
            with ProcessPoolExecutor(max_workers=workers) as pool:
                return list(pool.map(score_shard, args))

        fresh_seconds, fresh = timed(fresh_pool)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            reused_seconds, reused = timed(lambda: list(pool.map(score_shard, args)))
        merged = min(fresh, key=lambda item: (-item[0], item[1]))
        reused_merged = min(reused, key=lambda item: (-item[0], item[1]))
        agrees = merged == reused_merged == serial
        print(f"workers={workers}: fresh_pool={fresh_seconds:.4f}s; "
              f"reused_pool={reused_seconds:.4f}s; agrees={agrees}")
        if not agrees:
            raise SystemExit("parallel shard merge differs from serial top-1")


if __name__ == "__main__":
    main()
