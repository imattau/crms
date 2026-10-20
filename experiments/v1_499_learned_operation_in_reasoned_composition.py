"""Learn one operation from examples and reuse it in proof-backed chat composition.

The operation phrase and its contrastive label are explicitly teacher-supplied.
The target sequence is not directly taught: CRMS must combine the learned
stable-deduplication procedure with an existing reverse procedure and learned
sequence evidence, after the knowledge engine verifies every list member.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_492_reasoned_filter_language_coverage import (
    build_case, learn_connective_procedures, teach_relation_surface,
)
from v1_497_composition_derived_practice import run_chat, require
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


REQUEST = (
    "From values 4, 12, 4, 9, and 7, keep only the values Nia reaches, then "
    "deduplicate the values then reverse the list."
)
UNLICENSED = (
    "From values 4, 12, 4, 9, and 7, keep only the values Nia reaches, then "
    "remove repeats then reverse the list."
)


def stable_unique(values: list[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def main() -> None:
    knowledge, _ = build_case()
    procedures = learn_connective_procedures()
    index = CRMSResearchIndex()
    teach_relation_surface(knowledge, index)

    before = compose_verified_filter(REQUEST, knowledge, procedures)
    require(before is not None and before.status == "unsupported_procedure"
            and not before.output_values,
            f"unlearned operation unexpectedly composed: {before}")

    teaching_inputs = (
        [12, 4, 12, 9, 7], [4, 12, 4, 9, 7], [9, 12, 4, 12, 7],
        [7, 4, 9, 12, 4], [12, 9, 7, 4, 12],
    )
    phrase = "deduplicate the values"
    labeler = "codex:deduplication-teacher"
    instruction_source = "reviewed:stable-deduplication"
    initial = procedures.teach(
        phrase,
        [(values, stable_unique(values)) for values in teaching_inputs],
        source_ids=[f"teacher:deduplicate:{index}" for index in range(len(teaching_inputs))],
        labeler_ids=[labeler] * len(teaching_inputs),
        instruction_source_ids=[instruction_source] * len(teaching_inputs))
    require(initial.status == "need_more_examples"
            and initial.contrastive_input is not None,
            f"the learner did not request a discriminating example: {initial}")
    contrast = list(initial.contrastive_input)
    require(contrast not in teaching_inputs,
            f"contrastive input was already taught: {contrast}")
    resolved = procedures.teach(
        phrase, [(contrast, stable_unique(contrast))],
        source_ids=["teacher:deduplicate:contrastive"],
        labeler_ids=[labeler],
        instruction_source_ids=[instruction_source])
    require(resolved.status == "learned"
            and resolved.procedure == [{"operation": "stable_unique",
                                        "parameters": {}}],
            f"contrastive example did not resolve the procedure: {resolved}")

    heldout_operation = procedures.predict(
        phrase, [11, 2, 11, 6, 2])
    require(heldout_operation.status == "ok"
            and heldout_operation.output == [11, 2, 6],
            f"learned operation did not transfer to a new input: {heldout_operation}")

    unsupported = compose_verified_filter(UNLICENSED, knowledge, procedures)
    require(unsupported is not None
            and unsupported.status == "unsupported_procedure"
            and not unsupported.output_values,
            f"one learned phrase licensed an unprovided alias: {unsupported}")

    composed = compose_verified_filter(REQUEST, knowledge, procedures)
    require(composed is not None and composed.status == "answered"
            and composed.included_values == (4, 12, 4, 9)
            and composed.excluded_negative == (7,)
            and composed.output_values == (9, 12, 4)
            and composed.inference_proofs
            and composed.procedure_records
            and any(record.get("labeler_id") == labeler
                    for record in composed.procedure_records),
            f"learned operation did not join verified composition: {composed}")

    with tempfile.TemporaryDirectory(prefix="crms-learned-operation-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedure_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        index.save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        # Reload into a clean runtime with no prior dialogue or feedback state.
        session = root / "session"
        session.mkdir()
        for source in (knowledge_path, procedure_path, index_path,
                       root / "math.json", root / "translations.json"):
            shutil.copy2(source, session / source.name)
        output = run_chat(session, session / knowledge_path.name,
                          session / procedure_path.name,
                          session / index_path.name, (REQUEST, "why?"))
        require("[9, 12, 4]" in output
                and "runtime:record-12" in output
                and "runtime:record-7-negative" in output
                and labeler in output
                and "Because Nia" in output
                and "Traceback" not in output,
                f"fresh chat did not explain the learned composition:\n{output}")

    print("unlearned operation abstains before examples: PASS")
    print("a contrastive example resolves the learned operation: PASS")
    print("learned operation applies to a held-out input: PASS")
    print("learned operation combines with reasoning and a sequence rule: PASS")
    print("fresh chat reloads, cites evidence, and explains the composed proof: PASS")
    print("unsupported alias remains unsupported: PASS")
    print("scope: teacher-supervised operation learning, not autonomous self-learning")


if __name__ == "__main__":
    main()
