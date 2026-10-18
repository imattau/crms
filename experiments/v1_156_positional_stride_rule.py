"""Learn and reuse numeric, ordinal positional-stride instructions."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_position_stride=5,
                      max_repeat=5)
    ambiguous_model = CRMSModel(max_composition_depth=1, max_position_stride=5)
    ambiguous = ambiguous_model.teach(
        "keep every 3rd item", [([1, 2, 3, 4, 5, 6, 7, 8], [3, 6])])
    if (ambiguous.status != "need_more_examples"
            or ambiguous.contrastive_input is None
            or len(set(tuple(row) for row in ambiguous.candidate_outputs or [])) < 2):
        raise SystemExit(f"ambiguous value/position rule did not request contrast: {ambiguous}")
    third = model.teach("keep every 3rd item", [
        ([1, 2, 3, 4, 5, 6, 7, 8], [3, 6]),
        # Distinguishes position 3,6 from values divisible by three.
        ([9, 7, 5, 3, 1, 0], [5, 0]),
    ])
    fourth = model.teach("keep every 4th item", [
        ([9, 8, 7, 6, 5, 4, 3, 2, 1], [6, 2]),
    ])
    expected = {"operation": "keep_every_kth_position", "parameters": {"k": 3}}
    expected_fourth = {"operation": "keep_every_kth_position", "parameters": {"k": 4}}
    if third.status != "learned" or third.procedure != [expected]:
        raise SystemExit(f"positional stride was not uniquely learned: {third}")
    if fourth.status != "learned" or fourth.procedure != [expected_fourth]:
        raise SystemExit(f"second stride was not uniquely learned: {fourth}")

    composed_model = CRMSModel(max_composition_depth=2,
                               max_position_stride=5)
    twice_examples = []
    for values in (
            [4, 11, 7, 2, 15, 1, 9, 6, 13, 5, 18, 3, 20, 8, 14, 12,
             17, 10, 21, 16, 22, 19, 24, 23, 26, 25, 27],
            list(range(36, 0, -1))):
        twice_examples.append((values, [values[index]
                                        for index in range(8, len(values), 9)]))
    twice = composed_model.teach("keep every third item twice", twice_examples)
    held_out_twice = composed_model.predict(
        "keep every third item twice", list(range(40, 0, -1)))
    if (twice.status != "learned" or held_out_twice.status != "ok"
            or held_out_twice.output != [32, 23, 14, 5]):
        raise SystemExit(f"composed positional strides did not transfer: {twice}, "
                         f"{held_out_twice}")

    affine_examples = []
    for values in ([4, 11, 7, 2, 15, 1, 9, 6, 13, 5, 18, 3, 20, 8, 14, 12,
                    17, 10, 21], list(range(18, 0, -1))):
        affine_examples.append((values, [2 * values[index]
                                         for index in (2, 5, 8, 11, 14, 17)]))
    affine = composed_model.teach("double each third item", affine_examples)
    held_out_affine = composed_model.predict(
        "double each third item", list(range(30, 0, -1)))
    if (affine.status != "learned" or held_out_affine.status != "ok"
            or held_out_affine.output != [56, 50, 44, 38, 32, 26, 20, 14, 8, 2]):
        raise SystemExit(f"stride/value-map composition did not transfer: "
                         f"{affine}, {held_out_affine}")

    transferred = model.predict(
        "keep every 5th item", [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110])
    if (transferred.status != "ok" or transferred.output != [50, 100]
            or transferred.procedure != [
                {"operation": "keep_every_kth_position", "parameters": {"k": 5}}]):
        raise SystemExit(f"ordinal parameter did not transfer: {transferred}")
    for phrase in ("repeat each value 5 times", "repeat each value five times"):
        repeated = model.teach(phrase, [
            ([2, 7], [2] * 5 + [7] * 5),
            ([3, -1], [3] * 5 + [-1] * 5),
        ])
        if repeated.status != "learned":
            raise SystemExit(f"numeric-word grounding example failed: {repeated}")
    for phrase, examples in (
            ("keep every 3 values", [([1, 2, 3, 4, 5, 6, 7, 8], [3, 6]),
                                     ([9, 7, 5, 3, 1, 0], [5, 0])]),
            ("keep every 4 values", [([9, 8, 7, 6, 5, 4, 3, 2, 1], [6, 2])])):
        if model.teach(phrase, examples).status != "learned":
            raise SystemExit("cardinal stride parameter examples were not learned")
    word_number = model.predict("keep every five values", list(range(1, 13)))
    if (word_number.status != "ok" or word_number.output != [5, 10]
            or word_number.procedure != [
                {"operation": "keep_every_kth_position", "parameters": {"k": 5}}]):
        raise SystemExit(f"grounded number word did not fill stride slot: {word_number}")

    ungrounded = CRMSModel(max_composition_depth=1, max_position_stride=5)
    for phrase, examples in (
            ("keep every 3 values", [([1, 2, 3, 4, 5, 6, 7, 8], [3, 6]),
                                     ([9, 7, 5, 3, 1, 0], [5, 0])]),
            ("keep every 4 values", [([9, 8, 7, 6, 5, 4, 3, 2, 1], [6, 2])])):
        if ungrounded.teach(phrase, examples).status != "learned":
            raise SystemExit("numeric stride control was not learned")
    if ungrounded.predict("keep every five values", list(range(1, 13))).status == "ok":
        raise SystemExit("unlearned number word filled a positional stride slot")

    ordinal_word_model = CRMSModel(max_composition_depth=1,
                                   max_position_stride=5)
    ordinal_three_examples = [
        ([1, 2, 3, 4, 5, 6, 7, 8], [3, 6]),
        ([9, 8, 7, 6, 5, 4, 3, 2, 1], [7, 4, 1]),
    ]
    ordinal_four_examples = [
        ([1, 2, 3, 4, 5, 6, 7, 8, 9], [4, 8]),
        ([9, 8, 7, 6, 5, 4, 3, 2, 1], [6, 2]),
    ]
    for phrase, examples in (
            ("keep every 3rd item", ordinal_three_examples),
            ("keep every third item", ordinal_three_examples),
            ("select every 3rd value", ordinal_three_examples),
            ("select every 4th value", ordinal_four_examples)):
        if ordinal_word_model.teach(phrase, examples).status != "learned":
            raise SystemExit(f"ordinal word grounding failed for {phrase!r}")
    spelled_ordinal = ordinal_word_model.predict(
        "select every third value", list(range(1, 13)))
    if (spelled_ordinal.status != "ok" or spelled_ordinal.output != [3, 6, 9, 12]
            or "keep every third item" not in (spelled_ordinal.evidence_phrases or [])):
        raise SystemExit(f"grounded ordinal word did not transfer: {spelled_ordinal}")

    ungrounded_ordinal = CRMSModel(max_composition_depth=1,
                                   max_position_stride=5)
    for phrase, examples in (
            ("select every 3rd value", ordinal_three_examples),
            ("select every 4th value", ordinal_four_examples)):
        if ungrounded_ordinal.teach(phrase, examples).status != "learned":
            raise SystemExit("numeric ordinal control example was not learned")
    if ungrounded_ordinal.predict(
            "select every third value", list(range(1, 13))).status == "ok":
        raise SystemExit("unseen spelled ordinal was treated as a built-in number")

    morphology_model = CRMSModel(max_composition_depth=1,
                                 max_position_stride=7, max_repeat=7)
    cardinal_examples = {
        4: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [value for value in range(1, 11)
                                               for _ in range(4)]),
            ([2, 5], [2, 2, 2, 2, 5, 5, 5, 5])],
        6: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [value for value in range(1, 11)
                                               for _ in range(6)]),
            ([2, 5], [2, 2, 2, 2, 2, 2, 5, 5, 5, 5, 5, 5])],
        7: [([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [value for value in range(1, 11)
                                               for _ in range(7)]),
            ([2, 5], [2, 2, 2, 2, 2, 2, 2, 5, 5, 5, 5, 5, 5, 5])],
    }
    for value, word in ((4, "four"), (6, "six"), (7, "seven")):
        for phrase in (f"repeat each value {value} times",
                       f"repeat each value {word} times"):
            if morphology_model.teach(phrase, cardinal_examples[value]).status != "learned":
                raise SystemExit(f"cardinal word grounding failed for {word}")
    for value, word in ((4, "fourth"), (6, "sixth")):
        ascending = ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                     list(range(value, 11, value)))
        descending = ([10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
                      list(range(10 - value + 1, 0, -value)))
        examples = [ascending, descending]
        for phrase in (f"select every {value}th item",
                       f"select every {word} item"):
            if morphology_model.teach(phrase, examples).status != "learned":
                raise SystemExit(f"ordinal word grounding failed for {word}")
    seventh = morphology_model.predict(
        "select every seventh item", list(range(1, 31)))
    if (seventh.status != "ok" or seventh.output != [7, 14, 21, 28]
            or not any("sixth item" in phrase
                       for phrase in seventh.evidence_phrases or [])):
        raise SystemExit(f"ordinal suffix rule did not generalize from evidence: {seventh}")
    with tempfile.TemporaryDirectory() as directory:
        morphology_path = Path(directory) / "ordinal-memory.json"
        morphology_model.save(morphology_path)
        morphology_restored = CRMSModel(
            max_composition_depth=1, max_position_stride=7, max_repeat=7)
        morphology_restored.load(morphology_path)
        restored_seventh = morphology_restored.predict(
            "select every seventh item", list(range(1, 31)))
        if restored_seventh.status != "ok" or restored_seventh.output != [7, 14, 21, 28]:
            raise SystemExit("derived ordinal form did not survive reconstruction")

    single_pair_model = CRMSModel(max_composition_depth=1,
                                  max_position_stride=7, max_repeat=7)
    for phrase in ("repeat each value 7 times", "repeat each value seven times"):
        if single_pair_model.teach(phrase, cardinal_examples[7]).status != "learned":
            raise SystemExit("single-pair cardinal control was not grounded")
    for phrase in ("select every 4th item", "select every fourth item"):
        examples = [([1, 2, 3, 4, 5, 6, 7, 8], [4, 8]),
                    ([8, 7, 6, 5, 4, 3, 2, 1], [5, 1])]
        if single_pair_model.teach(phrase, examples).status != "learned":
            raise SystemExit("single ordinal pair control was not grounded")
    if single_pair_model.predict(
            "select every seventh item", list(range(1, 31))).status == "ok":
        raise SystemExit("one ordinal pair licensed suffix generalization")
    out_of_range = model.predict("keep every 7th item", list(range(1, 15)))
    if out_of_range.status == "ok":
        raise SystemExit("stride above the configured bound was applied")
    if model._numeric_phrase_slots("keep every 3th item") is not None:
        raise SystemExit("an incorrectly suffixed ordinal became a parameter")

    # The value-based divisibility filter must remain a distinct operation.
    multiples = model.teach("keep values divisible by 3", [
        ([9, 7, 5, 3, 1, 0], [9, 3, 0]),
        ([6, 4, 3, 2, 1], [6, 3]),
    ])
    if (multiples.status != "learned"
            or multiples.procedure != [
                {"operation": "keep_multiples_k", "parameters": {"k": 3}}]):
        raise SystemExit(f"value filter was confused with positional stride: {multiples}")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rules.json"
        model.save(path)
        restored = CRMSModel(max_composition_depth=1, max_position_stride=5,
                             max_repeat=5)
        restored.load(path)
        result = restored.predict(
            "keep every 5th item", [2, 4, 6, 8, 10, 12, 14, 16, 18, 20])
        if result.status != "ok" or result.output != [10, 20]:
            raise SystemExit(f"stride rule did not survive persistence: {result}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["procedures"]["keep every 4th item"][0]["parameters"]["k"] = 6
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            restored.load(path)
        except ValueError:
            pass
        else:
            raise SystemExit("out-of-bound stored positional stride was accepted")

    print("positional stride rule diagnostic: PASS")
    print("example synthesis, ambiguity, ordinal and grounded word-number transfer, "
          "learned spelled ordinals and suffix generalization, affine/stride "
          "composition, abstention, bounds, persistence: PASS")


if __name__ == "__main__":
    main()
