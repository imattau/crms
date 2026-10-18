"""Infer and test two-step CRMS procedures from input/output demonstrations.

This asks whether examples can ground a new phrase to a composition of
existing primitives. It is a finite synthetic test, not open-ended learning.
Run: python v1_8_composition_learning.py
"""
from itertools import product

from v1_3_crms import TRANSFORMS


def apply(step, xs):
    name, params = step
    return TRANSFORMS[name](list(xs), **params)


def candidates():
    # Finite hypothesis space: one or two ordered steps; add_k uses +3.
    steps = [(name, {}) for name in TRANSFORMS if name != 'add_k']
    steps += [('add_k', {'k': 3})]
    return [(step,) for step in steps] + list(product(steps, repeat=2))


def run(proc, xs):
    for step in proc:
        xs = apply(step, xs)
    return xs


def infer(examples):
    return [p for p in candidates()
            if all(run(p, x) == y for x, y in examples)]


class CompositionMemory:
    def __init__(self):
        self.rules = {}

    def learn(self, phrase, examples):
        fits = infer(examples)
        if len(fits) != 1:
            return {'status': 'ambiguous' if fits else 'no_fit', 'candidates': fits}
        self.rules[phrase.lower()] = fits[0]
        return {'status': 'learned', 'procedure': fits[0], 'candidates': fits}

    def process(self, phrase, xs):
        proc = self.rules.get(phrase.lower())
        return None if proc is None else run(proc, xs)


def fmt(proc):
    return ' -> '.join(name + (f'({params})' if params else '') for name, params in proc)


def main():
    print('=== Two-step procedure learning ===')
    phrase = 'apply the doubling operation twice'
    # Teacher gives only examples; no operation labels are passed to inference.
    demos = [([1, 2, 3, 4], [4, 8, 12, 16]),
             ([7, 8, 1, 6, 3], [28, 32, 4, 24, 12]),
             ([5, 2, 9, 4], [20, 8, 36, 16])]
    mem = CompositionMemory()
    before = mem.process(phrase, [5, 2, 9, 4])
    result = mem.learn(phrase, demos)
    tests = [[5, 2, 9, 4], [-3, 10, 7, 0, 5], [12, 1, -8, 3]]
    expected = [ [4 * x for x in xs] for xs in tests ]
    got = [mem.process(phrase, xs) for xs in tests]
    print(f'Unseen phrase before examples: {before}')
    print(f'Two demonstrations: {result["status"]}; compatible procedures={len(result["candidates"])}')
    if result['status'] == 'learned':
        print(f'Inferred: {fmt(result["procedure"])}')
    print(f'Held-out procedures: {sum(a == b for a,b in zip(got,expected))}/{len(tests)} correct')
    print(f'Outputs: {got}; expected: {expected}')

    # One-example ambiguity: reversing then selecting evens and selecting evens
    # then reversing agree on this symmetric example. Ask for another example.
    ambiguous = CompositionMemory()
    one = [([2, 4], [4, 2])]
    r1 = ambiguous.learn('ambiguous operation', one)
    r2 = ambiguous.learn('ambiguous operation', one + [([1, 2, 3, 4], [4, 2])])
    print(f'\nAmbiguity test: one example -> {r1["status"]} '
          f'({len(r1["candidates"])} candidates); contrastive example -> '
          f'{r2["status"]} ({len(r2["candidates"])} candidates)')

    # Falsification control: rotate-left is not expressible by this 2-step library.
    unsupported = [([1, 2, 3, 4], [2, 3, 4, 1]),
                   ([8, -1, 5, 2], [-1, 5, 2, 8]),
                   ([6, 0, 9], [0, 9, 6])]
    control = infer(unsupported)
    print(f'Unsupported-rule control (rotate left): {"incorrectly fit" if control else "rejected"}; '
          f'compatible procedures={len(control)}')

    # Generalization falsifier: remove one demonstration and check which
    # procedures survive; if there are many, the system should ask more.
    weak = infer(demos[:1])
    print(f'One-demo composition ambiguity: {len(weak)} candidate procedures; '
          f'committed={len(weak) == 1}')


if __name__ == '__main__':
    main()
