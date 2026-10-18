"""Sweep deterministic generated two- and three-step rule programs.

Programs are sampled from the active search-step space. The learner receives
only generated instruction strings and input/output examples. After learning,
the returned program is compared by exact semantic key and by outputs on
fresh, wider-range input lists.

Run from the project root with:
    python3 experiments/v1_14_generated_composition_sweep.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _apply_procedure, _extend_search_signature,
    _semantic_key,
)


SEED = 73
PROGRAM_COUNT = 40
MAX_EXAMPLES = 40


def random_list(rng: random.Random, low: int, high: int) -> list[int]:
    return [rng.randint(low, high) for _ in range(rng.randint(3, 7))]


def main() -> None:
    rng = random.Random(SEED)
    search = CRMSModel(max_composition_depth=3, max_workers=1)
    seen_behaviors = set()
    targets: list[tuple[Step, ...]] = []
    while len(targets) < PROGRAM_COUNT:
        depth = rng.choice((2, 3))
        signature = (False, False, True)
        steps = []
        for _ in range(depth):
            eligible = [
                (step, next_signature)
                for step in search._steps
                if (next_signature := _extend_search_signature(
                    signature, step)) is not None
            ]
            step, signature = rng.choice(eligible)
            steps.append(step)
        target = tuple(steps)
        behavior = _semantic_key(target)
        if behavior in seen_behaviors:
            continue
        seen_behaviors.add(behavior)
        targets.append(target)

    failures = []
    examples_required = Counter()
    contrastive_examples_used = 0
    for index, target in enumerate(targets):
        phrase = f"generated composition trial {index:02d}"
        # Keep each trial's training and held-out data independent of how many
        # random examples earlier trials happened to consume. A learner change
        # must not silently replace the later trial inputs and invalidate the
        # before/after comparison.
        trial_rng = random.Random(SEED * 1009 + index)
        model = CRMSModel(max_composition_depth=3, max_workers=1)
        result = None
        example_count = 0
        suggested_input = None
        probe_history = []
        while example_count < MAX_EXAMPLES:
            values = (suggested_input if suggested_input is not None
                      else random_list(trial_rng, -12, 12))
            suggested_input = None
            output = _apply_procedure(target, values)
            result = model.teach(phrase, [(values, output)])
            example_count += 1
            if result.status == "need_more_examples" and result.contrastive_input is not None:
                probe_history.append((result.candidate_count,
                                      result.contrastive_input))
                probe_outputs = result.candidate_outputs or []
                if len({tuple(candidate) for candidate in probe_outputs}) < 2:
                    raise RuntimeError(
                        f"non-separating contrastive probe for trial {index}: "
                        f"{result.contrastive_input} -> {probe_outputs}"
                    )
                output_at_probe = _apply_procedure(target, result.contrastive_input)
                if output_at_probe not in probe_outputs:
                    raise RuntimeError(
                        f"contrastive probe omitted target output for trial {index}: "
                        f"{output_at_probe} not in {probe_outputs}"
                    )
                suggested_input = result.contrastive_input
                contrastive_examples_used += 1
            if result.status in ("learned", "no_fit"):
                break

        learned = model._procedures.get(phrase)
        behavior_matches = (
            result is not None
            and result.status == "learned"
            and learned is not None
            and _semantic_key(learned) == _semantic_key(target)
        )
        held_out = [
            [trial_rng.randint(-40, 40)
             for _ in range(trial_rng.randint(0, 8))]
            for _ in range(3)
        ]
        held_out_matches = behavior_matches and all(
            model.predict(phrase, values).output == _apply_procedure(target, values)
            for values in held_out
        )
        if held_out_matches:
            examples_required[example_count] += 1
        else:
            failures.append((index, example_count,
                             None if result is None else result.status,
                             target, None if result is None else result.procedure,
                             None if result is None else result.candidate_count,
                             probe_history))

    print(
        f"generated_compositions={PROGRAM_COUNT} seed={SEED} "
        f"max_examples={MAX_EXAMPLES}"
    )
    print(f"learned_and_generalized={PROGRAM_COUNT - len(failures)}/{PROGRAM_COUNT}")
    print(f"examples_to_unique_rule={dict(sorted(examples_required.items()))}")
    print(f"contrastive_examples_used={contrastive_examples_used}")
    if failures:
        print(f"failures={failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
