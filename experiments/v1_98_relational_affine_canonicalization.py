"""Check exact equivalence classes around first-relative filters."""

from __future__ import annotations

import random
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crms_model import Step, _apply_procedure, _semantic_key


def main() -> None:
    pairs = [
        (
            (Step('repeat_each_k', {'k': 4}), Step('add_k', {'k': -6}),
             Step('keep_greater_than_first', {})),
            (Step('add_k', {'k': -6}), Step('repeat_each_k', {'k': 4}),
             Step('keep_greater_than_first', {})),
        ),
        (
            (Step('double', {}), Step('keep_greater_than_first', {}),
             Step('add_k', {'k': -9})),
            (Step('double', {}), Step('add_k', {'k': -9}),
             Step('keep_greater_than_first', {})),
        ),
        (
            (Step('scale_k', {'k': -3}), Step('keep_greater_than_first', {}),
             Step('repeat_each_k', {'k': 2})),
            (Step('scale_k', {'k': -3}), Step('repeat_each_k', {'k': 2}),
             Step('keep_greater_than_first', {})),
        ),
    ]
    rng = random.Random(98)
    probes = [[], [0], [1, 2, 3], [4, 4, 7], [8, 3, 9, -2]]
    probes.extend([[rng.randint(-50, 50) for _ in range(rng.randint(1, 10))]
                   for _ in range(300)])
    for left, right in pairs:
        if _semantic_key(left) != _semantic_key(right):
            raise SystemExit(f'equivalent relative-filter programs not grouped: {left} / {right}')
        if any(_apply_procedure(left, values) != _apply_procedure(right, values)
               for values in probes):
            raise SystemExit(f'canonicalization pair differs on probes: {left} / {right}')

    # Audit every key collision among short programs containing exactly one
    # relative filter. A collision is safe only when all list outputs agree.
    vocabulary = (
        Step('scale_k', {'k': 2}), Step('scale_k', {'k': -1}),
        Step('add_k', {'k': 1}), Step('repeat_each_k', {'k': 2}),
        Step('keep_greater_than_first', {}),
        Step('keep_less_than_first', {}),
    )
    programs = []
    for depth in (1, 2, 3):
        for program in product(vocabulary, repeat=depth):
            if sum(step.operation in {'keep_greater_than_first',
                                      'keep_less_than_first'}
                   for step in program) == 1:
                programs.append(program)
    exhaustive = [[]]
    for length in range(1, 5):
        exhaustive.extend(list(values) for values in
                          product(range(-2, 3), repeat=length))
    representatives = {}
    collision_count = 0
    for program in programs:
        key = _semantic_key(program)
        prior = representatives.setdefault(key, program)
        if prior == program:
            continue
        collision_count += 1
        if any(_apply_procedure(prior, values)
               != _apply_procedure(program, values)
               for values in exhaustive):
            raise SystemExit(
                f'unsound relative-filter semantic-key collision: {prior} / {program}')
    print('relative-filter affine canonicalization: PASS')
    print(f'{len(pairs)} exact equivalence classes; {len(probes)} probes each')
    print(f'{len(programs)} short programs; {collision_count} key collisions '
          f'checked on {len(exhaustive)} exhaustive lists each')


if __name__ == '__main__':
    main()
