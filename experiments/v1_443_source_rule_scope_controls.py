"""Exercise source-rule proposal scope gates on novel clause forms.

These controls target the narrow review-candidate extractor from v1_437.
They are Codex-authored regression cases, not an estimate of production
proposal precision.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_research import CRMSResearchIndex
from v1_437_heldout_publisher_phrase_review import (
    MDN_SOURCE, NUMPY_SORT_SOURCE, PYTHON_SOURCE,
    extract_passive_review_candidate, extract_review_candidate,
)


CASES = (
    ("positive with explanatory parenthetical",
     "The following function will sort the array in ascending order "
     "(if it does not contain NaN).", True),
    ("denied guarantee",
     "The documentation does not guarantee that the following function "
     "will sort the array in ascending order.", False),
    ("no evidence",
     "There is no guarantee that the following function will sort the array "
     "in ascending order.", False),
    ("unverified behavior",
     "The author has not verified that the following function will sort the "
     "array in ascending order.", False),
    ("uncertainty scope",
     "It is uncertain whether the following function will sort the array "
     "in ascending order.", False),
    ("conditional antecedent",
     "If all values are comparable, the following function will sort the "
     "array in ascending order.", True),
    ("exclusive condition",
     "The following function will sort the array in ascending order only "
     "if all values are comparable.", True),
    ("direct negation",
     "The following function will not sort the array in ascending order.",
     False),
    ("quoted assertion",
     "The note says, 'The following function will sort the array in "
     "ascending order,' but this statement is not verified.", False),
    ("metalinguistic mention",
     "The phrase 'sort the array in ascending order' is a label, not an "
     "instruction.", False),
    ("opposite direction",
     "The following function will sort the array in descending order.",
     False),
)

PASSIVE_CASES = (
    ("asserted passive alternative",
     "If True, the returned array will be sorted in descending order. "
     "If False, the returned array will be sorted in ascending order.", True),
    ("passive no-guarantee scope",
     "The documentation does not guarantee that the returned array will be "
     "sorted in ascending order.", False),
    ("passive uncertainty scope",
     "It is unclear whether the returned array will be sorted in ascending "
     "order.", False),
    ("passive exclusive condition",
     "The returned array will be sorted in ascending order only if the "
     "input values are comparable.", True),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    index = CRMSResearchIndex()
    index.add_document(
        PYTHON_SOURCE[0], PYTHON_SOURCE[1], PYTHON_SOURCE[3],
        PYTHON_SOURCE[2])
    for number, (name, text, should_propose) in enumerate(CASES):
        source_id = f"scope-control-{number}"
        index.add_document(
            source_id, name, text, f"https://scope-fixtures.invalid/{number}")
        candidate = extract_review_candidate(index, source_id)
        require((candidate is not None) is should_propose,
                f"{name}: expected proposal={should_propose}, got {candidate!r}")
        if candidate is not None:
            require(candidate["phrase"] == "sort the array in ascending order"
                    and candidate["prose"] == text
                    and index.resolve_citation(candidate["prose_citation"])
                        == text,
                    f"{name}: proposal phrase or citation drifted: {candidate!r}")
            if any(word in name for word in
                   ("condition", "parenthetical", "positive")):
                require(candidate["scope_notes"],
                        f"{name}: proposal dropped its condition: {candidate!r}")
        print(f"{name}: {'proposal' if candidate else 'rejected'}: PASS")
    for number, (name, text, should_propose) in enumerate(PASSIVE_CASES):
        source_id = f"passive-scope-control-{number}"
        index.add_document(
            source_id, name, text,
            f"https://passive-scope-fixtures.invalid/{number}")
        candidate = extract_passive_review_candidate(index, source_id)
        require((candidate is not None) is should_propose,
                f"{name}: expected proposal={should_propose}, got {candidate!r}")
        if candidate is not None:
            require(candidate["phrase"] == "sort in ascending order"
                    and candidate["prose"] in text
                    and index.resolve_citation(candidate["prose_citation"])
                        == candidate["prose"],
                    f"{name}: proposal phrase or citation drifted: {candidate!r}")
            if any(word in name for word in
                   ("condition", "asserted")):
                require(candidate["scope_notes"],
                        f"{name}: proposal dropped its condition: {candidate!r}")
        label = ("scoped proposal" if candidate and
                 any(word in name for word in
                     ("condition", "parenthetical", "asserted"))
                 else "proposal" if candidate else "rejected")
        print(f"{name}: {label}: PASS")
    positive_count = sum(should for _, _, should in (*CASES, *PASSIVE_CASES))
    negative_count = len(CASES) + len(PASSIVE_CASES) - positive_count
    print(f"scope controls: {positive_count} asserted/scoped proposals, "
          f"{negative_count} denied, uncertain, quoted, or non-instructional "
          "cases rejected")


if __name__ == "__main__":
    main()
