"""Learn and verify a math aggregate over proof-selected values in chat."""
from __future__ import annotations

import shutil
import sys
import tempfile
import copy
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain, discover_and_accept
from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from crms_knowledge import CRMSKnowledgeBase
from crms_math import CRMSMath, render as render_math
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


REQUEST = (
    "Filter 23, 5, 23, and 8 to values Mira reaches, then sum the values."
)
UNKNOWN_REQUEST = (
    "Filter 23, 5, and 11 to values Mira reaches, then sum the values."
)
CONFLICT_REQUEST = (
    "Filter 23, 5, and 8 to values Mira reaches, then sum the values."
)


def sum_training_data(model: CRMSModel) -> None:
    phrase = "sum the values"
    labeler = "codex:sum-teacher"
    instruction_source = "teacher:exact-integer-sum"
    examples = (
        ([3, 1, 2], [6]), ([5, -1, 4], [8]), ([4, 1, 4, -2], [7]),
        ([0, 0], [0]), ([9, -3], [6]), ([1, 2, 3], [6]),
    )
    result = model.teach(
        phrase, examples,
        source_ids=[f"teacher:sum:initial:{index}"
                    for index in range(len(examples))],
        labeler_ids=[labeler] * len(examples),
        instruction_source_ids=[instruction_source] * len(examples))
    probe_inputs = [list(values) for values, _output in examples]
    contrast_count = 0
    while result.status == "need_more_examples" and contrast_count < 8:
        probe = result.contrastive_input
        require(probe is not None and probe not in probe_inputs,
                f"sum learner returned a missing/repeated contrast: {result}")
        probe = list(probe)
        probe_inputs.append(probe)
        contrast_count += 1
        result = model.teach(
            phrase, [(probe, [sum(probe)])],
            source_ids=[f"teacher:sum:contrast:{contrast_count}"],
            labeler_ids=[labeler],
            instruction_source_ids=[instruction_source])
    require(result.status == "learned"
            and result.procedure == [{"operation": "sum_values",
                                      "parameters": {}}]
            and contrast_count > 0,
            f"sum did not resolve to one exact aggregate procedure: {result}")


def build_knowledge() -> CRMSKnowledgeBase:
    knowledge = CRMSKnowledgeBase()
    discover_and_accept(knowledge)
    add_chain(knowledge, "Mira", "Nell", "Quartz", "23",
              "mira:record-23", conclusion="none")
    add_chain(knowledge, "Mira", "Omar", "Ridge", "5",
              "mira:record-5", conclusion="none")
    knowledge.add_negative_fact(
        "Mira", "reaches", "8", "mira:record-8-negative")
    return knowledge


def main() -> None:
    procedures = learn_components()
    sum_training_data(procedures)
    knowledge = build_knowledge()

    result = compose_verified_filter(REQUEST, knowledge, procedures)
    require(result is not None and result.status == "answered"
            and result.included_values == (23, 5, 23)
            and result.excluded_negative == (8,)
            and result.output_values == (51,)
            and result.inference_proofs
            and "mira:record-23" in result.evidence_sources
            and "mira:record-5" in result.evidence_sources
            and "mira:record-8-negative" in result.evidence_sources
            and "Verified values satisfying the relation 'Mira reaches': "
                "[23, 5, 23]" in result.text
            and "Their total is 51." in result.text
            and any(record.get("labeler_id") == "codex:sum-teacher"
                    for record in result.procedure_records),
            f"proof-filtered sum was not composed correctly: {result}")

    # Independent exact arithmetic re-evaluates the verified included values.
    exact = CRMSMath().ask("What is 23 + 5 + 23?")
    require(exact is not None and exact.status == "answered"
            and str(exact.value) == "51"
            and "51" in render_math(exact),
            f"exact math verifier disagreed with the learned aggregate: {exact}")

    unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (11,)
            and not unknown.output_values,
            f"unknown value entered the aggregate: {unknown}")
    conflicted = copy.deepcopy(knowledge)
    conflicted.add_fact("Mira", "reaches", "23", "mira:conflict-positive")
    conflicted.add_negative_fact(
        "Mira", "reaches", "23", "mira:conflict-negative")
    conflict = compose_verified_filter(CONFLICT_REQUEST, conflicted, procedures)
    require(conflict is not None and conflict.status == "conflict"
            and not conflict.output_values,
            f"conflicted evidence entered the aggregate: {conflict}")

    with tempfile.TemporaryDirectory(prefix="crms-reasoned-sum-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedure_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        CRMSResearchIndex().save(index_path)
        math_model = CRMSMath()
        math_model.save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        session = root / "session"
        session.mkdir()
        for source in (knowledge_path, procedure_path, index_path,
                       root / "math.json", root / "translations.json"):
            shutil.copy2(source, session / source.name)
        output = run_chat(session, session / knowledge_path.name,
                          session / procedure_path.name,
                          session / index_path.name, (REQUEST, "why?"))
        require("Verified values satisfying the relation 'Mira reaches': "
                "[23, 5, 23]" in output
                and "Their total is 51." in output
                and "mira:record-23" in output
                and "mira:record-5" in output
                and "mira:record-8-negative" in output
                and "codex:sum-teacher" in output
                and "Because Mira" in output
                and "Traceback" not in output,
                f"fresh chat did not produce/explain the verified aggregate:\n"
                f"{output}")

    print("contrastive examples resolve exact summation procedure: PASS")
    print("verified reasoning selects values before learned aggregation: PASS")
    print("independent exact arithmetic agrees with aggregate output: PASS")
    print("positive, negative, and procedure lineage survive fresh chat: PASS")
    print("unknown and conflicted evidence block the aggregate: PASS")
    print("scope: controlled reasoning→math composition, not general word problems")


if __name__ == "__main__":
    main()
