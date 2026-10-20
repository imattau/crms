"""Teach a sum alias and transfer it to new facts, values, and clause order."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain
from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from v1_502_reasoned_numeric_aggregation import (
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


ALIAS = "add up every value"
REQUEST = "Add up every value in 41, 6, 41, and 10 that Tavi reaches."
REORDERED = "Tavi reaches some of 41, 6, 41, and 10. Add up every value."
UNKNOWN = "Tavi reaches some of 41, 6, 12, and 10. Add up every value."


def teach_alias(model: CRMSModel) -> None:
    examples = (
        ([2, 3], [5]), ([8, -2, 4], [10]), ([0, 0], [0]),
        ([4, 4, -1], [7]), ([1, 2, 3, 4], [10]), ([-3, -2], [-5]),
    )
    labeler = "codex:aggregate-alias-teacher"
    result = model.teach(
        ALIAS, examples,
        source_ids=[f"teacher:add-up:{i}" for i in range(len(examples))],
        labeler_ids=[labeler] * len(examples),
        instruction_source_ids=["teacher:exact-integer-sum"] * len(examples))
    seen = [list(values) for values, _ in examples]
    contrast_count = 0
    while result.status == "need_more_examples" and contrast_count < 8:
        probe = result.contrastive_input
        require(probe is not None and list(probe) not in seen,
                f"alias learner returned a repeated contrast: {result}")
        probe = list(probe)
        seen.append(probe)
        contrast_count += 1
        result = model.teach(
            ALIAS, [(probe, [sum(probe)])],
            source_ids=[f"teacher:add-up:contrast:{contrast_count}"],
            labeler_ids=[labeler],
            instruction_source_ids=["teacher:exact-integer-sum"])
    require(result.status == "learned"
            and result.procedure == [{"operation": "sum_values",
                                      "parameters": {}}]
            and contrast_count > 0,
            f"the alias did not learn exact summation: {result}")


def main() -> None:
    knowledge = build_knowledge()
    add_chain(knowledge, "Tavi", "Uma", "Vega", "41",
              "tavi:record-41", conclusion="none")
    add_chain(knowledge, "Tavi", "Wren", "Xeno", "6",
              "tavi:record-6", conclusion="none")
    knowledge.add_negative_fact(
        "Tavi", "reaches", "10", "tavi:record-10-negative")

    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    before = compose_verified_filter(REQUEST, knowledge, procedures)
    require(before is None,
            f"unlicensed operation alias was recognized before teaching: {before}")

    teach_alias(procedures)
    result = compose_verified_filter(REQUEST, knowledge, procedures)
    reordered = compose_verified_filter(REORDERED, knowledge, procedures)
    for request, candidate in ((REQUEST, result), (REORDERED, reordered)):
        require(candidate is not None and candidate.status == "answered"
                and candidate.included_values == (41, 6, 41)
                and candidate.excluded_negative == (10,)
                and candidate.output_values == (88,)
                and candidate.inference_proofs and candidate.procedure_records
                and "tavi:record-41" in candidate.evidence_sources
                and "tavi:record-6" in candidate.evidence_sources
                and "tavi:record-10-negative" in candidate.evidence_sources
                and any(record.get("labeler_id") ==
                        "codex:aggregate-alias-teacher"
                        for record in candidate.procedure_records),
                f"learned alias failed on request {request!r}: {candidate}")

    unknown = compose_verified_filter(UNKNOWN, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (12,)
            and not unknown.output_values,
            f"unknown member entered aggregate: {unknown}")
    checked = CRMSMath().ask("What is 41 + 6 + 41?")
    require(checked is not None and checked.status == "answered"
            and str(checked.value) == "88",
            f"independent arithmetic disagreed with composition: {checked}")

    with tempfile.TemporaryDirectory(prefix="crms-learned-alias-") as folder:
        root = Path(folder)
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
            (REORDERED, "why?"))
        require("Their total is 88." in output
                and "tavi:record-41" in output
                and "tavi:record-6" in output
                and "tavi:record-10-negative" in output
                and "codex:aggregate-alias-teacher" in output
                and "Because Tavi" in output
                and "Traceback" not in output,
                f"fresh copied-model chat failed to answer/explain:\n{output}")

    print("unlicensed alias abstains before examples: PASS")
    print("contrastively learned alias transfers to new values and a new entity: PASS")
    print("reordered clauses compose with inferred positives and explicit negative: PASS")
    print("independent arithmetic agrees; unknown member blocks output: PASS")
    print("SQLite fresh chat retains answer, explanation, and lineage: PASS")
    print("scope: supervised operation-alias transfer, not autonomous synonym discovery")


if __name__ == "__main__":
    main()
