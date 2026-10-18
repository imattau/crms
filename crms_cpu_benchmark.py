"""CPU-only benchmark comparing reference and cached CRMS inference search.

Run: python crms_cpu_benchmark.py
Uses only the Python standard library plus crms_model.py. No accelerator APIs.
"""
from time import perf_counter

from crms_model import CRMSModel, _apply_procedure


def reference_search(model, examples):
    """Straightforward exhaustive search used as a correctness/time reference."""
    found = []
    for first in model._steps:
        one = (first,)
        if all(_apply_procedure(one, x) == y for x, y in examples):
            found.append(one)
        if model.max_composition_depth == 2:
            for second in model._steps:
                pair = (first, second)
                if all(_apply_procedure(pair, x) == y for x, y in examples):
                    found.append(pair)
    unique = {tuple((s.operation, tuple(sorted(s.parameters.items()))) for s in p): p
              for p in found}
    return list(unique.values())


def timed(fn, repetitions=3):
    samples = []
    result = None
    for _ in range(repetitions):
        start = perf_counter()
        result = fn()
        samples.append(perf_counter() - start)
    return sorted(samples)[len(samples) // 2], result


def main():
    examples = [([1, 2, 3, 4, 5], [8, 6, 4, 2]),
                ([9, 4, 7, 2, 6], [12, 8, 4])]
    print('CPU-only procedure search benchmark (median of 3, seconds)')
    print('max_add | primitive rules | ref time | cached serial | parallel | speedup | results agree')
    for bound in (10, 50, 150):
        model = CRMSModel(max_composition_depth=2, max_add=bound,
                          max_workers=1, parallel_min_work=10_000)
        parallel_model = CRMSModel(max_composition_depth=2, max_add=bound,
                                   parallel_min_work=0)
        reference_time, reference = timed(lambda: reference_search(model, examples))
        cached_time, cached = timed(lambda: model._infer(examples))
        parallel_time, parallel = timed(lambda: parallel_model._infer(examples))
        agree = {tuple((s.operation, tuple(sorted(s.parameters.items()))) for s in p)
                 for p in reference} == {
                     tuple((s.operation, tuple(sorted(s.parameters.items()))) for s in p)
                     for p in cached}
        parallel_agree = {tuple((s.operation, tuple(sorted(s.parameters.items()))) for s in p)
                          for p in cached} == {
                              tuple((s.operation, tuple(sorted(s.parameters.items()))) for s in p)
                              for p in parallel}
        print(f'{bound:7d} | {len(model._steps):15d} | {reference_time:8.4f} | '
              f'{cached_time:13.4f} | {parallel_time:8.4f} | '
              f'{cached_time/max(parallel_time, 1e-12):7.2f}x | {agree and parallel_agree}')


if __name__ == '__main__':
    main()
