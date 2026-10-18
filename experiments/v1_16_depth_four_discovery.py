"""Check the four-step behavior search with the current primitive library.

The learner receives only input/output examples. Teacher answers to requested
probes must reject the behavior at depth three and let depth four learn an
equivalent procedure that generalizes to held-out lists. A unique fit that
does not match the target is challenged with another separating input.

Run from the project root with:
    python3 experiments/v1_16_depth_four_discovery.py
"""

from __future__ import annotations

import sys
import tempfile
import random
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _apply_procedure, _contrastive_probe, _semantic_key,
)


INSTRUCTION = "select the smallest odd value then add one"
TARGET = (
    Step("keep_odds", {}),
    Step("sort_ascending", {}),
    Step("first", {}),
    Step("add_k", {"k": 1}),
)
TRAINING_INPUTS = [
    [8, 3, 1, 4, 7],
    [2, 9, -5, 6, 1],
    [11, 4, -3, 8, 5],
    [0, -7, 2, 13],
]
HELD_OUT_INPUTS = [
    [],
    [4, 9, 2, 5],
    [-10, -3, 6, 1],
    [7, 3, 11],
]


def main() -> None:
    examples = [
        (values, _apply_procedure(TARGET, values))
        for values in TRAINING_INPUTS
    ]

    def teach_to_target(model: CRMSModel, initial: list[tuple[list[int], list[int]]],
                        max_examples: int = 20):
        """Answer requested probes; challenge any learned wrong behavior."""
        examples_used = len(initial)
        result = model.teach(INSTRUCTION, initial)
        while examples_used < max_examples:
            procedure = model._procedures.get(INSTRUCTION)
            if (result.status == "learned" and procedure is not None
                    and _semantic_key(procedure) == _semantic_key(TARGET)):
                break
            if result.status == "need_more_examples":
                probe = result.contrastive_input
                outputs = result.candidate_outputs
                if probe is None or outputs is None:
                    # The teacher can supply a contrast between the target
                    # and any retained candidate when the bounded generic
                    # probe search finds none. This still tests the learner's
                    # complete candidate set and subsequent version-space
                    # filtering; no answer is inferred from the target.
                    candidates = [
                        tuple(Step(step["operation"], step.get("parameters", {}))
                              for step in procedure)
                        for procedure in (result.candidate_procedures or [])
                    ]
                    target_in_space = any(
                        _semantic_key(candidate) == _semantic_key(TARGET)
                        for candidate in candidates)
                    if (not target_in_space
                            and model.max_composition_depth >= len(TARGET)):
                        raise RuntimeError(
                            "complete candidate set omitted the demonstrated target"
                        )
                    separating = None
                    for candidate in candidates:
                        if _semantic_key(candidate) == _semantic_key(TARGET):
                            continue
                        candidate_probe, candidate_outputs = _contrastive_probe(
                            [TARGET, candidate])
                        if (candidate_probe is not None
                                and candidate_outputs is not None
                                and len({tuple(output) for output in candidate_outputs}) > 1):
                            separating = (candidate_probe, candidate_outputs)
                        else:
                            # If the model's generic probe domain missed a
                            # distinction, let the teacher search a wider
                            # deterministic domain for a real counterexample.
                            rng = random.Random(116 + examples_used)
                            for _ in range(2_000):
                                values = [rng.randint(-100, 100)
                                          for _ in range(rng.randint(0, 12))]
                                target_output = _apply_procedure(TARGET, values)
                                candidate_output = _apply_procedure(candidate, values)
                                if target_output != candidate_output:
                                    separating = (
                                        values, [target_output, candidate_output])
                                    break
                        if separating is not None:
                            break
                    if separating is None:
                        break
                    probe, outputs = separating
                expected = _apply_procedure(TARGET, probe)
                if (len({tuple(output) for output in outputs}) < 2
                        or (expected not in outputs
                            and model.max_composition_depth >= len(TARGET))):
                    raise RuntimeError(
                        f"learner or teacher returned an invalid contrastive probe: {probe}"
                    )
            elif result.status == "learned" and procedure is not None:
                # A unique fit can still be the wrong general rule. Ask for
                # an input that separates it from the intended procedure.
                probe, outputs = _contrastive_probe([TARGET, procedure])
                if (probe is None or outputs is None
                        or len({tuple(output) for output in outputs}) < 2):
                    break
                expected = _apply_procedure(TARGET, probe)
                if (expected not in outputs
                        and model.max_composition_depth >= len(TARGET)):
                    raise RuntimeError(
                        f"target output missing from corrective probe: {probe}"
                    )
            else:
                break
            result = model.teach(
                INSTRUCTION, [(probe, expected)])
            examples_used += 1
        return result, examples_used

    depth_three = CRMSModel(max_composition_depth=3, max_workers=1)
    limited, depth_three_examples = teach_to_target(depth_three, examples)
    depth_three_rejects = limited.status == "no_fit"

    with tempfile.TemporaryDirectory() as temporary_directory:
        memory_path = Path(temporary_directory) / "depth_four_memory.json"
        depth_four = CRMSModel(memory_path, max_composition_depth=4, max_workers=1)
        started = perf_counter()
        learned, depth_four_examples = teach_to_target(depth_four, examples)
        elapsed = perf_counter() - started
        reloaded = CRMSModel(memory_path, max_composition_depth=4, max_workers=1)

        procedure = reloaded._procedures.get(INSTRUCTION)
        behavior_matches = (
            learned.status == "learned"
            and procedure is not None
            and _semantic_key(procedure) == _semantic_key(TARGET)
        )
        held_out_matches = behavior_matches and all(
            reloaded.predict(INSTRUCTION, values).output
            == _apply_procedure(TARGET, values)
            for values in HELD_OUT_INPUTS
        )
    search_steps = len(depth_four._steps)

    print(
        f"depth_three={limited.status} after {depth_three_examples} examples; "
        f"depth_four={learned.status}, candidates={learned.candidate_count}, "
        f"examples={depth_four_examples}, "
        f"equivalent={behavior_matches}, held_out="
        f"{'PASS' if held_out_matches else 'FAIL'}, "
        f"search_steps={search_steps}, search_seconds={elapsed:.2f}"
    )
    if not behavior_matches:
        print(f"remaining_candidates={learned.candidate_procedures}")
    if not (depth_three_rejects and behavior_matches and held_out_matches):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
