"""Regular -es morphology transfers exact predicates across voice.

This is a narrow lexical-normalization regression, not synonym induction.
Run with: python3 experiments/v1_416_regular_es_gate_morphology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_nl_gate import _stem, gate_quoted_evidence  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    for present, past, expected in (
        ("crosses", "crossed", "cross"),
        ("passes", "passed", "pass"),
        ("boxes", "boxed", "box"),
        ("watches", "watched", "watch"),
        ("goes", "went", "go"),
    ):
        require(_stem(present) == expected and _stem(past) == expected,
                f"inflection mismatch: {present}/{past}: "
                f"{_stem(present)!r}/{_stem(past)!r}")
    for word, expected in (("sizes", "size"), ("shoes", "shoe"),
                           ("uses", "use")):
        require(_stem(word) == expected,
                f"ordinary final-e word was over-stripped: {word!r} -> "
                f"{_stem(word)!r}")

    sentence = "Nacre City 0133 is crossed by Serein River 0133."
    positive = gate_quoted_evidence(
        "What body of water crosses Nacre City 0133?", [{"text": sentence}])
    require(positive["status"] == "accepted"
            and positive["evidence"]["text"] == sentence,
            f"active question did not match exact passive predicate: {positive!r}")

    wrong_entity = gate_quoted_evidence(
        "What body of water crosses Nacre City 0134?", [{"text": sentence}])
    require(wrong_entity["status"] != "accepted",
            f"morphology change bypassed the numbered-entity check: {wrong_entity!r}")

    wrong_relation = gate_quoted_evidence(
        "Which river flows through Nacre City 0133?", [{"text": sentence}])
    require(wrong_relation["status"] != "accepted",
            f"morphology change licensed an unrelated predicate: {wrong_relation!r}")

    print("regular -es active/passive predicate normalization: PASS")
    print("wrong entity and wrong relation remain rejected: PASS")


if __name__ == "__main__":
    main()
