"""Ensure learned composition participates in cross-route conflict checks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "experiments")]

from crms_model import CRMSModel
from v1_21_learned_sequence_connective import ATOMS, COMPOUNDS


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, examples in ATOMS:
        if model.teach(phrase, examples).status != "learned":
            raise SystemExit(f"atomic rule fixture failed: {phrase}")
    for phrase, examples in COMPOUNDS:
        if model.teach(phrase, examples).status != "learned":
            raise SystemExit(f"sequence connective fixture failed: {phrase}")

    # These phrases share a positional language frame and all demonstrate
    # reversal, while composition independently supports sort-then-add.
    model.max_composition_depth = 1
    reverse_examples = [
        ([1, 2, 3], [3, 2, 1]),
        ([3, 7, -2], [-2, 7, 3]),
        ([8, 0, 4], [4, 0, 8]),
    ]
    for phrase in (
            "sort the list and then add one to numbers",
            "sort the list and then add two to values",
            "reverse the list and then add two to values",
            "reverse the array and then add one to numbers"):
        if model.teach(phrase, reverse_examples).status != "learned":
            raise SystemExit(f"positional analogy fixture failed: {phrase}")
    model.max_composition_depth = 2

    query = "sort the list and then add one to values"
    composition, composition_conflict, composition_sources, _template = (
        model._retrieve_learned_composition(query))
    analogy, analogy_conflict, analogy_sources, _analogy_template = (
        model._retrieve_analogical_frame(query))
    if (composition is None or composition_conflict
            or tuple(step.operation for step in composition)
            != ("sort_ascending", "add_k")
            or analogy is None or analogy_conflict
            or tuple(step.operation for step in analogy) != ("reverse",)):
        raise SystemExit(
            "fixture did not produce distinct composition and analogy candidates")

    for values in ([3, 1, 2], [], [-4, 9, 0], [0], [5, -2, 5]):
        result = model.predict(query, values)
        if (result.status != "need_examples" or result.output is not None
                or "competing rules" not in (result.request or "")
                or result.contrastive_input is None
                or result.candidate_outputs is None
                or len({tuple(output) for output in result.candidate_outputs}) < 2
                or not set(composition_sources + analogy_sources)
                <= set(result.evidence_phrases or ())):
            raise SystemExit(
                f"conflicting composition and analogy were not surfaced: {result}")

    print("learned composition vs positional analogy conflict: PASS")
    print("five held-out inputs, contrastive output probe, and combined provenance: PASS")


if __name__ == "__main__":
    main()
