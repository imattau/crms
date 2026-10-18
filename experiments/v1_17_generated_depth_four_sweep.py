"""Sweep generated four-step behaviors that need depth four to express.

Targets are sampled from the configured operation steps. Any target behavior
represented at depth three or less is excluded, so this measures the added
search depth rather than redundant four-step spellings.

Run from the project root with:
    python3 experiments/v1_17_generated_depth_four_sweep.py
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _apply_procedure, _contrastive_probe,
    _position_sequence_extension_allowed, _semantic_key,
)


SEED = 1701
PROGRAM_COUNT = 6
MAX_EXAMPLES = 8


def random_list(rng: random.Random, low: int, high: int) -> list[int]:
    return [rng.randint(low, high) for _ in range(rng.randint(3, 7))]


def grammar_admits(procedure: tuple[Step, ...]) -> bool:
    """Mirror the search's exact sequence restrictions for generated targets."""
    relational = {"keep_greater_than_first", "keep_less_than_first"}
    endpoints = {"first", "last", "drop_first", "drop_last"}
    prefix: tuple[Step, ...] = ()
    for step in procedure:
        if (any(previous.operation in relational for previous in prefix)
                and step.operation not in endpoints):
            return False
        if not _position_sequence_extension_allowed(prefix, step):
            return False
        prefix += (step,)
    return True


def main() -> None:
    rng = random.Random(SEED)
    search = CRMSModel(max_composition_depth=4, max_workers=1)

    # Enumerate semantic behavior classes through depth three. These programs
    # are only the audit's exclusion set; no labels enter CRMS teaching.
    shorter_behaviors = {_semantic_key(())}
    frontier: list[tuple[Step, ...]] = [()]
    for _depth in range(1, 4):
        next_frontier = []
        for procedure in frontier:
            for step in search._steps:
                extended = procedure + (step,)
                behavior = _semantic_key(extended)
                if behavior not in shorter_behaviors:
                    shorter_behaviors.add(behavior)
                    next_frontier.append(extended)
        frontier = next_frontier

    targets = []
    seen = set()
    while len(targets) < PROGRAM_COUNT:
        target = tuple(rng.choice(search._steps) for _ in range(4))
        behavior = _semantic_key(target)
        if (not grammar_admits(target) or behavior in shorter_behaviors
                or behavior in seen):
            continue
        seen.add(behavior)
        targets.append(target)

    failures = []
    examples_to_rule = Counter()
    total_contrasts = 0
    for index, target in enumerate(targets):
        instruction = f"generated depth four trial {index:02d}"
        model = CRMSModel(max_composition_depth=4, max_workers=1)
        result = None
        examples_used = 0
        suggested_input = None
        while examples_used < MAX_EXAMPLES:
            values = (suggested_input if suggested_input is not None
                      else random_list(rng, -20, 20))
            suggested_input = None
            result = model.teach(
                instruction,
                [(values, _apply_procedure(target, values))],
            )
            examples_used += 1
            learned = model._procedures.get(instruction)
            if (result.status == "need_more_examples"
                    and result.contrastive_input is not None):
                probe_outputs = result.candidate_outputs or []
                if len({tuple(output) for output in probe_outputs}) < 2:
                    raise RuntimeError(
                        f"non-separating probe for trial {index}: "
                        f"{result.contrastive_input}"
                    )
                suggested_input = result.contrastive_input
                target_output = _apply_procedure(target, suggested_input)
                if target_output not in probe_outputs:
                    raise RuntimeError(
                        f"probe omitted target output for trial {index}: "
                        f"{target_output} not in {probe_outputs}"
                    )
                total_contrasts += 1
            elif (result.status == "need_more_examples"
                  and result.contrastive_input is None):
                target_key = _semantic_key(target)
                target_present = False
                alternatives = []
                for encoded in result.candidate_procedures or []:
                    candidate = tuple(
                        Step(step["operation"], step.get("parameters", {}))
                        for step in encoded)
                    if _semantic_key(candidate) == target_key:
                        target_present = True
                    elif len(alternatives) < 512:
                        alternatives.append(candidate)
                if not target_present:
                    raise RuntimeError(
                        f"complete candidates omitted target for trial {index}: "
                        f"target={target}; examples={model._examples[instruction]}; "
                        f"candidate_count={result.candidate_count}"
                    )
                # Search one shared deterministic probe set against all
                # alternatives. This finds counterexamples that a small
                # per-candidate probe budget can miss, while keeping teacher
                # selection independent of any assumed candidate ranking.
                probe_rng = random.Random(SEED + 1009 * index)
                teacher_probes = [
                    [probe_rng.randint(-100, 100)
                     for _ in range(probe_rng.randint(0, 12))]
                    for _ in range(2_000)
                ]
                best_probe = None
                best_rank = None
                for candidate_probe in teacher_probes:
                    target_output = _apply_procedure(target, candidate_probe)
                    outputs = [tuple(target_output)]
                    outputs.extend(tuple(_apply_procedure(candidate,
                                                          candidate_probe))
                                   for candidate in alternatives)
                    target_class_size = sum(
                        output == tuple(target_output) for output in outputs)
                    if target_class_size == len(outputs):
                        continue
                    # The synthetic teacher chooses a probe that leaves the
                    # smallest target-consistent class; this avoids spending
                    # the example budget on a separator that only rejects one
                    # irrelevant candidate.
                    rank = (target_class_size, -len(set(outputs)))
                    if best_rank is None or rank < best_rank:
                        best_probe, best_rank = candidate_probe, rank
                if best_probe is not None:
                    suggested_input = best_probe
                    total_contrasts += 1
            if (result.status == "learned" and learned is not None
                    and _semantic_key(learned) == _semantic_key(target)):
                break
            if result.status == "learned" and learned is not None:
                # A unique fit to the demonstrations can still be the wrong
                # general rule. Ask the synthetic teacher for a counterexample.
                probe, outputs = _contrastive_probe([target, learned])
                if (probe is None or outputs is None
                        or len({tuple(output) for output in outputs}) < 2):
                    for _ in range(2_000):
                        candidate_probe = [
                            rng.randint(-100, 100)
                            for _ in range(rng.randint(0, 12))
                        ]
                        pair = [_apply_procedure(target, candidate_probe),
                                _apply_procedure(learned, candidate_probe)]
                        if pair[0] != pair[1]:
                            probe, outputs = candidate_probe, pair
                            break
                if (probe is None or outputs is None
                        or len({tuple(output) for output in outputs}) < 2):
                    break
                if _apply_procedure(target, probe) not in outputs:
                    raise RuntimeError(
                        f"teacher target missing from corrective probe for trial {index}"
                    )
                suggested_input = probe
                total_contrasts += 1
            elif result.status == "no_fit":
                break

        learned = model._procedures.get(instruction)
        matches = (
            result is not None
            and result.status == "learned"
            and learned is not None
            and _semantic_key(learned) == _semantic_key(target)
        )
        held_out = [
            [rng.randint(-60, 60) for _ in range(rng.randint(0, 8))]
            for _ in range(4)
        ]
        generalized = matches and all(
            model.predict(instruction, values).output
            == _apply_procedure(target, values)
            for values in held_out
        )
        if generalized:
            examples_to_rule[examples_used] += 1
        else:
            target_present = any(
                _semantic_key(tuple(
                    Step(step["operation"], step.get("parameters", {}))
                    for step in encoded)) == _semantic_key(target)
                for encoded in (result.candidate_procedures or []))
            failures.append((
                index, examples_used,
                None if result is None else result.status,
                None if result is None else result.candidate_count,
                target_present, target,
                None if result is None else result.contrastive_input,
                result.candidate_procedures if result is not None else None,
                model._examples[instruction],
            ))

    print(
        f"irreducible_depth_four_programs={PROGRAM_COUNT} seed={SEED} "
        f"max_examples={MAX_EXAMPLES}"
    )
    print(f"learned_and_generalized={PROGRAM_COUNT - len(failures)}/{PROGRAM_COUNT}")
    print(f"examples_to_unique_rule={dict(sorted(examples_to_rule.items()))}")
    print(f"contrastive_examples_used={total_contrasts}")
    if failures:
        print(f"failures={failures}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
