"""Teach and apply a sum-first request frame over proof-selected values.

The request frame is a new development example, authored during the current
turn. Results measure this controlled transfer only; they are not an
independent-language benchmark.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from v1_502_reasoned_numeric_aggregation import build_knowledge
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


REQUEST = "Sum every value in 23, 5, 23, and 8 that Mira reaches."
UNKNOWN_REQUEST = "Sum every value in 23, 5, 11, and 8 that Mira reaches."
PHRASE = "sum every value"


def teach_sum_phrase(model: CRMSModel) -> None:
    examples = (
        ([3, 1, 2], [6]), ([5, -1, 4], [8]), ([4, 1, 4, -2], [7]),
        ([0, 0], [0]), ([9, -3], [6]), ([1, 2, 3], [6]),
    )
    teacher = "codex:sum-first-phrase-teacher"
    source = "teacher:exact-integer-sum"
    result = model.teach(
        PHRASE, examples,
        source_ids=[f"teacher:sum-first:{i}" for i in range(len(examples))],
        labeler_ids=[teacher] * len(examples),
        instruction_source_ids=[source] * len(examples))
    contrast_inputs = [list(values) for values, _ in examples]
    contrast_count = 0
    while result.status == "need_more_examples" and contrast_count < 8:
        probe = result.contrastive_input
        require(probe is not None and list(probe) not in contrast_inputs,
                f"sum-first learner returned a repeated contrast: {result}")
        probe = list(probe)
        contrast_inputs.append(probe)
        contrast_count += 1
        result = model.teach(
            PHRASE, [(probe, [sum(probe)])],
            source_ids=[f"teacher:sum-first:contrast:{contrast_count}"],
            labeler_ids=[teacher], instruction_source_ids=[source])
    require(result.status == "learned"
            and result.procedure == [{"operation": "sum_values",
                                      "parameters": {}}]
            and contrast_count > 0,
            f"new sum wording did not learn the exact aggregate: {result}")


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()

    before = compose_verified_filter(REQUEST, knowledge, procedures)
    require(before is not None and before.status == "unsupported_procedure"
            and not before.output_values,
            f"untaught sum-first phrase unexpectedly ran: {before}")

    teach_sum_phrase(procedures)
    result = compose_verified_filter(REQUEST, knowledge, procedures)
    require(result is not None and result.status == "answered"
            and result.included_values == (23, 5, 23)
            and result.excluded_negative == (8,)
            and result.output_values == (51,)
            and result.inference_proofs and result.procedure_records
            and "mira:record-23" in result.evidence_sources
            and "mira:record-5" in result.evidence_sources
            and "mira:record-8-negative" in result.evidence_sources
            and any(record.get("labeler_id") ==
                    "codex:sum-first-phrase-teacher"
                    for record in result.procedure_records),
            f"learned sum-first composition failed: {result}")

    unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (11,)
            and not unknown.output_values,
            f"an unknown value entered the sum-first aggregate: {unknown}")

    # Independently recompute the checked proof-selected values.
    exact = CRMSMath().ask("What is 23 + 5 + 23?")
    require(exact is not None and exact.status == "answered"
            and str(exact.value) == "51",
            f"independent arithmetic disagreed: {exact}")

    with tempfile.TemporaryDirectory(prefix="crms-sum-first-") as folder:
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
        for source_path in (knowledge_path, procedure_path, index_path,
                            root / "math.json", root / "translations.json"):
            shutil.copy2(source_path, session / source_path.name)
        output = run_chat(
            session, session / knowledge_path.name,
            session / procedure_path.name, session / index_path.name,
            (REQUEST, "why?"))
        require("Their total is 51." in output
                and "mira:record-23" in output
                and "mira:record-5" in output
                and "mira:record-8-negative" in output
                and "codex:sum-first-phrase-teacher" in output
                and "Because Mira" in output
                and "Traceback" not in output,
                f"fresh chat did not answer/explain the composition:\n{output}")

    print("sum-first frame abstains before operation phrase is taught: PASS")
    print("contrastively learned phrase composes with verified relation proofs: PASS")
    print("independent exact arithmetic agrees; unknown values block output: PASS")
    print("SQLite fresh-process chat retains proof, teacher, and negative lineage: PASS")
    print("scope: one controlled alternate request frame, not broad math transfer")


if __name__ == "__main__":
    main()
