"""Measure transfer from grounded multi-token optional spans.

The learner should infer a repeated contiguous deletion from same-rule phrase
pairs, apply it to a separately grounded phrase, and combine it with a word
substitution. No built-in list of removable words is provided.

Run from the project root with:
    python3 experiments/v1_18_optional_span_diagnostic.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


REVERSE_EXAMPLES = [
    ([1, 2, 3], [3, 2, 1]),
    ([2, 8, 1], [1, 8, 2]),
]
PHRASES = (
    "reverse all the values",
    "reverse values",
    "reverse all the entries",
    "reverse entries",
    "turn all the values",
)


def main() -> None:
    model = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in PHRASES:
        result = model.teach(phrase, REVERSE_EXAMPLES)
        if result.status != "learned":
            raise RuntimeError(f"could not ground {phrase!r}: {result.status}")

    transfer = model.predict("turn entries", [-1, 2, 9])
    transfer_ok = transfer.status == "ok" and transfer.output == [9, 2, -1]
    evidence_expected = {
        "reverse all the values", "reverse values",
        "reverse all the entries", "reverse entries", "turn all the values",
    }
    evidence_ok = evidence_expected <= set(transfer.evidence_phrases or ())

    unknown_modifier = model.predict("please turn entries", [-1, 2, 9])
    modifier_abstains = unknown_modifier.status == "need_examples"

    single_context = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in (
        "reverse all the values", "reverse values",
        "reverse all the entries", "turn all the values",
    ):
        single_context.teach(phrase, REVERSE_EXAMPLES)
    insufficient = single_context.predict("turn entries", [-1, 2, 9])
    one_pair_abstains = insufficient.status == "need_examples"

    ambiguous = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in PHRASES:
        ambiguous.teach(phrase, REVERSE_EXAMPLES)
    sort_examples = [
        ([3, -1, 5], [-1, 3, 5]),
        ([8, 2, 0, 6], [0, 2, 6, 8]),
    ]
    for phrase in (
        "organize all the values", "organize values",
        "organize all the entries", "organize entries",
        "organize all the items", "turn all the items",
    ):
        learned = ambiguous.teach(phrase, sort_examples)
        if learned.status == "need_more_examples":
            probe = learned.contrastive_input
            if probe is None:
                raise RuntimeError(
                    f"sorting ambiguity for {phrase!r} had no contrastive probe")
            learned = ambiguous.teach(
                phrase, [(probe, sorted(probe))])
        if learned.status != "learned":
            raise RuntimeError(
                f"could not ground competing sort phrase {phrase!r}: "
                f"{learned.status}")
    competing = ambiguous.predict("turn entries", [-1, 2, 9])
    ambiguity_preserved = competing.status == "need_examples"

    print(
        f"optional span transfer: {transfer.status}:{transfer.output}; "
        f"evidence_complete={evidence_ok}; "
        f"{'PASS' if transfer_ok and evidence_ok else 'FAIL'}"
    )
    print(
        f"unknown modifier: {unknown_modifier.status}; "
        f"{'PASS' if modifier_abstains else 'FAIL'}"
    )
    print(
        f"one deletion pair: {insufficient.status}; "
        f"{'PASS' if one_pair_abstains else 'FAIL'}"
    )
    print(
        f"competing grounded behavior: {competing.status}; "
        f"{'PASS' if ambiguity_preserved else 'FAIL'}"
    )
    if not (transfer_ok and evidence_ok and modifier_abstains
            and one_pair_abstains and ambiguity_preserved):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
