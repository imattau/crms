"""Parity between the legacy regex composition and the typed plan path.

The new path shares request parsing with the old one but executes selection and
procedure application as independently verified plan steps. Every observable
field, including rendered text, must match before chat may switch paths.

Run with: python3 experiments/v1_552_family_a_plan_parity.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_500_learned_and_reasoned_composition import learn_components  # noqa: E402
from v1_502_reasoned_numeric_aggregation import (  # noqa: E402
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase  # noqa: E402

from crms_task_composition import (  # noqa: E402
    compose_verified_filter, compose_verified_filter_via_plan,
)


LINKED = (
    "Which values in 23, 5, 23, and 8 does Mira reach, and what do they sum to?"
)
WH_TOTAL = (
    "What is the total of the values Mira reaches among 23, 5, 23, and 8?"
)
GENERIC = (
    "Mira reaches some of 23, 5, 23, and 8. Sum every value.",
    "From 23, 5, 23, and 8, sum every value Mira reaches.",
    "For 23, 5, 23, and 8, sum every value Mira reaches.",
)
UNKNOWN_LINKED = (
    "Which values in 23, 5, 11, and 8 does Mira reach, and what do they sum to?"
)
UNKNOWN_GENERIC = "Mira reaches some of 23, 5, 11, and 8. Sum every value."
MORPHOLOGY = (
    "From 23, 5, 23, and 8, keep the values Mira reaches, then "
    "reversing the list."
)
UNLICENSED_ALIAS = "Mira reaches some of 23, 5, 23, and 8. Add up every value."
MULTIPLE_LISTS = (
    "Mira reaches some of 23, 5, 23, and 8. Sum every value from 1, 2, and 3."
)
MENTION_ONLY = (
    "The phrase sum every value appears in the notes. Mira reaches some of "
    "23, 5, 23, and 8."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def snapshot(result):
    if result is None:
        return None
    return {
        name: getattr(result, name)
        for name in (
            "status", "text", "subject", "relation", "input_values",
            "included_values", "excluded_negative", "unresolved_values",
            "output_values", "procedure", "evidence_sources", "proof_checks",
            "evidence", "inference_proofs", "procedure_records",
            "language_evidence",
        )
    }


def compare(label: str, request: str, knowledge, procedures) -> None:
    old = compose_verified_filter(request, knowledge, procedures)
    new = compose_verified_filter_via_plan(request, knowledge, procedures)
    old_snapshot, new_snapshot = snapshot(old), snapshot(new)
    require(old_snapshot == new_snapshot,
            f"{label}: legacy and plan paths disagree\n"
            f"  request: {request}\n"
            f"  legacy: {old_snapshot}\n"
            f"  plan:   {new_snapshot}")


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    no_sum = learn_components()

    compare("linked filter-and-sum", LINKED, knowledge, procedures)
    compare("WH total", WH_TOTAL, knowledge, procedures)
    for index, request in enumerate(GENERIC):
        compare(f"generic clause order {index + 1}", request, knowledge,
                procedures)
    compare("linked unknown", UNKNOWN_LINKED, knowledge, procedures)
    compare("generic unknown", UNKNOWN_GENERIC, knowledge, procedures)
    compare("licensed gerund", MORPHOLOGY, knowledge, procedures)
    compare("untaught aggregate", LINKED, knowledge, no_sum)
    compare("unlicensed alias", UNLICENSED_ALIAS, knowledge, procedures)
    compare("multiple value sets", MULTIPLE_LISTS, knowledge, procedures)
    compare("mention without request", MENTION_ONLY, knowledge, procedures)

    conflict = copy.deepcopy(knowledge)
    conflict.add_negative_fact("Mira", "reaches", "23", "conflict:record-23")
    compare("positive and negative proof", LINKED, conflict, procedures)

    ambiguous = copy.deepcopy(knowledge)
    ambiguous.add_fact("Ada", "reaches", "5", "ada:record-5")
    multiple_claims = (
        "Mira reaches some of 23, 5, 23, and 8; Ada reaches some too. "
        "Sum every value."
    )
    compare("ambiguous claim", multiple_claims, ambiguous, procedures)

    # Outside the explicit frame both paths must stay outside it.
    for label, request in (
            ("plain question", "Who reaches 23?"),
            ("no numeric set", "Mira reaches some values. Sum every value."),
            ("empty", ""),
    ):
        old = compose_verified_filter(request, knowledge, procedures)
        new = compose_verified_filter_via_plan(request, knowledge, procedures)
        require(old is None and new is None,
                f"{label}: a foreign request entered composition: {old} {new}")

    print("linked, WH, and reordered generic requests: PASS")
    print("unknown, conflict, untaught aggregate, and alias controls: PASS")
    print("licensed morphology and rendered text parity: PASS")
    print("foreign requests remain outside the frame: PASS")


if __name__ == "__main__":
    main()
