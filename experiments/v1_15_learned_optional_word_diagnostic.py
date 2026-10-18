"""Measure optional-span insertion/deletion with substitutions.

The learner sees only grounded phrase examples. It must learn that a token
span can be optional in multiple contexts, then combine deletion or insertion
with independently demonstrated word substitutions. No stop-word list or
language model is used.

Run from the project root with:
    python3 experiments/v1_15_learned_optional_word_diagnostic.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_model import CRMSModel


EXAMPLES = [
    ([1, 2, 3], [3, 2, 1]),
    ([2, 8, 1], [1, 8, 2]),
]

PHRASES = (
    "reverse the list",
    "reverse list",
    "reverse the values",
    "reverse values",
    "turn the list",
)
INSERTION_PHRASES = PHRASES[:-1] + ("turn list",)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        memory_path = Path(temporary_directory) / "memory.json"
        model = CRMSModel(memory_path, max_composition_depth=1, max_workers=1)
        for phrase in PHRASES:
            learned = model.teach(phrase, EXAMPLES)
            if learned.status != "learned":
                raise RuntimeError(f"could not ground {phrase!r}: {learned.status}")

        # The edit pattern is derived from stored cases, not a separate hidden
        # table, so it should be reconstructible after a memory reload.
        reloaded = CRMSModel(memory_path, max_composition_depth=1, max_workers=1)

    # "turn list" and "turn values" are both absent. The query must apply a
    # deletion grounded in two reverse phrases, then combine that pattern with
    # the separately grounded "turn" substitution and the "values" object.
    query = reloaded.predict("turn values", [-1, 2, 9])
    combined_transfer = query.status == "ok" and query.output == [9, 2, -1]
    expected_evidence = {
        "reverse the list", "reverse list", "reverse the values",
        "reverse values", "turn the list",
    }
    evidence_complete = expected_evidence <= set(query.evidence_phrases or ())

    # The same grounded optional-span rule can expand a short stored phrase
    # before independently grounded lexical substitutions are aligned.
    insertion_model = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in INSERTION_PHRASES:
        if insertion_model.teach(phrase, EXAMPLES).status != "learned":
            raise RuntimeError(f"could not ground insertion phrase {phrase!r}")
    inserted = insertion_model.predict("turn the values", [-1, 2, 9])
    insertion_transfer = inserted.status == "ok" and inserted.output == [9, 2, -1]
    insertion_evidence = {
        "reverse the list", "reverse list", "reverse the values",
        "reverse values", "turn list",
    } <= set(inserted.evidence_phrases or ())
    insertion_model.forget("reverse the values")
    after_forget_insertion = insertion_model.predict(
        "turn the values", [-1, 2, 9])
    insertion_evidence_removed = (
        after_forget_insertion.status == "need_examples")

    reloaded.forget("reverse the values")
    after_forget = reloaded.predict("turn values", [-1, 2, 9])
    deletion_evidence_removed = after_forget.status == "need_examples"

    # An unseen modifier remains unsupported even when all its other words are
    # familiar, preserving the conservative unknown-word gate.
    unknown_modifier = model.predict("please turn values", [-1, 2, 9])
    safe_abstention = unknown_modifier.status == "need_examples"

    control = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in (
        "reverse the list", "reverse list", "reverse the values", "turn the list",
    ):
        control.teach(phrase, EXAMPLES)
    without_deletion_evidence = control.predict("turn values", [-1, 2, 9])
    deletion_is_grounded = without_deletion_evidence.status == "need_examples"

    # Independently grounded patterns for sorting also produce "turn values".
    # The resolver must report ambiguity instead of selecting either behavior.
    ambiguous = CRMSModel(max_composition_depth=1, max_workers=1)
    for phrase in PHRASES:
        ambiguous.teach(phrase, EXAMPLES)
    sort_examples = [
        ([3, -1, 5], [-1, 3, 5]),
        ([8, 2, 0, 6], [0, 2, 6, 8]),
    ]
    for phrase in (
        "organize the values", "organize values",
        "organize the objects", "organize objects", "turn the objects",
    ):
        learned_sort = ambiguous.teach(phrase, sort_examples)
        if learned_sort.status == "need_more_examples":
            probe = learned_sort.contrastive_input
            if probe is None:
                raise RuntimeError("sorting ambiguity had no contrastive probe")
            learned_sort = ambiguous.teach(phrase, [(probe, sorted(probe))])
        if learned_sort.status != "learned":
            raise RuntimeError(f"could not ground sorting behavior for {phrase!r}: "
                               f"{learned_sort.status}")
    # Ground the cross-slot combination as well: ``turn`` was taught with
    # ``objects`` for sorting and ``list`` for reversal; ``values`` must not
    # silently inherit either action until its combination is demonstrated.
    turn_values_sort = ambiguous.teach("turn the values", sort_examples)
    if turn_values_sort.status == "need_more_examples":
        probe = turn_values_sort.contrastive_input
        if probe is None:
            raise RuntimeError("turn-the-values ambiguity had no contrastive probe")
        turn_values_sort = ambiguous.teach(
            "turn the values", [(probe, sorted(probe))])
    if turn_values_sort.status != "learned":
        raise RuntimeError("could not ground the competing turn-values rule")
    competing_transfer = ambiguous.predict("turn values", [-1, 2, 9])
    ambiguity_preserved = (
        competing_transfer.status in {"need_examples", "need_more_examples"}
        and bool((competing_transfer.language_gaps or {}).get("conflicting_tokens")))

    print(
        f"learned optional-word transfer after reload: {query.status}:{query.output}; "
        f"evidence_complete={evidence_complete}; "
        f"{'PASS' if combined_transfer and evidence_complete else 'FAIL'}"
    )
    print(
        f"learned optional-span insertion: {inserted.status}:{inserted.output}; "
        f"evidence_complete={insertion_evidence}; "
        f"{'PASS' if insertion_transfer and insertion_evidence else 'FAIL'}"
    )
    print(
        f"unknown modifier: {unknown_modifier.status}; "
        f"{'PASS' if safe_abstention else 'FAIL'}"
    )
    print(
        f"with only one deletion pair: {without_deletion_evidence.status}; "
        f"{'PASS' if deletion_is_grounded else 'FAIL'}"
    )
    print(
        f"after forgetting deletion evidence: {after_forget.status}; "
        f"{'PASS' if deletion_evidence_removed and insertion_evidence_removed else 'FAIL'}"
    )
    print(
        f"competing grounded rule: {competing_transfer.status}; "
        f"{'PASS' if ambiguity_preserved else 'FAIL'}"
    )
    if not (combined_transfer and evidence_complete and insertion_transfer
            and insertion_evidence and safe_abstention
            and deletion_is_grounded and deletion_evidence_removed
            and insertion_evidence_removed and ambiguity_preserved):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
