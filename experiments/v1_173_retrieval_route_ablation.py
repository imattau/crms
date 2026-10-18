"""Ablate representative learned instruction-retrieval routes.

Each route is tested on fixed held-out phrase/input pairs. This controlled
multi-example diagnostic estimates route contribution on these fixtures, not
across the full experiment corpus.
"""
from __future__ import annotations

import sys
import types
from random import Random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "experiments")]

from crms_model import CRMSModel
import v1_15_learned_optional_word_diagnostic as optional_span
import v1_21_learned_sequence_connective as sequence_connective
import v1_23_positional_analogy as analogy
import v1_101_contrastive_instruction_slots as contrastive_slot


def repeat(xs: list[int], k: int) -> list[int]:
    return [x for x in xs for _ in range(k)]


def heldout_lists(seed: int, count: int = 32) -> list[list[int]]:
    """Fixed varied lists, including empty and singleton boundary cases."""
    rng = Random(seed)
    values = [[], [rng.randint(-20, 20)]]
    while len(values) < count:
        width = rng.randint(2, 10)
        candidate = [rng.randint(-50, 50) for _ in range(width)]
        if candidate not in values:
            values.append(candidate)
    return values


def expand_cases(name: str, cases: list[tuple[str, list[int], list[int]]]):
    """Replace a few illustrative inputs with a fixed transfer corpus."""
    if name == "parameterized numeric":
        cases = [("repeat each value 5 times", xs, repeat(xs, 5))
                 for xs in heldout_lists(1731)]
        cases.extend(("add 5 to each value", xs,
                      [value + 5 for value in xs])
                     for xs in heldout_lists(1739))
        cases.extend(("rotate the list left 3", xs,
                      (xs[3 % len(xs):] + xs[:3 % len(xs)]) if xs else [])
                     for xs in heldout_lists(1740))
        return cases
    if name in {"aligned phrase", "positional analogy"}:
        phrase = "turn values" if name == "aligned phrase" else "reverse the array"
        return [(phrase, xs, list(reversed(xs))) for xs in heldout_lists(1732)]
    if name == "contrastive slot":
        result = []
        for phrase, operation, seed in (
                ("remove the first element", lambda xs: xs[1:], 1733),
                ("delete the last item", lambda xs: xs[:-1], 1734)):
            result.extend((phrase, xs, operation(xs))
                          for xs in heldout_lists(seed))
        return result
    if name == "lexical features":
        result = []
        for phrase, seed in (("reverse list", 1735),
                             ("please reverse quickly list", 1736)):
            result.extend((phrase, xs, list(reversed(xs)))
                          for xs in heldout_lists(seed, count=16))
        return result
    if name == "VSA fallback":
        return [("reverse list", xs, list(reversed(xs)))
                for xs in heldout_lists(1737)]
    if name == "learned composition":
        return [("sort the list and then add one to values", xs,
                 [value + 1 for value in sorted(xs)])
                for xs in heldout_lists(1738)]
    raise ValueError(name)


def fixture(name: str):
    if name == "parameterized numeric":
        model = CRMSModel(max_composition_depth=1, max_workers=1, max_repeat=5,
                          max_add=10, max_rotation=4)
        training_lists = ([1, 2], [-3, 4], [0, 5, 6], [], [-10])
        for k in (3, 4):
            examples = [(xs, repeat(xs, k)) for xs in training_lists]
            if model.teach(f"repeat each value {k} times", examples).status != "learned":
                raise RuntimeError("numeric fixture failed to learn")
        for k in (3, 7):
            examples = [(xs, [value + k for value in xs])
                        for xs in training_lists]
            if model.teach(f"add {k} to each value", examples).status != "learned":
                raise RuntimeError("numeric addition fixture failed to learn")
        for k in (1, 2):
            examples = []
            for xs in ([10, 11, 12, 13], [10, 11, 12, 13, 14]):
                rotated = xs[k:] + xs[:k]
                examples.append((xs, rotated))
            if model.teach(f"rotate the list left {k}", examples).status != "learned":
                raise RuntimeError("numeric rotation fixture failed to learn")
        return model, [], "_retrieve_parameterized_procedure"
    if name == "aligned phrase":
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase in optional_span.PHRASES:
            if model.teach(phrase, optional_span.EXAMPLES).status != "learned":
                raise RuntimeError("aligned fixture failed to learn")
        cases = [("turn values", xs, list(reversed(xs)))
                 for xs in ([-1, 2, 9], [], [8, 4])]
        return model, cases, "_retrieve_aligned_phrase"
    if name == "contrastive slot":
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        for phrase, op in contrastive_slot.TRAINING:
            contrastive_slot.teach(model, phrase, op)
        cases = [
            ("remove the first element", [3, 9, 1, 7], [9, 1, 7]),
            ("remove the first element", [], []),
            ("delete the last item", [3, 9, 1, 7], [3, 9, 1]),
        ]
        return model, cases, "_retrieve_contrastive_slot"
    if name == "positional analogy":
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        analogy.teach_all(model, analogy.REVERSE_FRAME)
        cases = [("reverse the array", xs, list(reversed(xs)))
                 for xs in ([9, 1, 3], [], [-4, 0, 12, 7])]
        return model, cases, "_retrieve_analogical_frame"
    if name == "lexical features":
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        examples = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
        phrases = (
            "reverse list today", "reverse list now",
            "please reverse the collection today",
            "please reverse this array now",
            "reverse quickly each item today",
            "reverse quickly every item now",
            "sort quickly list things today",
            "flip quickly list items now",
        )
        for phrase in phrases:
            if model.teach(phrase, examples).status != "learned":
                raise RuntimeError("lexical fixture failed to learn")
        lists = ([9, 1, 3], [], [8, -3, 2, 0])
        cases = [("reverse list", xs, list(reversed(xs))) for xs in lists]
        cases += [("please reverse quickly list", xs, list(reversed(xs)))
                  for xs in lists]
        return model, cases, "_retrieve_grounded_procedure"
    if name == "VSA fallback":
        model = CRMSModel(max_composition_depth=1, max_workers=1)
        examples = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
        for phrase in ("reverse the list", "reverse the array"):
            if model.teach(phrase, examples).status != "learned":
                raise RuntimeError("VSA fixture failed to learn")
        cases = [("reverse list", xs, list(reversed(xs)))
                 for xs in ([9, 1, 3], [], [8, -3, 2, 0])]
        return model, cases, "_retrieve_vsa_candidates"
    if name == "learned composition":
        model = sequence_connective.train()
        cases = [("sort the list and then add one to values", xs,
                  [x + 1 for x in sorted(xs)])
                 for xs in ([3, 1, 2], [], [-4, 9, 0])]
        return model, cases, "_retrieve_learned_composition"
    raise ValueError(name)


def main() -> None:
    names = ("parameterized numeric", "aligned phrase", "contrastive slot",
             "positional analogy", "lexical features", "VSA fallback",
             "learned composition")
    load_bearing = 0
    total = 0
    for name in names:
        model, seed_cases, method = fixture(name)
        cases = expand_cases(name, seed_cases)
        for phrase, xs, expected in cases:
            baseline = model.predict(phrase, xs)
            if baseline.status != "ok" or baseline.output != expected:
                raise SystemExit(f"baseline {name} failed: {baseline}")
            if name == "lexical features":
                marked = bool(baseline.matched_tokens or baseline.matched_bigrams)
            elif name == "VSA fallback":
                marked = bool(baseline.matched_templates and
                              baseline.matched_templates[0].startswith("vsa:"))
            else:
                marked = bool(baseline.matched_templates)
            if not marked:
                raise SystemExit(f"baseline was not attributed to {name}: {baseline}")

        if method == "_retrieve_parameterized_procedure":
            replacement = lambda self, *_: (None, False, [], None, [])
        elif method == "_retrieve_grounded_procedure":
            replacement = lambda self, *_: (None, False, {})
        elif method == "_retrieve_vsa_candidates":
            replacement = lambda self, *_: ([], None, None)
        else:
            replacement = lambda self, *_: (None, False, [], None)
        setattr(model, method, types.MethodType(replacement, model))
        correct = 0
        answered = 0
        wrong_answers = 0
        abstentions = 0
        ambiguous = 0
        attributed = 0
        for phrase, xs, expected in cases:
            result = model.predict(phrase, xs)
            is_answered = result.status == "ok"
            is_correct = is_answered and result.output == expected
            answered += is_answered
            correct += is_correct
            wrong_answers += is_answered and not is_correct
            abstentions += not is_answered
            ambiguous += result.status == "need_more_examples"
            attributed += is_answered and bool(
                result.evidence_phrases or result.matched_tokens
                or result.matched_bigrams or result.matched_templates)
        total += len(cases)
        load_bearing += len(cases) - correct
        print(f"{name}: after ablation: correct={correct}/{len(cases)}, "
              f"coverage={answered}/{len(cases)}, wrong={wrong_answers}, "
              f"abstained={abstentions} (ambiguous={ambiguous}), "
              f"answered with evidence attribution={attributed}/{len(cases)}")

    exact = CRMSModel(max_composition_depth=1, max_workers=1)
    examples = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
    exact.teach("reverse the list", examples)
    present = exact.predict("reverse the list", [9, 1, 3])
    exact.forget("reverse the list")
    absent = exact.predict("reverse the list", [9, 1, 3])
    if present.output != [3, 1, 9] or absent.status == "ok":
        raise SystemExit("exact phrase memory ablation failed")
    print("exact phrase memory: load-bearing")
    print(f"route-dependent predictions: {load_bearing}/{total} "
          f"across {total} fixed held-out phrase/input pairs")


if __name__ == "__main__":
    main()
