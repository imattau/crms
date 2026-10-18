"""Probe rule induction, ambiguity handling, and primitive discovery.

This diagnostic targets the current symbolic CRMS learner rather than the
historical VSA experiments. It does not add operations or pass rule labels to
the learner. The demonstrations are small and synthetic, so results describe
only this finite operation library.

Run from the project root with:
    python3 experiments/v1_11_rule_discovery_diagnostic.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import (
    CRMSModel, Step, _apply_procedure, _contrastive_probe, _semantic_key,
)


def main() -> None:
    model = CRMSModel(max_composition_depth=2, max_workers=1)

    # A two-step rule whose held-out result is not in the demonstrations.
    target = "return the smallest value"
    examples = [
        ([3, 1, 2], [1]),
        ([8, 2, 4], [2]),
        ([9, -1, 3, 5], [-1]),
    ]
    learned = model.teach(target, examples)
    contrastive_input = None
    if (learned.status == "need_more_examples"
            and learned.contrastive_input is not None):
        contrastive_input = learned.contrastive_input
        learned = model.teach(
            target,
            [(contrastive_input, _apply_procedure(
                (Step("sort_ascending", {}), Step("first", {})),
                contrastive_input))],
        )
    held_out_input = [7, -4, 6, 0]
    held_out_expected = [-4]
    held_out = model.predict(target, held_out_input)
    held_out_ok = (
        learned.status == "learned"
        and held_out.status == "ok"
        and held_out.output == held_out_expected
    )

    # One sorted demonstration confounds reverse with descending sort.
    ambiguity = CRMSModel(max_composition_depth=1, max_workers=1)
    first = ambiguity.teach("turn the list around", [([1, 2, 3], [3, 2, 1])])
    unresolved_status = first.status
    resolved = ambiguity.teach(
        "turn the list around",
        [([2, 8, 1], [1, 8, 2])],
    )

    # Learned phrase evidence may disambiguate examples, but only if its
    # procedure is among the rules that fit every demonstration.
    grounded = CRMSModel(max_composition_depth=1, max_workers=1)
    reverse_examples = [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])]
    for phrase in ("reverse the list", "reverse the values", "turn the list"):
        grounded.teach(phrase, reverse_examples)
    language_resolved = grounded.teach(
        "turn the values", [([1, 2, 3], [3, 2, 1])]
    )
    supported_by_language = (
        language_resolved.status == "learned"
        and language_resolved.procedure == [{"operation": "reverse", "parameters": {}}]
        and set(language_resolved.evidence_phrases or ()) == {
            "reverse the list", "reverse the values", "turn the list"
        }
    )

    contradictory_language = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in ("reverse the list", "reverse the values", "turn the list"):
        contradictory_language.teach(phrase, reverse_examples)
    conflicting_example = contradictory_language.teach(
        "turn the values", [([1, 2, 3], [1, 2, 3])]
    )
    prior_respected = conflicting_example.status == "need_more_examples"

    # Discover duplicate-each from examples. A repeated-value demonstration
    # distinguishes it from stable deduplication; the length-three cases still
    # alias rotations by +/-3, so resolve those with the learner's probe.
    duplicate_model = CRMSModel(max_composition_depth=2, max_workers=1)
    duplicate_examples = [
        ([1, 2, 3], [1, 1, 2, 2, 3, 3]),
        ([4, -1, 0], [4, 4, -1, -1, 0, 0]),
        ([1, 1, 2], [1, 1, 1, 1, 2, 2]),
    ]
    duplicate = duplicate_model.teach(
        "duplicate each value",
        duplicate_examples,
    )
    duplicate_probe = duplicate.contrastive_input
    if duplicate.status == "need_more_examples" and duplicate_probe is not None:
        duplicate = duplicate_model.teach(
            "duplicate each value",
            [(duplicate_probe, _apply_procedure(
                (Step("duplicate_each", {}),), duplicate_probe))],
        )
    duplicate_held_out = [2, -5, 7, 0, 3]
    with tempfile.TemporaryDirectory() as directory:
        memory_path = Path(directory) / "duplicate-memory.json"
        duplicate_model.save(memory_path)
        restored_duplicate = CRMSModel(
            memory_path, max_composition_depth=2, max_workers=1)
        duplicate_after_load = restored_duplicate.predict(
            "duplicate each value", duplicate_held_out)
    duplicate_discovered = (
        duplicate.status == "learned"
        and _semantic_key(tuple(
            Step(step['operation'], step['parameters'])
            for step in duplicate.procedure or []))
        == _semantic_key((Step("duplicate_each", {}),))
        and duplicate_model.predict(
            "duplicate each value", duplicate_held_out).output
        == [2, 2, -5, -5, 7, 7, 0, 0, 3, 3]
        and duplicate_after_load.status == "ok"
        and duplicate_after_load.output == [2, 2, -5, -5, 7, 7, 0, 0, 3, 3]
    )

    # A fixed {-1, 0, 1} probe domain cannot distinguish these rules: both
    # retain only zero. Candidate-grounded probes need to include a multiple
    # such as 3, which one rule keeps and the other rejects.
    modulus_probe, modulus_outputs = _contrastive_probe([
        (Step("keep_multiples_k", {"k": 3}),),
        (Step("keep_multiples_k", {"k": 6}),),
    ])
    modulus_probe_ok = (
        modulus_probe is not None
        and modulus_outputs is not None
        and len({tuple(output) for output in modulus_outputs}) == 2
    )

    # A balanced probe should quickly separate an always-empty odd/multiple
    # of six procedure from an intersection of multiples-of-five and six.
    interaction_candidates = [
        (Step("keep_odds", {}), Step("keep_multiples_k", {"k": 6})),
        (Step("keep_multiples_k", {"k": 5}),
         Step("keep_multiples_k", {"k": 6})),
    ]
    interaction_probe, interaction_outputs = _contrastive_probe(
        interaction_candidates)
    interaction_probe_ok = (
        interaction_probe is not None
        and interaction_outputs is not None
        and len({tuple(output) for output in interaction_outputs}) == 2
        and interaction_outputs == [
            _apply_procedure(candidate, interaction_probe)
            for candidate in interaction_candidates
        ]
    )

    print("CRMS rule-discovery diagnostic")
    print(
        f"composed rule: status={learned.status}, "
        f"candidate_count={learned.candidate_count}, "
        f"contrast={contrastive_input}, "
        f"procedure={learned.procedure}, "
        f"held_out={'PASS' if held_out_ok else 'FAIL'} "
        f"(got={held_out.output}, expected={held_out_expected})"
    )
    print(
        f"ambiguity gate: one_example={unresolved_status}, "
        f"after_contrast={resolved.status}, procedure={resolved.procedure}"
    )
    print(
        f"language-assisted induction: learned={language_resolved.status}, "
        f"support={language_resolved.evidence_phrases}, "
        f"grounded={'PASS' if supported_by_language else 'FAIL'}; "
        f"contradictory example preserved ambiguity="
        f"{'PASS' if prior_respected else 'FAIL'}"
    )
    print(
        f"repeat-count-two discovery: status={duplicate.status}, "
        f"probe={duplicate_probe}, held_out="
        f"{'PASS' if duplicate_discovered else 'FAIL'}, "
        f"reload={duplicate_after_load.status}"
    )
    print(
        f"parameter contrast: input={modulus_probe}, outputs={modulus_outputs}, "
        f"separated={'PASS' if modulus_probe_ok else 'FAIL'}"
    )
    print(
        f"combined-filter contrast: input={interaction_probe}, "
        f"outputs={interaction_outputs}, "
        f"separated={'PASS' if interaction_probe_ok else 'FAIL'}"
    )
    if not (modulus_probe_ok and interaction_probe_ok and duplicate_discovered):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
