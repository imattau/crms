"""A pronoun date sentence binds only to the immediately preceding named subject.

Run with: python3 experiments/v1_547_pronoun_date_anchor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import _natural_when_evidence  # noqa: E402
from crms_research import CRMSResearchIndex  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def index_with(text: str) -> CRMSResearchIndex:
    index = CRMSResearchIndex()
    index.add_document("notes", "Date notes", text, "date.txt")
    return index


def main() -> None:
    text = ("The Eiffel Tower is a landmark in Paris. "
            "It was completed in 1889.")
    evidence = _natural_when_evidence(
        index_with(text), "When was the Eiffel Tower completed?")
    require(evidence is not None
            and evidence["text"] == ("The Eiffel Tower is a landmark in Paris. "
                                     "It was completed in 1889.")
            and evidence["location"] == "date.txt",
            f"a locally anchored pronoun date was not found: {evidence!r}")

    # The same wording without the article still anchors.
    evidence = _natural_when_evidence(
        index_with(text), "When was Eiffel Tower completed?")
    require(evidence is not None and "1889" in evidence["text"],
            f"determiner-less subject did not anchor: {evidence!r}")

    # A different immediate subject must not license the pronoun.
    mixed = ("The Eiffel Tower is a landmark in Paris. "
             "The Colosseum is an amphitheatre in Rome. "
             "It was completed in 80 CE.")
    evidence = _natural_when_evidence(
        index_with(mixed), "When was the Eiffel Tower completed?")
    require(evidence is None,
            f"a pronoun bound to a non-adjacent subject: {evidence!r}")

    # No preceding named subject: the pronoun has no anchor.
    orphan = "It was completed in 1889."
    evidence = _natural_when_evidence(
        index_with(orphan), "When was the Eiffel Tower completed?")
    require(evidence is None,
            f"an unanchored pronoun produced a date: {evidence!r}")

    # An explicit subject in the dated sentence still works without a pronoun.
    explicit = "The Eiffel Tower was completed in 1889."
    evidence = _natural_when_evidence(
        index_with(explicit), "When was the Eiffel Tower completed?")
    require(evidence is not None and "1889" in evidence["text"],
            f"an explicit dated subject was not found: {evidence!r}")

    # A negation between subject and date remains unavailable.
    negated = ("The Eiffel Tower is a landmark in Paris. "
               "It was not completed in 1889.")
    evidence = _natural_when_evidence(
        index_with(negated), "When was the Eiffel Tower completed?")
    require(evidence is None,
            f"a negated date was accepted: {evidence!r}")

    print("locally anchored pronoun date is found with its exact source: PASS")
    print("determiner-less subject still anchors: PASS")
    print("non-adjacent, orphan, negated controls abstain: PASS")
    print("explicit dated subject remains supported: PASS")


if __name__ == "__main__":
    main()
