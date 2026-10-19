"""Consonant-y past-tense forms match their grounded predicate lemma.

Run with: python3 experiments/v1_417_ied_relation_gate.py
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
    for present, past, lemma in (
        ("study", "studied", "study"),
        ("carry", "carried", "carry"),
        ("marry", "married", "marry"),
        ("try", "tried", "try"),
    ):
        require(_stem(present) == lemma and _stem(past) == lemma,
                f"consonant-y inflection mismatch: {present}/{past}: "
                f"{_stem(present)!r}/{_stem(past)!r}")
    for past, lemma in (("died", "die"), ("lied", "lie"), ("tied", "tie")):
        require(_stem(past) == lemma,
                f"final-e past tense was mis-stemmed: {past!r} -> {_stem(past)!r}")

    sentence = "Meridian Institute 0266 studied metallurgy."
    positive = gate_quoted_evidence(
        "What did Meridian Institute 0266 study?", [{"text": sentence}])
    require(positive["status"] == "accepted",
            f"same predicate across tense was rejected: {positive!r}")

    wrong_predicate = gate_quoted_evidence(
        "What did Meridian Institute 0266 investigate?", [{"text": sentence}])
    require(wrong_predicate["status"] != "accepted",
            f"shared entity terms bypassed relation support: {wrong_predicate!r}")

    wrong_entity = gate_quoted_evidence(
        "What did Meridian Institute 0267 study?", [{"text": sentence}])
    require(wrong_entity["status"] != "accepted",
            f"inflection matching bypassed entity grounding: {wrong_entity!r}")

    print("consonant-y present/past predicate normalization: PASS")
    print("final-e verbs, wrong predicates, and wrong entities controlled: PASS")


if __name__ == "__main__":
    main()
