"""Probe known limits of the current example-grounded language retriever.

The cases isolate positional recombination, word-order changes, unknown
modifiers, and ambiguity when the same words occur with different procedures.
This is a deterministic diagnostic, not a general language benchmark.

Run from the project root with:
    python3 experiments/v1_10_language_retrieval_diagnostic.py
"""

from __future__ import annotations

from itertools import permutations
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel, _VSAEncoder, _apply_procedure, _semantic_key


EXAMPLES = {
    "reverse the list": [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])],
    "reverse the values": [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])],
    "turn the list": [([1, 2, 3], [3, 2, 1]), ([2, 8, 1], [1, 8, 2])],
    "sort the list": [([3, -1, 5], [-1, 3, 5]), ([8, 2, 0, 6], [0, 2, 6, 8]),
                      ([-4, 2], [-4, 2])],
    "sort the values": [([3, -1, 5], [-1, 3, 5]), ([8, 2, 0, 6], [0, 2, 6, 8]),
                        ([-4, 2], [-4, 2])],
    "arrange the list": [([3, -1, 5], [-1, 3, 5]), ([8, 2, 0, 6], [0, 2, 6, 8]),
                         ([-4, 2], [-4, 2])],
}

PROBES = [
    ("aligned word recombination", "turn the values", "ok", [3, 2, 1]),
    ("omitted filler word", "reverse list", "ok", [3, 2, 1]),
    # Every word is grounded, but the order is unseen and reverses the phrase.
    ("reordered known words", "values reverse the", "need_examples", None),
    ("unknown modifier", "please reverse the list", "need_examples", None),
    # Both tokens and their bigram occur with reverse and ascending sort.
    ("cross-rule lexical ambiguity", "the values", "need_examples", None),
]


def main() -> None:
    encoder = _VSAEncoder(dimension=1)
    bipolar_bundle_ok = (
        encoder._bundle([(1,), (1,), (-1,)]) == (1,)
        and encoder._bundle([(1,), (-1,), (-1,)]) == (-1,)
        and encoder._bundle([(1,), (-1,)]) == (0,)
    )
    if not bipolar_bundle_ok:
        raise RuntimeError("VSA bundling does not implement bipolar majority")

    model = CRMSModel(max_composition_depth=1)
    for phrase, examples in EXAMPLES.items():
        result = model.teach(phrase, examples)
        if result.status != "learned":
            raise RuntimeError(
                f"could not ground {phrase!r}: {result.status} "
                f"({result.candidate_count} candidates)"
            )

    values = [1, 2, 3]
    failures = 0
    gap_diagnostics_ok = True
    print("CRMS language-retrieval diagnostic")
    print("bipolar bundling: PASS")
    for label, phrase, expected_status, expected_output in PROBES:
        prediction = model.predict(phrase, values)
        correct = prediction.status == expected_status
        if expected_status == "ok":
            correct = correct and prediction.output == expected_output
        if label == "unknown modifier":
            correct = correct and (
                prediction.language_gaps is not None
                and prediction.language_gaps.get("unknown_tokens") == ["please"]
                and "please" in (prediction.request or "")
            )
        elif label == "reordered known words":
            correct = correct and (
                prediction.language_gaps is not None
                and "values reverse" in prediction.language_gaps.get(
                    "weak_bigrams", [])
            )
        elif label == "cross-rule lexical ambiguity":
            conflicts = (prediction.language_gaps or {}).get(
                "conflicting_bigrams", [])
            correct = correct and (
                any(item.startswith("the values:")
                    and "reverse" in item and "sort_ascending" in item
                    for item in conflicts)
                and "Learned language evidence conflicts" in (prediction.request or "")
                and "the values:" in (prediction.request or "")
            )
        if label in ("unknown modifier", "reordered known words"):
            gap_diagnostics_ok = gap_diagnostics_ok and correct
        failures += not correct
        print(
            f"{label}: {phrase!r} -> {prediction.status}"
            f"{'' if prediction.output is None else ': ' + str(prediction.output)}"
            f"; expected {expected_status}"
            f"{' (abstain)' if expected_status != 'ok' else ''}"
            f"{'' if expected_output is None else ': ' + str(expected_output)}"
            f"; {'PASS' if correct else 'FAIL'}"
        )
    print(
        f"cases={len(PROBES)} failures={failures}; "
        f"language-gap traces={'PASS' if gap_diagnostics_ok else 'FAIL'}"
    )

    # Exhaust all grounded in-order omissions of at least two tokens. A query
    # is expected to resolve only when all supporting phrases imply one
    # behavior; shared fragments across different rules must abstain.
    supported = defaultdict(dict)
    for phrase, procedure in model._procedures.items():
        words = model._instruction_sequence(phrase)
        for mask in range(1, 1 << len(words)):
            query_words = [word for index, word in enumerate(words)
                           if mask & (1 << index)]
            if len(query_words) < 2 or len(query_words) == len(words):
                continue
            query = " ".join(query_words)
            supported[query][_semantic_key(procedure)] = procedure

    probe_inputs = [[1, 2, 3], [3, -1, 2, 0], [-4, 5]]
    unique_total = unique_correct = ambiguous_total = ambiguous_abstained = 0
    for query, procedures in supported.items():
        prediction = model.predict(query, probe_inputs[0])
        if len(procedures) == 1:
            unique_total += 1
            procedure = next(iter(procedures.values()))
            expected = [_apply_procedure(procedure, values)
                        for values in probe_inputs]
            answers = [model.predict(query, values) for values in probe_inputs]
            if all(answer.status == "ok" and answer.output == result
                   for answer, result in zip(answers, expected)):
                unique_correct += 1
        else:
            ambiguous_total += 1
            ambiguous_abstained += prediction.status != "ok"

    print(
        f"in-order omissions: unique_correct={unique_correct}/{unique_total}, "
        f"ambiguous_abstentions={ambiguous_abstained}/{ambiguous_total}, "
        f"probe_inputs={len(probe_inputs)}"
    )

    exact_phrases = set(model._procedures)
    reordered = {
        " ".join(order)
        for phrase in exact_phrases
        for order in permutations(model._instruction_sequence(phrase))
        if " ".join(order) not in exact_phrases
    }
    reordered_answers = [
        phrase for phrase in sorted(reordered)
        if model.predict(phrase, probe_inputs[0]).status == "ok"
    ]

    # These added words are all known from other learned phrases, so this
    # checks that familiarity alone does not license a modifier.
    known_modifier_queries = [
        "reverse the list sort",
        "sort the list reverse",
        "reverse the values arrange",
        "arrange the list reverse",
        "turn the values sort",
    ]
    modifier_answers = [
        phrase for phrase in known_modifier_queries
        if model.predict(phrase, probe_inputs[0]).status == "ok"
    ]
    if reordered_answers or modifier_answers:
        raise RuntimeError(
            f"ungrounded language accepted: reorders={reordered_answers}, "
            f"known_modifiers={modifier_answers}"
        )
    print(
        f"word-order negatives: abstained="
        f"{len(reordered) - len(reordered_answers)}/{len(reordered)}, "
        f"known-modifier negatives: abstained={len(known_modifier_queries)}/"
        f"{len(known_modifier_queries)}"
    )

    # A novel token has no preloaded meaning. It becomes usable only after a
    # teacher grounds it to the same rule with examples.
    acquisition = CRMSModel(max_composition_depth=1)
    reverse_examples = EXAMPLES["reverse the list"]
    for phrase in ("reverse the list", "reverse the values"):
        acquisition.teach(phrase, reverse_examples)
    novel_before = acquisition.predict("zorb the values", values)
    acquisition.teach("zorb the list", reverse_examples)
    novel_after = acquisition.predict("zorb the values", values)
    removed = acquisition.forget("zorb the list")
    novel_after_forget = acquisition.predict("zorb the values", values)
    acquired = (novel_before.status == "need_examples"
                and novel_before.language_gaps is not None
                and novel_before.language_gaps.get("unknown_tokens") == ["zorb"]
                and "zorb" in (novel_before.request or "")
                and novel_after.status == "ok"
                and novel_after.output == [3, 2, 1]
                and removed
                and novel_after_forget.status == "need_examples"
                and novel_after_forget.language_gaps is not None
                and novel_after_forget.language_gaps.get("unknown_tokens") == ["zorb"])
    if not acquired:
        raise RuntimeError(
            "novel token did not move from abstention to demonstrated transfer: "
            f"before={novel_before.status}, after={novel_after.status}"
        )
    print(
        f"teacher-grounded token: before={novel_before.status}, "
        f"after={novel_after.status}:{novel_after.output}; "
        f"after forget={novel_after_forget.status}; PASS"
    )


if __name__ == "__main__":
    main()
