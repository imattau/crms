"""Compose a task from a unique value set, stored claim, and learned phrase."""
from __future__ import annotations

import copy
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from v1_502_reasoned_numeric_aggregation import (
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


REQUESTS = (
    "Mira reaches some of 23, 5, 23, and 8. Sum every value.",
    "From 23, 5, 23, and 8, sum every value Mira reaches.",
    "For 23, 5, 23, and 8, sum every value Mira reaches.",
)
LINKED_FILTER_SUM = (
    "Which values in 23, 5, 23, and 8 does Mira reach, and what do they sum to?"
)
WH_TOTAL = (
    "What is the total of the values Mira reaches among 23, 5, 23, and 8?"
)
UNKNOWN_LINKED_FILTER_SUM = (
    "Which values in 23, 5, 11, and 8 does Mira reach, and what do they sum to?"
)
UNKNOWN_REQUEST = "Mira reaches some of 23, 5, 11, and 8. Sum every value."
UNLICENSED_ALIAS = "Mira reaches some of 23, 5, 23, and 8. Add up every value."
MULTIPLE_LISTS = (
    "Mira reaches some of 23, 5, 23, and 8. Sum every value from 1, 2, and 3."
)
MENTION_ONLY = (
    "The phrase sum every value appears in the notes. Mira reaches some of "
    "23, 5, 23, and 8."
)


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)

    answers = [compose_verified_filter(request, knowledge, procedures)
               for request in REQUESTS]
    require(all(result is not None and result.status == "answered"
                and result.included_values == (23, 5, 23)
                and result.excluded_negative == (8,)
                and result.output_values == (51,)
                for result in answers),
            f"the same licensed parts did not compose across clause order: {answers}")

    linked = compose_verified_filter(LINKED_FILTER_SUM, knowledge, procedures)
    require(linked is not None and linked.status == "answered"
            and linked.included_values == (23, 5, 23)
            and linked.output_values == (51,),
            f"the linked WH filter-and-sum question failed: {linked}")
    wh_total = compose_verified_filter(WH_TOTAL, knowledge, procedures)
    require(wh_total is not None and wh_total.status == "answered"
            and wh_total.included_values == (23, 5, 23)
            and wh_total.output_values == (51,),
            f"the WH-total request failed: {wh_total}")
    unknown_linked = compose_verified_filter(
        UNKNOWN_LINKED_FILTER_SUM, knowledge, procedures)
    require(unknown_linked is not None and unknown_linked.status == "unknown"
            and unknown_linked.unresolved_values == (11,)
            and not unknown_linked.output_values,
            f"linked WH composition used an unknown value: {unknown_linked}")

    unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (11,)
            and not unknown.output_values,
            f"unknown value entered a generic composition: {unknown}")
    require(compose_verified_filter(UNLICENSED_ALIAS, knowledge, procedures)
            is None,
            "an unlicensed operation alias was silently normalized")
    require(compose_verified_filter(MULTIPLE_LISTS, knowledge, procedures)
            is None,
            "a request with multiple numeric sets was silently interpreted")
    require(compose_verified_filter(MENTION_ONLY, knowledge, procedures) is None,
            "mentioning a learned phrase without requesting it ran the procedure")

    ambiguous = copy.deepcopy(knowledge)
    ambiguous.add_fact("Ada", "reaches", "5", "ada:record-5")
    multiple_claims = (
        "Mira reaches some of 23, 5, 23, and 8; Ada reaches some too. "
        "Sum every value."
    )
    require(compose_verified_filter(multiple_claims, ambiguous, procedures)
            is None,
            "multiple stored claims did not force abstention")

    # Check one reordered request through a clean chat process and copied model.
    with tempfile.TemporaryDirectory(prefix="crms-generic-composition-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedure_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        CRMSResearchIndex().save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        session = root / "session"
        session.mkdir()
        for source in (knowledge_path, procedure_path, index_path,
                       root / "math.json", root / "translations.json"):
            shutil.copy2(source, session / source.name)
        output = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / index_path.name,
            (REQUESTS[0], LINKED_FILTER_SUM, WH_TOTAL, "why?"))
        require("Their total is 51." in output
                and "Verified values satisfying the relation 'Mira reaches': "
                    "[23, 5, 23]" in output
                and "mira:record-23" in output
                and "mira:record-5" in output
                and "mira:record-8-negative" in output
                and "Because Mira" in output
                and "Handling 2 explicit questions separately." not in output
                and "Traceback" not in output,
                f"fresh chat failed to retain proof-grounded composition:\n{output}")

    print("compositional parsing handles three reordered forms: PASS")
    print("linked WH filter-and-sum stays one task and rejects unresolved values: PASS")
    print("WH-total request selects values by proof before aggregation: PASS")
    print("positive, negative, learned-procedure and proof gates remain active: PASS")
    print("unknown values, competing claims, multiple lists, and unlicensed aliases abstain: PASS")
    print("copy-only fresh chat answers and explains the reordered request: PASS")
    print("scope: bounded list aggregation; broad language transfer remains untested")


if __name__ == "__main__":
    main()
