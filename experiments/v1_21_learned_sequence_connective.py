"""Check that grounded demonstrations teach a procedure-sequence connective.

CRMS should infer "and then" from two compounds whose component rules are
already grounded, then compose known components in a new combination. A
single compound and an unsupported connective must not license composition.

Run from the project root with:
    python3 experiments/v1_21_learned_sequence_connective.py
"""

from __future__ import annotations

import sys
from tempfile import TemporaryDirectory
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


REVERSE = [([1, 3, 2], [2, 3, 1]), ([6, -1, 4], [4, -1, 6]),
           ([2, 5, 2, 1], [1, 2, 5, 2])]
SORT = [([3, 1, 2], [1, 2, 3]), ([5, -1, 4], [-1, 4, 5]),
        ([4, 1, 4, -2], [-2, 1, 4, 4])]
ADD_ONE = [([1, 3, 2], [2, 4, 3]), ([6, -1, 4], [7, 0, 5]),
           ([1, 3, 1, 2], [2, 4, 2, 3]), ([-3, 0], [-2, 1])]

ATOMS = (
    ("reverse the list", REVERSE),
    ("add one to values", ADD_ONE),
    ("sort the list", SORT),
    ("flip the values", REVERSE),
    ("flip the list", REVERSE),
    ("reverse the array", REVERSE),
    ("turn the array", REVERSE),
)
COMPOUNDS = (
    ("reverse the list and then add one to values", [
        ([1, 3, 2], [3, 4, 2]),
        ([6, -1, 4], [5, 0, 7]),
        ([2, 5, 2, 1], [2, 3, 6, 3]),
    ]),
    ("sort the list and then flip the values", [
        ([3, 1, 2], [3, 2, 1]),
        ([5, -1, 4], [5, 4, -1]),
        ([4, 1, 4, -2], [4, 4, 1, -2]),
    ]),
)


def train(include_second: bool = True) -> CRMSModel:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    for phrase, examples in ATOMS:
        result = model.teach(phrase, examples)
        if result.status != "learned":
            raise RuntimeError(f"could not ground component {phrase!r}: {result.status}")
    for index, (phrase, examples) in enumerate(
            COMPOUNDS[:2 if include_second else 1]):
        result = model.teach(phrase, examples)
        if result.status != "learned":
            raise RuntimeError(f"could not ground compound {phrase!r}: {result.status}")
        if index == 0 and include_second:
            # Build the one-context negative cache before the next example is
            # taught; the second teach must invalidate and rebuild it.
            model._grounded_composition_connectives()
    return model


def main() -> None:
    ambiguous_model = CRMSModel(max_composition_depth=2, max_workers=1)
    ambiguous_addition = ambiguous_model.teach("add one to values", ADD_ONE[:3])
    candidate_signatures = {
        tuple(step["operation"] for step in procedure)
        for procedure in (ambiguous_addition.candidate_procedures or [])
    }
    if (ambiguous_addition.status != "need_more_examples"
            or ("add_k",) not in candidate_signatures
            or ("add_k", "absolute_values") not in candidate_signatures):
        raise SystemExit(
            "ambiguous add-one examples should preserve both grounded candidates"
        )
    follow_up = ambiguous_model.predict("add one to values", [2, 4])
    if (follow_up.status != "need_more_examples"
            or follow_up.contrastive_input != ambiguous_addition.contrastive_input
            or follow_up.candidate_outputs != ambiguous_addition.candidate_outputs
            or "separates the remaining procedures" not in (follow_up.message or "")):
        raise SystemExit("prediction discarded the probe from ambiguous teaching")
    resolved = ambiguous_model.teach("add one to values", [ADD_ONE[3]])
    if (resolved.status != "learned"
            or ambiguous_model.predict("add one to values", [2, 4]).status != "ok"):
        raise SystemExit("new evidence did not resolve and clear the cached ambiguity")

    model = train()
    query = "sort the list and then add one to values"
    held_out = ([3, 1, 2], [], [-4, 9, 0])
    expected = ([2, 3, 4], [], [-3, 1, 10])
    predictions = [model.predict(query, values) for values in held_out]
    prediction = predictions[0]
    transferred = all(
        result.status == "ok" and result.output == output
        for result, output in zip(predictions, expected)
    )
    evidence = set(prediction.evidence_phrases or ())
    evidence_ok = {
        phrase for phrase, _examples in COMPOUNDS
    } <= evidence
    template_ok = prediction.matched_templates == ["learned_sequence:and then"]

    paraphrased_composition = model.predict(
        "flip the array and then add one to values", [3, 1, 2])
    paraphrase_sources = set(paraphrased_composition.evidence_phrases or ())
    paraphrased_composition_ok = (
        paraphrased_composition.status == "ok"
        and paraphrased_composition.output == [3, 2, 4]
        and paraphrased_composition.matched_templates
        == ["learned_sequence:and then"]
        and {"flip the list", "reverse the array", "turn the array"}
        <= paraphrase_sources
        and {phrase for phrase, _examples in COMPOUNDS} <= paraphrase_sources
    )
    chain_three = model.predict(
        "flip the array and then add one to values and then sort the list",
        [3, 1, 2])
    chain_three_ok = (
        chain_three.status == "ok" and chain_three.output == [2, 3, 4]
        and chain_three.matched_templates == ["learned_sequence:and then"]
    )
    chain_four = model.predict(
        "flip the array and then add one to values and then sort the list "
        "and then reverse the list", [3, 1, 2])
    chain_four_ok = (
        chain_four.status == "ok" and chain_four.output == [4, 3, 2]
        and chain_four.matched_templates == ["learned_sequence:and then"]
    )
    chain_five = model.predict(
        "flip the array and then add one to values and then sort the list "
        "and then reverse the list and then add one to values", [3, 1, 2])
    chain_five_ok = (
        chain_five.status == "ok" and chain_five.output == [5, 4, 3]
        and chain_five.matched_templates == ["learned_sequence:and then"]
        and "reverse the list and then add one to values"
        in (chain_five.evidence_phrases or [])
    )
    print(
        f"new component combination: {prediction.status}:{prediction.output}; "
        f"evidence={evidence_ok}; template={template_ok}; "
        f"{'PASS' if transferred and evidence_ok and template_ok else 'FAIL'}"
    )
    print(
        f"paraphrased component composition: {paraphrased_composition.status}:"
        f"{paraphrased_composition.output}; sources="
        f"{len(paraphrase_sources)}; "
        f"{'PASS' if paraphrased_composition_ok else 'FAIL'}"
    )
    print(
        f"three-clause chain: {chain_three.status}:{chain_three.output}; "
        f"{'PASS' if chain_three_ok else 'FAIL'}"
    )
    print(
        f"four-clause chain: {chain_four.status}:{chain_four.output}; "
        f"{'PASS' if chain_four_ok else 'FAIL'}"
    )
    print(
        f"chain reusing a taught compound: {chain_five.status}:"
        f"{chain_five.output}; {'PASS' if chain_five_ok else 'FAIL'}"
    )
    print("ambiguous addition examples: need_more_examples; PASS")

    one_context = train(include_second=False)
    insufficient = one_context.predict(query, [3, 1, 2])
    single_context_abstains = insufficient.status == "need_examples"
    unsupported = model.predict("sort the list or add one to values", [3, 1, 2])
    unknown_connector_abstains = unsupported.status == "need_examples"
    unknown_component = model.predict(
        "shuffle the list and then add one to values", [3, 1, 2])
    unknown_component_abstains = unknown_component.status == "need_examples"
    with TemporaryDirectory() as directory:
        memory_path = Path(directory) / "memory.json"
        model.save(memory_path)
        restored = CRMSModel(memory_path, max_composition_depth=2, max_workers=1)
        after_load = restored.predict(query, [3, 1, 2])
        load_preserves_transfer = (
            after_load.status == "ok" and after_load.output == [2, 3, 4]
            and after_load.evidence_phrases == prediction.evidence_phrases
        )
        alias_after_load = restored.predict(
            "flip the array and then add one to values", [3, 1, 2])
        load_preserves_paraphrased_composition = (
            alias_after_load.status == "ok"
            and alias_after_load.output == [3, 2, 4]
            and alias_after_load.evidence_phrases
            == paraphrased_composition.evidence_phrases
        )
        chain_after_load = restored.predict(
            "flip the array and then add one to values and then sort the list",
            [3, 1, 2])
        load_preserves_chain = (
            chain_after_load.status == "ok"
            and chain_after_load.output == [2, 3, 4]
            and chain_after_load.evidence_phrases == chain_three.evidence_phrases
        )
    print(
        f"one connective context: {insufficient.status}; "
        f"{'PASS' if single_context_abstains else 'FAIL'}"
    )
    print(
        f"unsupported connective: {unsupported.status}; "
        f"{'PASS' if unknown_connector_abstains else 'FAIL'}"
    )
    print(
        f"unknown component: {unknown_component.status}; "
        f"{'PASS' if unknown_component_abstains else 'FAIL'}"
    )
    print(
        f"learned connective after save/load: {after_load.status}:{after_load.output}; "
        f"{'PASS' if load_preserves_transfer else 'FAIL'}"
    )
    print(
        f"paraphrased composition after save/load: {alias_after_load.status}:"
        f"{alias_after_load.output}; "
        f"{'PASS' if load_preserves_paraphrased_composition else 'FAIL'}"
    )
    print(
        f"three-clause chain after save/load: {chain_after_load.status}:"
        f"{chain_after_load.output}; {'PASS' if load_preserves_chain else 'FAIL'}"
    )
    if not (transferred and evidence_ok and template_ok
            and paraphrased_composition_ok
            and chain_three_ok and chain_four_ok and chain_five_ok
            and single_context_abstains and unknown_connector_abstains
            and unknown_component_abstains and load_preserves_transfer
            and load_preserves_paraphrased_composition
            and load_preserves_chain):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
