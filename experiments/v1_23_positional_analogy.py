"""Check symbolic analogical completion across disjoint grounded vocabulary.

The model gets separately taught phrases and examples only. It may recombine
token roles that recur in multiple independent phrase contexts when they map
to one learned procedure, but must abstain if more than one procedure frame
supports the query. No synonym table, embedding, or preloaded linguistic
knowledge is used.

Run from the project root with:
    python3 experiments/v1_23_positional_analogy.py
"""

from __future__ import annotations

import sys
from tempfile import TemporaryDirectory
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


REVERSE = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
SORT = [([3, -1, 5], [-1, 3, 5]), ([8, 2, 0, 6], [0, 2, 6, 8]),
        ([-4, 2], [-4, 2])]
REVERSE_FRAME = [
    ("reverse the list", REVERSE),
    ("reverse the values", REVERSE),
    ("turn the array", REVERSE),
    ("flip the array", REVERSE),
    ("reverse the items", SORT),
    ("sort the array", SORT),
]


def teach_all(model: CRMSModel, cases: list[tuple[str, list]]) -> None:
    for phrase, examples in cases:
        result = model.teach(phrase, examples)
        if result.status != "learned":
            raise RuntimeError(f"could not ground {phrase!r}: {result.status}")


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    teach_all(model, REVERSE_FRAME)

    queries = ("reverse the array",)
    held_out = ([], [9, 1, 3], [-4, 0, 12, 7])
    expected = ([], [3, 1, 9], [7, 12, 0, -4])
    predictions = [model.predict(query, values)
                   for query in queries for values in held_out]
    transfer_ok = all(
        prediction.status == "ok" and prediction.output == output
        for query_offset in range(len(queries))
        for prediction, output in zip(
            predictions[query_offset * len(held_out):
                        (query_offset + 1) * len(held_out)], expected)
    )
    prediction = model.predict(queries[0], [9, 1, 3])
    evidence_ok = {"reverse the list", "reverse the values", "turn the array",
                   "flip the array"} <= set(prediction.evidence_phrases or ())
    template_ok = bool(prediction.matched_templates) and prediction.matched_templates[0].startswith(
        "analogy_frame:")
    print(
        f"disjoint-vocabulary frame transfer: {prediction.status}:{prediction.output}; "
        f"all_held_out={transfer_ok}; evidence={evidence_ok}; "
        f"template={template_ok}; "
        f"{'PASS' if transfer_ok and evidence_ok and template_ok else 'FAIL'}"
    )

    with TemporaryDirectory() as temporary:
        memory_path = Path(temporary) / "memory.json"
        persisted = CRMSModel(memory_path, max_composition_depth=1,
                              max_workers=1)
        teach_all(persisted, REVERSE_FRAME)
        restored = CRMSModel(memory_path, max_composition_depth=1,
                             max_workers=1)
        after_load = restored.predict("reverse the array", [9, 1, 3])
        reload_ok = (after_load.status == "ok"
                     and after_load.output == [3, 1, 9]
                     and after_load.matched_templates == prediction.matched_templates)
        restored.forget("reverse the values")
        after_forget = restored.predict("reverse the array", [9, 1, 3])
        invalidation_ok = after_forget.status == "need_examples"
    print(
        f"frame after reload: {after_load.status}:{after_load.output}; "
        f"forget support: {after_forget.status}; "
        f"{'PASS' if reload_ok and invalidation_ok else 'FAIL'}"
    )

    induced = CRMSModel(max_composition_depth=1, max_workers=1)
    teach_all(induced, REVERSE_FRAME)
    narrowed = induced.teach("reverse the array", [REVERSE[0]])
    analogy_narrows_induction = (
        narrowed.status == "learned"
        and narrowed.procedure == [{"operation": "reverse", "parameters": {}}]
        and set(narrowed.evidence_phrases or ()) == {
            "reverse the list", "reverse the values", "turn the array",
            "flip the array",
        }
    )
    corrected = CRMSModel(max_composition_depth=1, max_workers=1)
    teach_all(corrected, REVERSE_FRAME)
    contradictory_prior = corrected.teach("reverse the array", SORT)
    teacher_evidence_wins = (
        contradictory_prior.status == "learned"
        and contradictory_prior.procedure == [
            {"operation": "sort_ascending", "parameters": {}}
        ]
        and not contradictory_prior.evidence_phrases
    )
    print(
        f"analogy-assisted induction: {narrowed.status}; "
        f"contrasting examples: {contradictory_prior.status}; "
        f"{'PASS' if analogy_narrows_induction and teacher_evidence_wins else 'FAIL'}"
    )

    insufficient = CRMSModel(max_composition_depth=1, max_workers=1)
    teach_all(insufficient, [("reverse the list", REVERSE),
                             ("invert the sequence", REVERSE)])
    unsupported_before_second_frame = insufficient.predict(
        "invert the list", [9, 1, 3])
    under_supported = unsupported_before_second_frame.status == "need_examples"
    unknown_role = model.predict("reverse the sequence", [9, 1, 3])
    unknown_abstains = unknown_role.status == "need_examples"

    ambiguous = CRMSModel(max_composition_depth=1, max_workers=1)
    teach_all(ambiguous, [
        ("flarn the gadget", REVERSE),
        ("flarn the thing", REVERSE),
        ("blort the widget", REVERSE),
        ("zint the widget", REVERSE),
        ("flarn the item", SORT),
        ("flarn the object", SORT),
        ("sort the widget", SORT),
        ("arrange the widget", SORT),
    ])
    competing = ambiguous.predict("flarn the widget", [3, -1, 5])
    ambiguity_abstains = competing.status == "need_examples"
    print(
        f"one grounded phrase: {unsupported_before_second_frame.status}; "
        f"unknown role value: {unknown_role.status}; "
        f"competing frames: {competing.status}; "
        f"{'PASS' if under_supported and unknown_abstains and ambiguity_abstains else 'FAIL'}"
    )
    if not (transfer_ok and evidence_ok and template_ok and reload_ok
            and invalidation_ok and analogy_narrows_induction
            and teacher_evidence_wins and under_supported
            and unknown_abstains and ambiguity_abstains):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
