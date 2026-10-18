"""Check rotation/duplication discovery and their exactness boundaries.

CRMS should infer cyclic offsets from demonstrations, request a probe when
short examples leave offsets aliased, transfer a numeric phrase slot, and
preserve conservative behavior when rotation interacts with filtering or
repeated runs.

Run from the project root with:
    python3 experiments/v1_24_rotation_rule_discovery.py
"""

from __future__ import annotations

import sys
from tempfile import TemporaryDirectory
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure, _semantic_key


def rotated(values: list[int], offset: int) -> list[int]:
    return _apply_procedure((Step("rotate_left_k", {"k": offset}),), values)


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1, max_rotation=4)
    phrase = "rotate the list left"
    first_input = [1, 2, 3, 4]
    first = model.teach(phrase, [(first_input, rotated(first_input, 1))])
    probe = first.contrastive_input
    probe_separates_offsets = (
        first.status == "need_more_examples"
        and probe is not None
        and first.candidate_outputs is not None
        and len(set(map(tuple, first.candidate_outputs))) > 1
    )
    if not probe_separates_offsets:
        raise RuntimeError("one rotation example did not request a separating probe")

    learned = model.teach(phrase, [(probe, rotated(probe, 1))])
    held_out = ([], [7], [9, -1, 4], [2, 8, -3, 5, 1, 6])
    generalizes = (
        learned.status == "learned"
        and learned.procedure == [{"operation": "rotate_left_k", "parameters": {"k": 1}}]
        and all(model.predict(phrase, values).output == rotated(values, 1)
                for values in held_out)
    )
    print(
        f"offset discovery: {learned.status}; probe={probe}; "
        f"held_out={generalizes}; {'PASS' if generalizes else 'FAIL'}"
    )
    with TemporaryDirectory() as temporary:
        memory_path = Path(temporary) / "rotation-memory.json"
        model.save(memory_path)
        restored = CRMSModel(memory_path, max_composition_depth=1,
                             max_workers=1, max_rotation=4)
        after_load = restored.predict(phrase, [9, -1, 4])
        persistence = (after_load.status == "ok"
                      and after_load.output == rotated([9, -1, 4], 1))
        widened = CRMSModel(memory_path, max_composition_depth=1,
                            max_workers=1, max_rotation=5)
        widening_checked = (
            widened.max_rotation == 5
            and widened.predict(phrase, [9, -1, 4]).output
            == rotated([9, -1, 4], 1))
        try:
            CRMSModel(memory_path, max_composition_depth=1, max_workers=1,
                      max_rotation=3)
        except ValueError:
            configuration_checked = True
        else:
            configuration_checked = False
    print(
        f"rotation persistence={persistence}; widening={widening_checked}; "
        f"narrowing rejected={configuration_checked}; "
        f"{'PASS' if persistence and widening_checked and configuration_checked else 'FAIL'}"
    )

    # Literal numeric slots should map to the same explicit operation family.
    parameterized = CRMSModel(max_composition_depth=1, max_workers=1,
                              max_rotation=4)
    for offset, lengths in ((1, (4, 5)), (2, (5, 6))):
        examples = []
        for length in lengths:
            values = list(range(10, 10 + length))
            examples.append((values, rotated(values, offset)))
        result = parameterized.teach(f"rotate the list left {offset}", examples)
        if result.status != "learned":
            raise RuntimeError(f"could not learn offset {offset}: {result.status}")
    query = parameterized.predict("rotate the list left 3", [9, 1, 3, 5, 7])
    slot_transfer = (
        query.status == "ok"
        and query.output == [5, 7, 9, 1, 3]
        and query.procedure == [{"operation": "rotate_left_k", "parameters": {"k": 3}}]
        and query.matched_templates == ["rotate the list left <number>"]
    )
    print(
        f"grounded numeric offset transfer: {query.status}:{query.output}; "
        f"{'PASS' if slot_transfer else 'FAIL'}"
    )

    # Reorder-only rotation algebra has exact canonical equivalences.
    double_rotation = (
        Step("rotate_left_k", {"k": 1}),
        Step("rotate_left_k", {"k": 1}),
    )
    offset_two = (Step("rotate_left_k", {"k": 2}),)
    reverse_then_rotate = (
        Step("reverse", {}), Step("rotate_left_k", {"k": 1}),
    )
    rotate_then_reverse = (
        Step("rotate_left_k", {"k": -1}), Step("reverse", {}),
    )
    # Cyclic endpoints at offsets 0 and -1 are exactly the ordinary first
    # and last elements, including singleton and empty-list behavior.
    cyclic_first = (
        Step("rotate_left_k", {"k": -1}), Step("first", {}),
    )
    ordinary_last = (Step("last", {}),)
    repeated_filter_after_rotation = (
        Step("keep_evens", {}), Step("rotate_left_k", {"k": -2}),
        Step("keep_evens", {}),
    )
    filtered_rotation = (
        Step("keep_evens", {}), Step("rotate_left_k", {"k": -2}),
    )
    duplicate_then_reverse = (
        Step("duplicate_each", {}), Step("reverse", {}),
    )
    reverse_then_duplicate = (
        Step("reverse", {}), Step("duplicate_each", {}),
    )
    duplicate_then_filter = (
        Step("duplicate_each", {}), Step("keep_evens", {}),
    )
    filter_then_duplicate = (
        Step("keep_evens", {}), Step("duplicate_each", {}),
    )
    duplicate_then_select = (
        Step("duplicate_each", {}), Step("first", {}),
    )
    rotate_copied = (
        Step("duplicate_each", {}), Step("rotate_left_k", {"k": 1}),
    )
    duplicate_reorder = (
        Step("rotate_left_k", {"k": 1}), Step("duplicate_each", {}),
    )
    phased_rotation = (
        Step("duplicate_each", {}), Step("rotate_left_k", {"k": -3}),
    )
    equivalent_phased_rotation = (
        Step("rotate_left_k", {"k": -2}), Step("duplicate_each", {}),
        Step("rotate_left_k", {"k": 1}),
    )
    repeat_algebra = (
        _semantic_key(duplicate_then_reverse)
        == _semantic_key(reverse_then_duplicate)
        and _semantic_key(duplicate_then_filter)
        == _semantic_key(filter_then_duplicate)
        and _semantic_key(duplicate_then_select)
        == _semantic_key((Step("first", {}),))
        and _semantic_key(phased_rotation)
        == _semantic_key(equivalent_phased_rotation)
        and _semantic_key(rotate_copied) != _semantic_key(duplicate_reorder)
        and _apply_procedure(rotate_copied, [1, 2, 3])
        != _apply_procedure(duplicate_reorder, [1, 2, 3])
    )
    reorder_algebra = (
        _semantic_key(double_rotation) == _semantic_key(offset_two)
        and _semantic_key(reverse_then_rotate) == _semantic_key(rotate_then_reverse)
        and _semantic_key(cyclic_first) == _semantic_key(ordinary_last)
        and _semantic_key(repeated_filter_after_rotation)
        == _semantic_key(filtered_rotation)
        and repeat_algebra
    )

    # Filtering can change the position represented by a prior rotation.
    # Preserve a conservative distinction rather than merging these programs.
    rotate_then_filter = (
        Step("rotate_left_k", {"k": 1}), Step("keep_evens", {}),
    )
    filter_then_rotate = (
        Step("keep_evens", {}), Step("rotate_left_k", {"k": 1}),
    )
    ordering_interaction = (
        _semantic_key(rotate_then_filter) != _semantic_key(filter_then_rotate)
        and _apply_procedure(rotate_then_filter, [1, 2, 3, 4, 5])
        != _apply_procedure(filter_then_rotate, [1, 2, 3, 4, 5])
    )
    print(
        f"reorder canonicalization={reorder_algebra}; "
        f"duplicate canonicalization={repeat_algebra}; "
        f"operation_count={len(model._steps)}; "
        f"filter-order distinction={ordering_interaction}; "
        f"{'PASS' if reorder_algebra and ordering_interaction else 'FAIL'}"
    )
    if not (generalizes and persistence and configuration_checked
            and slot_transfer and reorder_algebra
            and ordering_interaction):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
