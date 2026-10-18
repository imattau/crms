"""Check exact canonicalization of modular filters with sorted extrema."""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import Step, _apply_procedure, _semantic_key


def main() -> None:
    filters = (Step("keep_odds", {}), Step("keep_multiples_k", {"k": 3}))
    affine = (Step("double", {}), Step("add_k", {"k": 2}))
    aliases = []
    for order in itertools.permutations(filters + (Step("sort_ascending", {}),)):
        aliases.append(order + (Step("first", {}),) + affine)
    for order in itertools.permutations(filters + (Step("sort_descending", {}),)):
        aliases.append(order + (Step("last", {}),) + affine)

    # Affine maps may move across the endpoint selector after filtering. A
    # filter following a translation instead becomes a predicate on the
    # original residue class.
    alias_groups = [
        aliases,
        [
            (Step("sort_ascending", {}), Step("keep_odds", {}),
             Step("first", {}), Step("scale_k", {"k": -2}),
             Step("add_k", {"k": 1})),
            (Step("sort_descending", {}), Step("keep_odds", {}),
             Step("scale_k", {"k": -2}), Step("add_k", {"k": 1}),
             Step("last", {})),
        ],
        [
            (Step("keep_evens", {}), Step("sort_ascending", {}),
             Step("first", {}), Step("add_k", {"k": 1})),
            (Step("add_k", {"k": 1}), Step("keep_odds", {}),
             Step("sort_ascending", {}), Step("first", {})),
        ],
    ]

    for group in alias_groups:
        expected_key = _semantic_key(group[0])
        if any(_semantic_key(procedure) != expected_key for procedure in group):
            raise SystemExit("commuting filters/sort/extremum aliases stayed distinct")

    probes = [list(values) for length in range(5)
              for values in itertools.product(range(-3, 4), repeat=length)]
    for group in alias_groups:
        for values in probes:
            expected = _apply_procedure(group[0], values)
            if any(_apply_procedure(procedure, values) != expected
                   for procedure in group):
                raise SystemExit(f"canonical alias differed on {values}")

    cancelled_rotation = (
        Step("rotate_left_k", {"k": -4}),
        Step("rotate_left_k", {"k": 4}),
        Step("keep_less_than_first", {}), Step("last", {}),
    )
    direct_relative = (Step("keep_less_than_first", {}), Step("last", {}))
    if _semantic_key(cancelled_rotation) != _semantic_key(direct_relative):
        raise SystemExit("cancelled rotations were not simplified before relational selection")
    for values in probes:
        if (_apply_procedure(cancelled_rotation, values)
                != _apply_procedure(direct_relative, values)):
            raise SystemExit(f"cancelled-rotation alias differed on {values}")

    affine_rotation = (
        Step("rotate_left_k", {"k": 4}), Step("scale_k", {"k": -3}),
        Step("add_k", {"k": 4}), Step("keep_less_than_first", {}),
    )
    commuted_affine_rotation = (
        Step("scale_k", {"k": -3}), Step("add_k", {"k": 4}),
        Step("rotate_left_k", {"k": 4}), Step("keep_less_than_first", {}),
    )
    if (_semantic_key(affine_rotation)
            != _semantic_key(commuted_affine_rotation)):
        raise SystemExit("affine maps were not commuted across rotation")
    for values in probes:
        if (_apply_procedure(affine_rotation, values)
                != _apply_procedure(commuted_affine_rotation, values)):
            raise SystemExit(f"affine/rotation alias differed on {values}")

    for copies in (2, 3, 4):
        for rotation in (-1, 1, copies + 1):
            aligned = (rotation // copies) * copies
            for relation in ("keep_less_than_first", "keep_greater_than_first"):
                partial = (
                    Step("repeat_each_k", {"k": copies}),
                    Step("rotate_left_k", {"k": rotation}),
                    Step("add_k", {"k": -3}), Step(relation, {}),
                )
                whole_run = (
                    Step("repeat_each_k", {"k": copies}),
                    *((Step("rotate_left_k", {"k": aligned}),)
                      if aligned else ()),
                    Step("add_k", {"k": -3}), Step(relation, {}),
                )
                if _semantic_key(partial) != _semantic_key(whole_run):
                    raise SystemExit("partial repeated-run rotation was not canonicalized")
                for values in probes:
                    if (_apply_procedure(partial, values)
                            != _apply_procedure(whole_run, values)):
                        raise SystemExit(
                            f"relative-filter rotation alias differed on {values}"
                        )

    whole_run_shift = (
        Step("repeat_each_k", {"k": 2}), Step("rotate_left_k", {"k": 2}),
        Step("keep_less_than_first", {}),
    )
    no_shift = (Step("repeat_each_k", {"k": 2}),
                Step("keep_less_than_first", {}))
    if _semantic_key(whole_run_shift) == _semantic_key(no_shift):
        raise SystemExit("whole repeated-run shift was incorrectly removed")

    singleton_relative_empty = (
        Step("add_k", {"k": 10}), Step("keep_evens", {}),
        Step("last", {}), Step("keep_greater_than_first", {}),
    )
    if _semantic_key(singleton_relative_empty) != ("always_empty",):
        raise SystemExit("strict relative filter after endpoint selection was not proved empty")
    if any(_apply_procedure(singleton_relative_empty, values)
           for values in probes):
        raise SystemExit("singleton strict relative filter produced a value")

    deletion_aliases = [
        (Step("add_k", {"k": 5}), Step("drop_first", {}),
         Step("add_k", {"k": -3}), Step("keep_multiples_k", {"k": 3})),
        (Step("add_k", {"k": 5}), Step("drop_first", {}),
         Step("keep_multiples_k", {"k": 3}), Step("add_k", {"k": -3})),
        (Step("drop_first", {}), Step("add_k", {"k": 5}),
         Step("add_k", {"k": -3}), Step("keep_multiples_k", {"k": 3})),
    ]
    if len({_semantic_key(procedure) for procedure in deletion_aliases}) != 1:
        raise SystemExit("affine/filter aliases around endpoint deletion stayed distinct")
    deletion_probes = [list(values) for length in range(6)
                       for values in itertools.product(range(-3, 4), repeat=length)]
    for values in deletion_probes:
        expected = _apply_procedure(deletion_aliases[0], values)
        if any(_apply_procedure(procedure, values) != expected
               for procedure in deletion_aliases):
            raise SystemExit(f"endpoint-deletion alias differed on {values}")
    filter_before_delete = (
        Step("keep_multiples_k", {"k": 3}), Step("drop_first", {}),
        Step("add_k", {"k": 2}),
    )
    filter_after_delete = (
        Step("drop_first", {}), Step("keep_multiples_k", {"k": 3}),
        Step("add_k", {"k": 2}),
    )
    if _semantic_key(filter_before_delete) == _semantic_key(filter_after_delete):
        raise SystemExit("filter-before-delete and filter-after-delete were merged")

    relative_endpoint_aliases = [
        (Step("scale_k", {"k": 5}), Step("add_first", {}),
         Step("scale_k", {"k": 3}), Step("last", {})),
        (Step("add_first", {}), Step("scale_k", {"k": 5}),
         Step("scale_k", {"k": 3}), Step("last", {})),
        (Step("scale_k", {"k": 5}), Step("add_first", {}),
         Step("last", {}), Step("scale_k", {"k": 3})),
    ]
    if len({_semantic_key(procedure)
            for procedure in relative_endpoint_aliases}) != 1:
        raise SystemExit("input-relative affine endpoint aliases stayed distinct")
    for values in probes:
        expected = _apply_procedure(relative_endpoint_aliases[0], values)
        if any(_apply_procedure(procedure, values) != expected
               for procedure in relative_endpoint_aliases):
            raise SystemExit(f"input-relative endpoint alias differed on {values}")

    expected_key = _semantic_key(aliases[0])
    controls = [
        (Step("keep_evens", {}), Step("sort_ascending", {}),
         Step("first", {})) + affine,
        (Step("keep_odds", {}), Step("sort_ascending", {}),
         Step("last", {})) + affine,
        (Step("keep_odds", {}), Step("sort_ascending", {}),
         Step("first", {}), Step("add_k", {"k": 3})),
    ]
    if any(_semantic_key(control) == expected_key for control in controls):
        raise SystemExit("distinct predicate, extremum, or offset was merged")

    print("filtered-extreme canonicalization diagnostic: PASS")
    alias_count = sum(len(group) for group in alias_groups)
    print(f"{alias_count} exact aliases plus relational/repeated-rotation rewrites; exhaustive lists and distinct controls: PASS")


if __name__ == "__main__":
    main()
