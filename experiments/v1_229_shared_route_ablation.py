"""Measure route-interaction safety on shared, ambiguous held-out phrases.

Unlike v1_173, this diagnostic ablates routes from the same model fixture so
it can measure whether removing one side of a route disagreement causes an
unsupported answer to leak through the router.
"""
from __future__ import annotations

import types
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


ABLATIONS = {
    "parameterized numeric": (
        "_retrieve_parameterized_procedure",
        lambda self, *_: (None, False, [], None, [])),
    "aligned phrase": (
        "_retrieve_aligned_phrase",
        lambda self, *_: (None, False, [], None)),
    "contrastive slot": (
        "_retrieve_contrastive_slot",
        lambda self, *_: (None, False, [], None)),
    "positional analogy": (
        "_retrieve_analogical_frame",
        lambda self, *_: (None, False, [], None)),
    "lexical features": (
        "_retrieve_grounded_procedure",
        lambda self, *_: (None, False, {})),
    "VSA fallback": (
        "_retrieve_vsa_candidates",
        lambda self, *_: ([], None, None)),
    "learned composition": (
        "_retrieve_learned_composition",
        lambda self, *_: (None, False, [], None)),
}


def seeded_model() -> CRMSModel:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    training_lists = ([1, 2, 3], [-3, 0, 4])
    for amount in (2, 4):
        rows = [(values, [value + amount for value in values])
                for values in training_lists]
        if model.teach(f"add {amount} to every value", rows).status != "learned":
            raise RuntimeError("numeric route fixture failed to learn")
    reverse_rows = [
        ([1, 2, 3], [3, 2, 1]),
        ([2, 8, 1], [1, 8, 2]),
        ([4, 0, -3, 9], [9, -3, 0, 4]),
    ]
    for phrase in ("add 5 to every number", "add 5 for every value",
                   "add 5 for every number"):
        if model.teach(phrase, reverse_rows).status != "learned":
            raise RuntimeError(f"aligned route fixture failed for {phrase!r}")
    return model


def main() -> None:
    query = "add 5 to every value"
    conflict_inputs = ([], [1, 2, 3], [-2, 0, 9], [0], [-3, -2, 9])
    cases = tuple((query, values, "ambiguous") for values in conflict_inputs) + (
        ("add 5 to every value now", [1, 2, 3], "abstain"),
        ("add 5 to every values", [1, 2, 3], "abstain"),
        ("add five to every value", [1, 2, 3], "abstain"),
        ("turn every value into a planet", [1, 2, 3], "abstain"),
    )
    baseline_model = seeded_model()
    for phrase, values, expected in cases:
        result = baseline_model.predict(phrase, values)
        if expected == "ambiguous":
            if (result.status != "need_examples" or result.output is not None
                    or "competing rules" not in (result.request or "")):
                raise SystemExit(f"shared-route conflict was not exposed: {result}")
        elif result.status == "ok" or result.output is not None:
            raise SystemExit(f"unsupported near-miss was answered: {result}")

    for amount in (6, 7):
        values = [-2, 0, 9]
        result = baseline_model.predict(
            f"add {amount} to every value", values)
        expected = [value + amount for value in values]
        if result.status != "ok" or result.output != expected:
            raise SystemExit(
                f"uncontested numeric value {amount} failed: {result}")
    print("full router: conflict abstained across empty, singleton, duplicate, "
          "negative, and mixed inputs; numeric values 6 and 7 transferred; "
          "near-misses abstained")
    for name, (method, replacement) in ABLATIONS.items():
        model = seeded_model()
        setattr(model, method, types.MethodType(replacement, model))
        results = [model.predict(phrase, values)
                   for phrase, values, _expected in cases]
        conflict_results = results[:len(conflict_inputs)]
        conflict_preserved = all(
            result.status == "need_examples" and result.output is None
            for result in conflict_results)
        unsupported_still_abstains = all(
            result.status != "ok" and result.output is None
            for result in results[len(conflict_inputs):])
        print(f"{name}: conflict preserved={conflict_preserved}, "
              f"unsupported abstention preserved={unsupported_still_abstains}")
        if not unsupported_still_abstains:
            raise SystemExit(f"ablating {name} caused an unsupported answer")
        if name == "parameterized numeric":
            if [result.output for result in conflict_results] != [
                    list(reversed(values)) for values in conflict_inputs]:
                raise SystemExit(
                    "without numeric evidence, aligned retrieval did not expose its competing behavior")
        elif name == "aligned phrase":
            if [result.output for result in conflict_results] != [
                    [value + 5 for value in values]
                    for values in conflict_inputs]:
                raise SystemExit(
                    "without aligned evidence, numeric retrieval did not expose its competing behavior")
        elif not conflict_preserved:
            raise SystemExit(f"unrelated route ablation erased the conflict: {name}")

    print("shared retrieval-route interaction diagnostic: PASS")


if __name__ == "__main__":
    main()
