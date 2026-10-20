"""Compose separately taught operation wording through ordinary chat.

The operation phrases and sequence connectives are explicitly supervised.
The evaluation holds out their combination, order, input values, and request
instances. This is a controlled recombination transfer check, not an
independent natural-language benchmark.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_451_reasoned_procedure_composition import add_chain
from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import (
    BASE_INPUTS, apply, learn_components, teach_compound,
)
from v1_502_reasoned_numeric_aggregation import build_knowledge
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


FIRST = (
    "Take values 23, 5, 23, and 8; among those Mira reaches, then "
    "keep unique entries and flip their order."
)
REVERSED_ORDER = (
    "Take values 23, 5, 23, and 8; among those Mira reaches, then "
    "flip their order then keep unique entries."
)
UNKNOWN = (
    "Take values 23, 5, 11, and 8; among those Mira reaches, then "
    "keep unique entries and flip their order."
)
UNLICENSED_CONNECTIVE = (
    "Take values 23, 5, 23, and 8; among those Mira reaches, then "
    "keep unique entries but flip their order."
)
UNLICENSED_OPERATION = (
    "Take values 23, 5, 23, and 8; among those Mira reaches, then "
    "keep unique entries and cube the values."
)
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_534_taught_operation_phrase_recombination.json"


def teach_operation_phrase(model, phrase: str, operation: str) -> None:
    def execute(values: list[int]) -> list[int]:
        if operation == "unique":
            return list(dict.fromkeys(values))
        if operation == "reverse":
            return list(reversed(values))
        raise ValueError(operation)

    examples = [
        ([3, 1, 3, 2], execute([3, 1, 3, 2])),
        ([5, 2, 5, 4], execute([5, 2, 5, 4])),
        ([8, 6, 8, 7], execute([8, 6, 8, 7])),
        ([1, 1, 2], execute([1, 1, 2])),
    ]
    result = model.teach(
        phrase, examples,
        source_ids=[f"teacher:operation-phrase:{phrase}:{i}"
                    for i in range(len(examples))],
        labeler_ids=["teacher:operation-phrase"] * len(examples),
        instruction_source_ids=["teacher:operation-phrase"] * len(examples))
    seen = [list(values) for values, _output in examples]
    contrast = 0
    while result.status == "need_more_examples" and contrast < 12:
        values = list(result.contrastive_input or ())
        require(bool(values) and values not in seen,
                f"{phrase}: missing/repeated contrast: {result}")
        seen.append(values)
        contrast += 1
        result = model.teach(
            phrase, [(values, execute(values))],
            source_ids=[f"teacher:operation-phrase:{phrase}:contrast:{contrast}"],
            labeler_ids=["teacher:operation-phrase"],
            instruction_source_ids=["teacher:operation-phrase"])
    require(result.status == "learned" and result.procedure is not None,
            f"{phrase}: no unique operation learned: {result}")


def main() -> None:
    knowledge = build_knowledge()
    add_chain(knowledge, "Mira", "Nell", "Quartz", "23",
              "mira:record-23", conclusion="none")
    add_chain(knowledge, "Mira", "Omar", "Ridge", "5",
              "mira:record-5", conclusion="none")
    knowledge.add_negative_fact(
        "Mira", "reaches", "8", "mira:record-8-negative")

    procedures = learn_components()
    before_teaching = compose_verified_filter(FIRST, knowledge, procedures)
    require(before_teaching is None
            or (before_teaching.status != "answered"
                and not before_teaching.output_values),
            f"new operation wording did not abstain before teaching: {before_teaching}")
    teach_operation_phrase(procedures, "keep unique entries", "unique")
    teach_operation_phrase(procedures, "flip their order", "reverse")

    # Two distinct demonstrations license this sequence connective. The
    # evaluation phrases below are not shown as compound examples.
    teach_compound(
        procedures, "reverse the list then add one to values",
        "reverse", "add_one", "codex:sequence-then-teacher")
    teach_compound(
        procedures, "sort the list then flip the values",
        "sort", "reverse", "codex:sequence-then-teacher")

    cases = (
        (FIRST, (5, 23), "codex:sequence-teacher"),
        (REVERSED_ORDER, (23, 5), "codex:sequence-then-teacher"),
    )
    case_results = []
    for request, expected, connective_labeler in cases:
        result = compose_verified_filter(request, knowledge, procedures)
        oracle_input = [23, 5, 23]
        # Independent Python implementation checks both operation orders.
        if request == FIRST:
            oracle = list(reversed(list(dict.fromkeys(oracle_input))))
        else:
            oracle = list(dict.fromkeys(reversed(oracle_input)))
        require(result is not None and result.status == "answered"
                and result.included_values == (23, 5, 23)
                and result.excluded_negative == (8,)
                and result.output_values == expected == tuple(oracle)
                and "mira:record-23" in result.evidence_sources
                and "mira:record-5" in result.evidence_sources
                and "mira:record-8-negative" in result.evidence_sources
                and any(row.get("labeler_id") == "teacher:operation-phrase"
                        for row in result.procedure_records)
                and any(row.get("labeler_id") == connective_labeler
                        for row in result.procedure_records),
                f"held-out request/order failed: {request!r}: {result}")
        case_results.append({
            "request": request,
            "expected": list(expected),
            "actual": list(result.output_values),
            "proof_sources": ["mira:record-23", "mira:record-5"],
            "negative_source": "mira:record-8-negative",
            "procedure_lineage": [
                row.get("source_id") for row in result.procedure_records],
            "sequence_labeler": connective_labeler,
        })

    unknown = compose_verified_filter(UNKNOWN, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (11,)
            and not unknown.output_values,
            f"unknown membership entered a composed output: {unknown}")
    for request in (UNLICENSED_CONNECTIVE, UNLICENSED_OPERATION):
        unsupported = compose_verified_filter(request, knowledge, procedures)
        require(unsupported is not None
                and unsupported.status == "unsupported_procedure"
                and not unsupported.output_values,
                f"unlicensed operation/connective was accepted: {unsupported}")

    with tempfile.TemporaryDirectory(prefix="crms-v1-534-") as folder:
        root = Path(folder)
        knowledge_path = root / "model.sqlite3"
        procedures_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedures_path)
        CRMSResearchIndex().save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")
        session = root / "copied-model"
        session.mkdir()
        for source in (knowledge_path, procedures_path, index_path,
                       root / "math.json", root / "translations.json"):
            shutil.copy2(source, session / source.name)
        chat_output = run_chat(
            session, session / knowledge_path.name,
            session / procedures_path.name, session / index_path.name,
            (FIRST, "why?", REVERSED_ORDER, UNKNOWN, UNLICENSED_CONNECTIVE))
        require("[5, 23]" in chat_output and "[23, 5]" in chat_output
                and "Because Mira" in chat_output
                and "mira:record-23" in chat_output
                and "mira:record-8-negative" in chat_output
                and "teacher:operation-phrase" in chat_output
                and "can't determine whether 11" in chat_output
                and "no taught phrase evidence" in chat_output.casefold()
                and "Traceback" not in chat_output,
                f"copied-model chat lost transfer, lineage, or abstention:\n{chat_output}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "experiment": "v1_534_taught_operation_phrase_recombination",
        "date": "2026-10-20",
        "status": "pass",
        "training": {
            "operation_phrases": ["keep unique entries", "flip their order"],
            "operation_labeler": "teacher:operation-phrase",
            "sequence_connectives": ["and", "then"],
            "connective_labels": ["codex:sequence-teacher",
                                  "codex:sequence-then-teacher"],
            "held_out_components": [
                "operation combinations", "operation order", "request instances",
                "entity values"
            ],
        },
        "cases": case_results,
        "controls": {
            "unknown_member": unknown.status,
            "unlicensed_connective": "unsupported_procedure",
            "unlicensed_operation": "unsupported_procedure",
            "before_phrase_teaching": (
                "abstained" if before_teaching is None
                or before_teaching.status != "answered" else "answered"),
            "copied_model_fresh_chat_and_why": True,
        },
        "independent_oracle": "Python stable de-duplication and list reversal",
        "limitations": [
            "Operation wording and connective were explicitly teacher-labeled.",
            "Request combinations, order, and values were held out from those examples.",
            "The fixtures are controlled; this is not independent natural-language transfer.",
            "The input evidence is a synthetic proof graph, not a representative corpus.",
        ],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("separately taught operation phrases combine through learned 'and' and 'then': PASS")
    print("held-out order reversal changes the result and matches independent Python oracle: PASS")
    print("positive, explicit-negative, operation-teacher, and connective provenance retained: PASS")
    print("unknown member, unlicensed connector, and unlicensed operation abstain: PASS")
    print("copied SQLite model answers in fresh chat and explains the proof: PASS")
    print("scope: controlled operation-phrase recombination; not independent language transfer")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
