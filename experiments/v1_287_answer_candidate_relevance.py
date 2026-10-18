"""Check that review proposals do not distract from supported answers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _candidates_relevant_to_answer
from crms_knowledge import FactCandidate


def main() -> None:
    relevant = FactCandidate(
        "Guido van Rossum", "created", "Python", "source-python",
        "<subject> created <object>",
        "Guido van Rossum created Python.", True)
    unrelated = FactCandidate(
        "Dennis Ritchie", "created", "the C language", "source-c",
        "<subject> created <object>",
        "Dennis Ritchie created the C language.", True)
    retained = _candidates_relevant_to_answer(
        "Who created Python?", [relevant, unrelated])
    if retained != [relevant]:
        raise SystemExit(
            "a direct Python answer would surface an unrelated C candidate: "
            f"{retained}")

    sparse_query_candidates = _candidates_relevant_to_answer(
        "What is it?", [relevant, unrelated])
    if sparse_query_candidates != [relevant, unrelated]:
        raise SystemExit(
            "sparse queries should retain proposals because relevance is "
            "not safely measurable")

    print("answer candidate relevance: PASS")
    print("the Python proposal remains available; the unrelated C proposal "
          "is suppressed when a supported answer already exists")


if __name__ == "__main__":
    main()
