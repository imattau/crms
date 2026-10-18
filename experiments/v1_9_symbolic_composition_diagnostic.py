"""Diagnose retrieval and explicit composition in the current symbolic model.

This adapts the original v1.3 diagnostic to ``CRMSModel``. Component phrases
are learned from examples, then composed with the documented ``, then ``
separator. Each trial measures step 1, step 2 on the gold intermediate, the
strict successful path, and the composed prediction. The independence baseline
is p1 * marginal_p2; p1 * p2_given_p1 is the chain-rule path rate.

Run from the project root with:
    python3 experiments/v1_9_symbolic_composition_diagnostic.py

This is a small synthetic mechanism diagnostic, not a language benchmark.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, Step, _apply_procedure


TARGETS = {
    "reverse": (Step("reverse", {}),),
    "ascending": (Step("sort_ascending", {}),),
    "descending": (Step("sort_descending", {}),),
    "double": (Step("double", {}),),
    "first": (Step("first", {}),),
    "last": (Step("last", {}),),
}


def teach_with_feedback(model: CRMSModel, phrase: str,
                        examples: list[tuple[list[int], list[int]]],
                        target: tuple[Step, ...]):
    """Resolve only real candidate ambiguity with the known teacher rule."""
    result = model.teach(phrase, examples)
    for _ in range(8):
        if result.status == "learned":
            return result
        probe = result.contrastive_input
        if result.status != "need_more_examples" or probe is None:
            return result
        expected = _apply_procedure(target, probe)
        if expected not in (result.candidate_outputs or []):
            raise RuntimeError(
                f"contrastive probe omitted intended behavior for {phrase!r}: {result}")
        result = model.teach(phrase, [(probe, expected)])
    return result


TEACHING = {
    "reverse": {
        "phrases": ["reverse the list", "reverse the values", "turn the list"],
        "query": "turn the values",
        "examples": [
            ([1, 2, 3], [3, 2, 1]),
            ([2, 8, 1], [1, 8, 2]),
        ],
    },
    "ascending": {
        "phrases": ["sort these values ascending", "sort these numbers ascending",
                    "order these values ascending"],
        "query": "order these numbers ascending",
        "examples": [
            ([3, -1, 5], [-1, 3, 5]),
            ([8, 2, 0, 6], [0, 2, 6, 8]),
        ],
    },
    "descending": {
        "phrases": ["sort these values descending", "sort these numbers descending",
                    "order these values descending"],
        "query": "order these numbers descending",
        "examples": [
            ([3, -1, 5], [5, 3, -1]),
            ([8, 2, 0, 6], [8, 6, 2, 0]),
        ],
    },
    "double": {
        "phrases": ["double every value", "double every number",
                    "multiply every value"],
        "query": "multiply every number",
        "examples": [
            ([3, -2, 5], [6, -4, 10]),
            ([0, 7, -1], [0, 14, -2]),
        ],
    },
    "first": {
        "phrases": ["keep the first value", "keep the first number",
                    "take the first value"],
        "query": "take the first number",
        "examples": [
            ([2, 8, 1], [2]),
            ([9, -3, 6, 4], [9]),
        ],
    },
    "last": {
        "phrases": ["keep the last value", "keep the last number",
                    "take the last value"],
        "query": "take the last number",
        "examples": [
            ([2, 8, 1], [1]),
            ([9, -3, 6, 4], [4]),
        ],
    },
}


def diagnose(seed: int = 42, n_trials: int = 200) -> dict[str, float | int]:
    rng = random.Random(seed)
    model = CRMSModel(max_composition_depth=1)
    canonical_procedures = {}
    for label, entry in TEACHING.items():
        for phrase in entry["phrases"]:
            result = teach_with_feedback(
                model, phrase, entry["examples"], TARGETS[label])
            if result.status != "learned":
                raise RuntimeError(
                    f"diagnostic teaching phrase {phrase!r} was not uniquely learned: "
                    f"{result.status} ({result.candidate_count} candidates)"
                )
        canonical_procedures[label] = model._procedures[entry["phrases"][0]]

    labels = list(TEACHING)
    step1_ok = step2_marginal_ok = step2_given_step1_ok = 0
    strict_path_ok = composed_ok = process_matches_direct = 0

    for _ in range(n_trials):
        first, second = rng.sample(labels, 2)
        first_query = TEACHING[first]["query"]
        second_query = TEACHING[second]["query"]
        values = [rng.randint(-9, 9) for _ in range(rng.randint(3, 6))]
        gold_mid = _apply_procedure(canonical_procedures[first], values)
        gold_output = _apply_procedure(canonical_procedures[second], gold_mid)

        predicted_mid = model.predict(first_query, values)
        first_correct = predicted_mid.status == "ok" and predicted_mid.output == gold_mid
        step1_ok += first_correct

        predicted_gold_step2 = model.predict(second_query, gold_mid)
        second_correct_on_gold = (
            predicted_gold_step2.status == "ok"
            and predicted_gold_step2.output == gold_output
        )
        step2_marginal_ok += second_correct_on_gold
        if first_correct:
            step2_given_step1_ok += second_correct_on_gold
            strict_path_ok += second_correct_on_gold

        compound = f"{first_query}, then {second_query}"
        composed = model.predict(compound, values)
        final_correct = composed.status == "ok" and composed.output == gold_output
        composed_ok += final_correct

        direct = _apply_procedure(
            tuple(canonical_procedures[first]) + tuple(canonical_procedures[second]),
            values,
        )
        process_matches_direct += (
            composed.status == "ok" and composed.output == direct
        )

    p1 = step1_ok / n_trials
    p2_marginal = step2_marginal_ok / n_trials
    p2_given_p1 = step2_given_step1_ok / step1_ok if step1_ok else 0.0
    return {
        "p1": p1,
        "p2_marginal": p2_marginal,
        "p2_given_p1": p2_given_p1,
        "independence_baseline": p1 * p2_marginal,
        "chain_rule_path": p1 * p2_given_p1,
        "strict_path": strict_path_ok / n_trials,
        "composed_final": composed_ok / n_trials,
        "compose_matches_direct": process_matches_direct / n_trials,
        "n": n_trials,
    }


def main() -> None:
    result = diagnose()
    print("CRMS symbolic-model composition diagnostic")
    print("independence baseline = p1 * marginal p2")
    print("chain-rule path = p1 * p2|p1")
    print(
        f"p1={result['p1']:.3f}  "
        f"p2_marginal={result['p2_marginal']:.3f}  "
        f"p2|p1={result['p2_given_p1']:.3f}  "
        f"independence={result['independence_baseline']:.3f}  "
        f"strict_path={result['strict_path']:.3f}  "
        f"composed_final={result['composed_final']:.3f}  "
        f"compose_matches_direct={result['compose_matches_direct']:.3f}  "
        f"n={result['n']}"
    )


if __name__ == "__main__":
    main()
