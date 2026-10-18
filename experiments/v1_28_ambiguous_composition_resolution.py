"""Check contrastive ambiguity handling for endpoint scaling and empty rules.

Run from the project root with:
    python3 experiments/v1_28_ambiguous_composition_resolution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _contrastive_probe


def main() -> None:
    probe_candidates = [
        (Step("last", {}),),
        (Step("first", {}),),
        (Step("rotate_left_k", {"k": 2}), Step("last", {})),
    ]
    short_probe, short_outputs = _contrastive_probe(probe_candidates)
    if (short_probe is None or len(short_probe) != 3
            or len({tuple(output) for output in short_outputs or []}) != 3):
        raise SystemExit(f"probe did not prefer the shortest full split: {short_probe}")

    scaled_last = (Step("scale_k", {"k": -4}), Step("last", {}))
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    lists = [[1, 2, 9], [4, -7, 3, 11], [-8, 6, 5],
             [-1, 10, 2, 7, 13]]
    learned = model.teach(
        "multiply the last value by negative four",
        [(values, _apply_procedure(scaled_last, values)) for values in lists],
    )
    if learned.status != "learned":
        raise SystemExit(f"scale-then-last remained ambiguous: {learned}")
    for values in ([], [3], [5, -2, 8], [-9, 4, 0, 12]):
        expected = _apply_procedure(scaled_last, values)
        if model.predict("multiply the last value by negative four", values).output != expected:
            raise SystemExit(f"scaled endpoint failed on {values}")

    always_empty = (
        Step("keep_odds", {}), Step("keep_multiples_k", {"k": 4}),
    )
    empty_model = CRMSModel(max_composition_depth=2, max_workers=1)
    examples = [[1, 2, 3, 4], [0, 5, -2, 7], [3, 9, 12], [-4, -1, 6]]
    result = empty_model.teach(
        "keep odd multiples of four",
        [(values, _apply_procedure(always_empty, values)) for values in examples],
    )
    if (result.status != "need_more_examples"
            or result.contrastive_input is None
            or [] not in (result.candidate_outputs or [])
            or "keep odd multiples of four" in empty_model._procedures):
        raise SystemExit(f"empty-rule ambiguity was not surfaced: {result}")
    previous_count = result.candidate_count
    # Feed the requested contrastive input. New feedback may shrink the
    # candidate set without identifying one procedure; stay review-only.
    for _ in range(3):
        if result.contrastive_input is None:
            break
        result = empty_model.teach(
            "keep odd multiples of four", [(result.contrastive_input, [])])
        if (result.status != "need_more_examples"
                or result.candidate_count >= previous_count
                or "keep odd multiples of four" in empty_model._procedures):
            raise SystemExit(
                f"empty-rule feedback did not safely reduce ambiguity: {result}")
        previous_count = result.candidate_count
    if result.contrastive_input is not None:
        raise SystemExit(f"probe budget should stop rather than imply certainty: {result}")
    held_out = ([], [0], [1, 2, 3], [-7, -4, 0, 8, 11])
    if any(empty_model.predict("keep odd multiples of four", values).status
           not in {"need_more_examples", "need_examples"}
           for values in held_out):
        raise SystemExit("ambiguous empty rule was applied without unique support")

    print("ambiguous composition resolution: PASS")
    print("short contrast, scaled endpoint generalization, iterative ambiguity reduction, and no false empty-rule commit: PASS")


if __name__ == "__main__":
    main()
