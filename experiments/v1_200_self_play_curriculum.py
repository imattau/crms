"""Exercise bounded, mechanically supervised rule-learning self-play.

The target sampler uses a small hand-declared program specification; an
independent interpreter generates examples.  CRMS receives opaque task labels
and only input/output pairs.  A machine teacher answers CRMS's contrastive
requests, then a finite exhaustive/seeded audit checks the learned behavior.
Nothing is written to persistent user memory.  This evaluates synthesis and
curriculum mechanics; it does not teach natural-language meanings or discover
operations outside the target set.
"""
from __future__ import annotations

import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure


TARGETS = (
    (Step('add_k', {'k': 2}),),
    (Step('add_k', {'k': 1}), Step('reverse', {})),
    (Step('keep_odds', {}), Step('sort_ascending', {})),
    (Step('repeat_each_k', {'k': 3}), Step('reverse', {})),
    (Step('first', {}), Step('add_k', {'k': 1})),
)
TRAINING_INPUTS = [
    [3, -2, 1, 4], [], [-5, 0, 2], [8, 7, 7], [1], [4, -1, 6],
]


def specified_output(procedure: tuple[Step, ...], values: list[int]) -> list[int]:
    """Independent reference interpreter for the sampled operation subset."""
    result = list(values)
    for step in procedure:
        if step.operation == 'add_k':
            result = [value + step.parameters['k'] for value in result]
        elif step.operation == 'reverse':
            result = list(reversed(result))
        elif step.operation == 'keep_odds':
            result = [value for value in result if value % 2]
        elif step.operation == 'sort_ascending':
            result = sorted(result)
        elif step.operation == 'first':
            result = result[:1]
        elif step.operation == 'repeat_each_k':
            count = step.parameters['k']
            result = [value for item in result for value in [item] * count]
        else:
            raise ValueError(f'unsupported self-play target: {step.operation}')
    return result


def validation_inputs() -> list[list[int]]:
    """Exhaustive short lists plus fixed seeded longer cases."""
    values = [-2, -1, 0, 1, 2]
    result = [list(items) for length in range(5)
              for items in itertools.product(values, repeat=length)]
    rng = random.Random(200)
    result.extend([[rng.randint(-20, 20)
                    for _ in range(rng.randint(5, 12))]
                   for _ in range(32)])
    return result


def distinguishing_probe(model: CRMSModel, candidates: list[list[dict]],
                         target: tuple[Step, ...],
                         probes: list[list[int]]) -> list[int] | None:
    procedures = [tuple(Step(item['operation'], item.get('parameters', {}))
                        for item in candidate)
                  for candidate in candidates]
    for values in probes:
        expected = specified_output(target, values)
        if any(_apply_procedure(procedure, values) != expected
               for procedure in procedures):
            return values
    return None


def train_self_play_task(index: int, target: tuple[Step, ...],
                         probes: list[list[int]]) -> tuple[int, int, int]:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    phrase = f'curriculum task {index}'
    examples = [(values, specified_output(target, values))
                for values in TRAINING_INPUTS]
    rounds = 0
    while rounds < 20:
        result = model.teach(phrase, examples)
        rounds += 1
        if result.status == 'learned':
            learned = model._procedures[phrase]
            counterexample = next((values for values in probes
                                   if _apply_procedure(learned, values)
                                   != specified_output(target, values)), None)
            if counterexample is None:
                return rounds, len(examples), len(probes)
            examples.append((counterexample,
                             specified_output(target, counterexample)))
            continue

        if result.status != 'need_more_examples':
            raise SystemExit(
                f'task {index} stopped with {result.status}: {result.message}')
        probe = result.contrastive_input
        if probe is None:
            probe = distinguishing_probe(
                model, result.candidate_procedures or [], target, probes)
        if probe is None or any(existing == probe for existing, _ in examples):
            raise SystemExit(
                f'task {index} has unresolved candidates but no new separating input')
        examples.append((list(probe), specified_output(target, list(probe))))
    raise SystemExit(f'task {index} exceeded the bounded teaching-round limit')


def main() -> None:
    probes = validation_inputs()
    total_rounds = 0
    total_examples = 0
    for index, target in enumerate(TARGETS):
        rounds, examples, checked = train_self_play_task(index, target, probes)
        total_rounds += rounds
        total_examples += examples
        print(f'task {index}: depth={len(target)}; examples={examples}; '
              f'teacher rounds={rounds}; audit inputs={checked}; PASS')
    print(f'mechanically supervised self-play: {len(TARGETS)} tasks, '
          f'{total_examples} examples, {total_rounds} training rounds; PASS')


if __name__ == '__main__':
    main()
