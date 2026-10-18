"""Check conservative modular reasoning for always-empty procedures."""

from __future__ import annotations

import itertools
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def procedure(*steps: tuple[str, dict]) -> tuple[Step, ...]:
    return tuple(Step(operation, parameters) for operation, parameters in steps)


def main() -> None:
    empty_programs = [
        procedure(("keep_odds", {}), ("keep_multiples_k", {"k": 4})),
        procedure(("keep_odds", {}), ("add_first", {}), ("keep_odds", {})),
        procedure(("keep_evens", {}), ("add_first", {}), ("keep_odds", {})),
        procedure(("keep_multiples_k", {"k": 4}), ("subtract_first", {}),
                  ("keep_odds", {})),
        procedure(("first", {}), ("add_first", {}), ("keep_odds", {})),
        procedure(("last", {}), ("add_first", {}), ("keep_odds", {})),
    ]
    target_key = _semantic_key(empty_programs[0])
    if target_key != ("always_empty",) or any(
            _semantic_key(candidate) != target_key for candidate in empty_programs):
        raise SystemExit("proved-empty procedures were not behaviorally canonicalized")

    nonempty = procedure(("keep_odds", {}), ("add_first", {}),
                         ("keep_multiples_k", {"k": 4}))
    if _semantic_key(nonempty) == target_key:
        raise SystemExit("modular abstraction merged a procedure that can return values")
    if _apply_procedure(nonempty, [1, 3]) != [4]:
        raise SystemExit("nonempty counterexample does not exercise the control rule")

    scale_last = procedure(("scale_k", {"k": -4}), ("last", {}))
    singleton_affine = [
        procedure(("last", {}), ("add_first", {}), ("scale_k", {"k": -2})),
        procedure(("last", {}), ("scale_k", {"k": -2}), ("add_first", {})),
    ]
    if any(_semantic_key(candidate) != _semantic_key(scale_last)
           for candidate in singleton_affine):
        raise SystemExit("selected singleton affine forms were not canonicalized")
    singleton_noop_forms = [
        procedure(("last", {}), ("cumulative_sum", {}),
                  ("scale_k", {"k": -4})),
        procedure(("last", {}), ("sort_by_magnitude", {}),
                  ("scale_k", {"k": -4})),
    ]
    if any(_semantic_key(candidate) != _semantic_key(scale_last)
           for candidate in singleton_noop_forms):
        raise SystemExit("singleton no-op operations remained separate programs")
    singleton_sum = procedure(("last", {}), ("sum_values", {}),
                              ("scale_k", {"k": -4}))
    if (_semantic_key(singleton_sum) == _semantic_key(scale_last)
            or _apply_procedure(singleton_sum, [])
            == _apply_procedure(scale_last, [])):
        raise SystemExit("empty-sum behavior was unsafely canonicalized")

    rng = random.Random(47)
    values = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]
    probes = [list(row) for length in range(5)
              for row in itertools.product(values, repeat=length)]
    probes.extend([[rng.randint(-40, 40) for _ in range(rng.randint(0, 12))]
                   for _ in range(500)])
    for candidate in empty_programs:
        if any(_apply_procedure(candidate, probe) for probe in probes):
            raise SystemExit(f"empty proof contradicted by a concrete list: {candidate}")

    # All-empty demonstrations do not uniquely identify a constant-empty
    # behavior. The learner should request a useful separator and abstain.
    training_inputs = [
        list(range(26)), [-11, 0], [2, -3, 2], [3, 5, -9],
        [11, -6, 4], [10, -7], [-5, -1, -6], [-2, -2, -4],
    ]
    model = CRMSModel(max_composition_depth=3, max_workers=1)
    result = None
    for values_in in training_inputs:
        result = model.teach("always empty", [(values_in, [])])
    if (result is None or result.status != "need_more_examples"
            or result.contrastive_input is None or not result.candidate_outputs
            or "always empty" in model._procedures):
        raise SystemExit(f"ambiguous empty behavior was not kept uncommitted: {result}")
    output_counts = Counter(tuple(output) for output in result.candidate_outputs)
    if (max(output_counts.values()) / len(result.candidate_outputs) > 0.90
            or len(result.contrastive_input) < 4):
        raise SystemExit(f"large ambiguity received a weak or tiny probe: {result}")
    if [] not in result.candidate_outputs:
        raise SystemExit("contrastive probe omitted the teacher's empty output")
    before = result.candidate_count
    next_result = model.teach("always empty",
                              [(result.contrastive_input, [])])
    if (next_result.status != "need_more_examples"
            or next_result.candidate_count >= before
            or "always empty" in model._procedures):
        raise SystemExit(f"teacher feedback did not reduce ambiguity safely: {next_result}")

    scalar_model = CRMSModel(max_composition_depth=3, max_workers=1)
    scalar_examples = [[1, 2, 3], list(range(27)), [0, -1]]
    for values_in in scalar_examples:
        output = [-4 * values_in[-1]] if values_in else []
        scalar_result = scalar_model.teach("scale then take last", [(values_in, output)])
    for _ in range(8):
        if scalar_result.status != "need_more_examples":
            break
        probe = scalar_result.contrastive_input
        expected = [-4 * probe[-1]] if probe else []
        if expected not in (scalar_result.candidate_outputs or []):
            raise SystemExit("contrastive probe omitted the teacher-side scalar output")
        scalar_result = scalar_model.teach(
            "scale then take last", [(probe, expected)])
    if scalar_result.status != "learned":
        raise SystemExit(f"singleton affine rule remained ambiguous: {scalar_result}")
    if scalar_model.predict("scale then take last", [3, -8, 2, 7]).output != [-28]:
        raise SystemExit("canonicalized singleton affine rule failed on a held-out list")

    print("empty filter composition diagnostic: PASS")
    print("sound modular proof, nonempty guard, honest abstention, bounded useful long probe, singleton affine canonicalization: PASS")


if __name__ == "__main__":
    main()
