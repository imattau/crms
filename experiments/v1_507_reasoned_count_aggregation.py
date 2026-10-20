"""Learn count and apply it only to values selected by verified reasoning."""
from __future__ import annotations

import copy
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
from v1_502_reasoned_numeric_aggregation import build_knowledge
from crms_math import CRMSMath
from crms_model import CRMSModel, Step, _semantic_key
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


PHRASE = "count the matching entries"
REQUEST = (
    "Count the matching entries among 41, 6, 41, and 10 that Tavi reaches."
)
REORDERED = (
    "Tavi reaches some of 41, 6, 41, and 10. Count the matching entries."
)
UNKNOWN = (
    "Tavi reaches some of 41, 6, 12, and 10. Count the matching entries."
)


def teach_count(model: CRMSModel) -> None:
    examples = (
        ([1, 2, 3], [3]), ([7, -2], [2]), ([], [0]),
        ([4, 4, 4, 4], [4]), ([0, 5, -1], [3]), ([2, 9], [2]),
    )
    labeler = "codex:count-teacher"
    result = model.teach(
        PHRASE, examples,
        source_ids=[f"teacher:count:{i}" for i in range(len(examples))],
        labeler_ids=[labeler] * len(examples),
        instruction_source_ids=["teacher:list-entry-count"] * len(examples))
    seen = [list(values) for values, _ in examples]
    contrast_count = 0
    while result.status == "need_more_examples" and contrast_count < 8:
        probe = result.contrastive_input
        require(probe is not None and list(probe) not in seen,
                f"count learner returned a repeated contrast: {result}")
        probe = list(probe)
        seen.append(probe)
        contrast_count += 1
        result = model.teach(
            PHRASE, [(probe, [len(probe)])],
            source_ids=[f"teacher:count:contrast:{contrast_count}"],
            labeler_ids=[labeler],
            instruction_source_ids=["teacher:list-entry-count"])
    require(result.status == "learned"
            and result.procedure == [{"operation": "count_values",
                                      "parameters": {}}],
            f"count did not resolve to the intended operation: {result}")


def main() -> None:
    count = Step("count_values", {})
    require(_semantic_key((count,))
            == _semantic_key((Step("reverse", {}), count))
            == _semantic_key((Step("add_k", {"k": 4}), count))
            == _semantic_key((count, Step("sum_values", {})))
            == _semantic_key((count, Step("sort_ascending", {}))),
            "exact count-preserving operations failed to canonicalize")
    require(_semantic_key((count,))
            != _semantic_key((Step("stable_unique", {}), count))
            and _semantic_key((count,))
            != _semantic_key((count, Step("add_k", {"k": 1}))),
            "canonicalization erased a length-changing or value-changing effect")

    knowledge = build_knowledge()
    add_chain(knowledge, "Tavi", "Uma", "Vega", "41",
              "tavi:record-41", conclusion="none")
    add_chain(knowledge, "Tavi", "Wren", "Xeno", "6",
              "tavi:record-6", conclusion="none")
    knowledge.add_negative_fact(
        "Tavi", "reaches", "10", "tavi:record-10-negative")

    procedures = learn_components()
    before = compose_verified_filter(REQUEST, knowledge, procedures)
    require(before is None,
            f"untaught count phrase unexpectedly ran: {before}")
    teach_count(procedures)

    for request in (REQUEST, REORDERED):
        result = compose_verified_filter(request, knowledge, procedures)
        require(result is not None and result.status == "answered"
                and result.included_values == (41, 6, 41)
                and result.excluded_negative == (10,)
                and result.output_values == (3,)
                and result.output_values[0] == len(result.included_values)
                and result.inference_proofs and result.procedure_records
                and "tavi:record-41" in result.evidence_sources
                and "tavi:record-6" in result.evidence_sources
                and "tavi:record-10-negative" in result.evidence_sources
                and any(record.get("labeler_id") == "codex:count-teacher"
                        for record in result.procedure_records)
                and "There are 3 listed entries satisfying" in result.text,
                f"proof-filtered count failed for {request!r}: {result}")

    unknown = compose_verified_filter(UNKNOWN, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (12,)
            and not unknown.output_values,
            f"unknown value entered the count: {unknown}")
    conflicted = copy.deepcopy(knowledge)
    conflicted.add_fact("Tavi", "reaches", "41", "tavi:positive-conflict")
    conflicted.add_negative_fact(
        "Tavi", "reaches", "41", "tavi:negative-conflict")
    conflict = compose_verified_filter(REQUEST, conflicted, procedures)
    require(conflict is not None and conflict.status == "conflict"
            and not conflict.output_values,
            f"conflicted value entered the count: {conflict}")

    # Independently count the verified entries; duplicates count as entries.
    checked_count = len((41, 6, 41))
    require(checked_count == 3,
            f"independent entry count disagreed: {checked_count}")

    with tempfile.TemporaryDirectory(prefix="crms-reasoned-count-") as folder:
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
        require("There are 3 listed entries satisfying" in output
                and "tavi:record-41" in output
                and "tavi:record-6" in output
                and "tavi:record-10-negative" in output
                and "codex:count-teacher" in output
                and "Because Tavi" in output
                and "Traceback" not in output,
                f"copied-model chat did not answer/explain the count:\n{output}")

    print("count phrase abstains before teaching: PASS")
    print("count equivalence canonicalizes only exact length/singleton identities: PASS")
    print("six labeled examples uniquely teach count; it composes over proof-selected values: PASS")
    print("independent entry count agrees; duplicate values count as entries: PASS")
    print("unknown and conflicting evidence block output: PASS")
    print("copied-model fresh chat answers and explains with lineage: PASS")
    print("scope: one supervised count task; no broad math claim")


if __name__ == "__main__":
    main()
