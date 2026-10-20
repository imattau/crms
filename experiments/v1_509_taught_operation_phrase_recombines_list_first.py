"""Learn an operation phrase, then recombine it in a list-first request.

The request wording corresponds to the frozen list-first gap in v1_504. The
phrase remains unsupported until explicitly taught; after teaching, the
generic composer should combine it with proof-backed selection without a new
phrase-specific parser rule.
"""
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
from v1_502_reasoned_numeric_aggregation import build_knowledge, sum_training_data
from v1_503_sum_first_reasoned_composition import teach_sum_phrase
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


PHRASE = "add together only the numbers"
REQUEST = (
    "From 23, 5, 23, and 8, add together only the numbers Mira reaches."
)
TRANSFER = (
    "From 41, 6, 41, and 10, add together only the numbers Tavi reaches."
)
UNKNOWN = (
    "From 41, 6, 12, and 10, add together only the numbers Tavi reaches."
)


def teach_phrase(model: CRMSModel) -> None:
    examples = (
        ([2, 3], [5]), ([8, -2, 4], [10]), ([0, 0], [0]),
        ([4, 4, -1], [7]), ([1, 2, 3, 4], [10]), ([-3, -2], [-5]),
    )
    labeler = "codex:list-first-sum-teacher"
    result = model.teach(
        PHRASE, examples,
        source_ids=[f"teacher:add-together:{i}" for i in range(len(examples))],
        labeler_ids=[labeler] * len(examples),
        instruction_source_ids=["teacher:exact-integer-sum"] * len(examples))
    seen = [list(values) for values, _ in examples]
    contrast = 0
    while result.status == "need_more_examples" and contrast < 8:
        probe = result.contrastive_input
        require(probe is not None and list(probe) not in seen,
                f"operation learner repeated a contrast: {result}")
        probe = list(probe)
        seen.append(probe)
        contrast += 1
        result = model.teach(
            PHRASE, [(probe, [sum(probe)])],
            source_ids=[f"teacher:add-together:contrast:{contrast}"],
            labeler_ids=[labeler],
            instruction_source_ids=["teacher:exact-integer-sum"])
    require(result.status == "learned"
            and result.procedure == [{"operation": "sum_values",
                                      "parameters": {}}],
            f"phrase did not learn exact summation: {result}")


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
    require(compose_verified_filter(REQUEST, knowledge, procedures) is None,
            "the held-out operation phrase worked before it was taught")
    teach_phrase(procedures)

    for request, expected_values, expected_total in (
            (REQUEST, (23, 5, 23), 51), (TRANSFER, (41, 6, 41), 88)):
        result = compose_verified_filter(request, knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.included_values == expected_values
                and result.output_values == (expected_total,)
                and result.inference_proofs and result.procedure_records
                and any(record.get("phrase") == PHRASE
                        and record.get("labeler_id")
                        == "codex:list-first-sum-teacher"
                        for record in result.procedure_records),
                f"learned phrase failed to recombine for {request!r}: {result}")

    unknown = compose_verified_filter(UNKNOWN, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (12,)
            and not unknown.output_values,
            f"unknown value entered the learned aggregate: {unknown}")
    exact = CRMSMath().ask("What is 41 + 6 + 41?")
    require(exact is not None and exact.status == "answered"
            and str(exact.value) == "88",
            f"independent arithmetic disagreed: {exact}")

    with tempfile.TemporaryDirectory(prefix="crms-list-first-sum-") as folder:
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
            (TRANSFER, "why?"))
        require("Their total is 88." in output
                and "tavi:record-41" in output
                and "tavi:record-6" in output
                and "tavi:record-10-negative" in output
                and "codex:list-first-sum-teacher" in output
                and "Because Tavi" in output
                and "Traceback" not in output,
                f"copied-model chat lost the recombination or lineage:\n{output}")

    print("unlicensed phrase abstains before teaching: PASS")
    print("contrastively taught phrase transfers to the frozen request and a new entity/value set: PASS")
    print("proof selection, explicit negatives, and independent arithmetic remain valid: PASS")
    print("copied-model chat explains the result with rule/procedure lineage: PASS")
    print("unknown list members block aggregation: PASS")
    print("scope: teacher-labeled operation phrase transfer, not autonomous synonym discovery")


if __name__ == "__main__":
    main()
