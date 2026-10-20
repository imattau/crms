"""Induce an ``and`` sequence rule and use it in proof-backed chat.

CRMS is shown two different procedure pairs with their ordered outputs. The
target pair (stable deduplication followed by reversal) is not taught as a
compound. The learner must infer the shared connective, preserve order on an
interleaved-duplicate input, and use the composed operation only after the
knowledge engine proves each finite-list membership claim.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from v1_492_reasoned_filter_language_coverage import build_case
from v1_497_composition_derived_practice import run_chat, require
from crms_math import CRMSMath
from crms_model import CRMSModel
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


BASE_INPUTS = (
    [3, 1, 2], [5, -1, 4], [4, 1, 4, -2],
)
COMPOSITION_INPUT = [12, 4, 12, 9]
REQUEST = (
    "From values 4, 12, 4, 9, and 7, keep only the values Nia reaches, then "
    "remove duplicate values and reverse the list."
)
UNKNOWN_REQUEST = (
    "From values 4, 12, 8, keep only the values Nia reaches, then "
    "remove duplicate values and reverse the list."
)
UNLICENSED_CONNECTIVE = (
    "From values 4, 12, 4, 9, and 7, keep only the values Nia reaches, "
    "then remove duplicate values but reverse the list."
)


def apply(values: list[int], operation: str) -> list[int]:
    if operation == "reverse":
        return list(reversed(values))
    if operation == "add_one":
        return [value + 1 for value in values]
    if operation == "sort":
        return sorted(values)
    if operation == "unique":
        return list(dict.fromkeys(values))
    raise ValueError(operation)


def teach(model: CRMSModel, phrase: str, operation: str,
          inputs: tuple[list[int], ...], source_prefix: str,
          labeler: str, instruction_source: str):
    result = model.teach(
        phrase,
        [(list(values), apply(list(values), operation)) for values in inputs],
        source_ids=[f"{source_prefix}:{index}" for index in range(len(inputs))],
        labeler_ids=[labeler] * len(inputs),
        instruction_source_ids=[instruction_source] * len(inputs))
    if result.status == "need_more_examples":
        contrast = list(result.contrastive_input or ())
        require(bool(contrast) and contrast not in inputs,
                f"{phrase}: missing or repeated contrastive input: {result}")
        result = model.teach(
            phrase, [(contrast, apply(contrast, operation))],
            source_ids=[f"{source_prefix}:contrast"],
            labeler_ids=[labeler],
            instruction_source_ids=[instruction_source])
    require(result.status == "learned",
            f"procedure did not learn uniquely: {phrase}: {result}")
    return result


def teach_compound(model: CRMSModel, phrase: str, first: str, second: str,
                   labeler: str) -> None:
    examples = [
        (list(values), apply(apply(list(values), first), second))
        for values in BASE_INPUTS
    ]
    result = model.teach(
        phrase, examples,
        source_ids=[f"teacher:compound:{phrase}:{index}"
                    for index in range(len(examples))],
        labeler_ids=[labeler] * len(examples),
        instruction_source_ids=["teacher:sequence:and"] * len(examples))
    require(result.status == "learned",
            f"compound demonstration was not learned: {phrase}: {result}")


def learn_components(*, include_second_compound: bool = True) -> CRMSModel:
    model = CRMSModel(max_composition_depth=2, max_workers=1)
    labeler = "codex:procedure-teacher"
    for phrase, operation in (
            ("reverse the list", "reverse"),
            ("add one to values", "add_one"),
            ("sort the list", "sort"),
            ("flip the values", "reverse"),
            ("remove duplicate values", "unique")):
        teach(model, phrase, operation, BASE_INPUTS,
              f"teacher:component:{phrase}", labeler,
              f"teacher:operation:{operation}")

    teach_compound(model, "reverse the list and add one to values",
                   "reverse", "add_one", "codex:sequence-teacher")
    # Rebuild the single-context view before adding the second demonstration;
    # the second distinct component pairing must be what licenses `and`.
    require(not model._grounded_composition_connectives(),
            "one compound alone licensed a sequence connective")
    if include_second_compound:
        teach_compound(model, "sort the list and flip the values",
                       "sort", "reverse", "codex:sequence-teacher")
    return model


def main() -> None:
    one_pair = learn_components(include_second_compound=False)
    unlicensed = one_pair.predict(
        "remove duplicate values and reverse the list", COMPOSITION_INPUT)
    require(unlicensed.status != "ok" and unlicensed.output is None,
            f"one sequence example licensed a new component pair: {unlicensed}")

    procedures = learn_components()
    connectives = procedures._grounded_composition_connectives()
    require(("and",) in connectives
            and len(connectives[("and",)][0]) >= 2,
            f"distinct examples did not license the sequence connective: {connectives}")

    dedupe_then_reverse = procedures.predict(
        "remove duplicate values and reverse the list", COMPOSITION_INPUT)
    reverse_then_dedupe = procedures.predict(
        "reverse the list and remove duplicate values", COMPOSITION_INPUT)
    require(dedupe_then_reverse.status == "ok"
            and dedupe_then_reverse.output == [9, 4, 12]
            and reverse_then_dedupe.status == "ok"
            and reverse_then_dedupe.output == [9, 12, 4]
            and dedupe_then_reverse.output != reverse_then_dedupe.output
            and dedupe_then_reverse.matched_templates == ["learned_sequence:and"],
            "learned connective failed the order-sensitive unseen composition: "
            f"{dedupe_then_reverse}; {reverse_then_dedupe}")

    knowledge, _ = build_case()
    result = compose_verified_filter(REQUEST, knowledge, procedures)
    require(result is not None and result.status == "answered"
            and result.included_values == (4, 12, 4, 9)
            and result.excluded_negative == (7,)
            and result.output_values == (9, 12, 4)
            and any(record.get("labeler_id") == "codex:sequence-teacher"
                    for record in result.procedure_records),
            f"proof-backed composition did not use the learned connective: {result}")

    unknown = compose_verified_filter(UNKNOWN_REQUEST, knowledge, procedures)
    require(unknown is not None and unknown.status == "unknown"
            and unknown.unresolved_values == (8,)
            and not unknown.output_values,
            f"unknown membership passed through to the learned procedure: {unknown}")
    unsupported = compose_verified_filter(
        UNLICENSED_CONNECTIVE, knowledge, procedures)
    require(unsupported is not None
            and unsupported.status == "unsupported_procedure"
            and not unsupported.output_values,
            f"an unlicensed connective was accepted: {unsupported}")

    index = CRMSResearchIndex()
    with tempfile.TemporaryDirectory(prefix="crms-learned-and-compose-") as d:
        root = Path(d)
        knowledge_path = root / "model.sqlite3"
        procedure_path = root / "procedures.json"
        index_path = root / "sources.json"
        knowledge.save(knowledge_path)
        procedures.save(procedure_path)
        index.save(index_path)
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

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
                and "codex:sequence-teacher" in output
                and "Because Nia" in output
                and "Traceback" not in output,
                f"fresh chat failed to explain the learned sequence composition:\n"
                f"{output}")

    print("one sequence demonstration does not license a new component pair: PASS")
    print("two distinct demonstrations license `and` as a learned sequence rule: PASS")
    print("order-sensitive unseen operation pair composes correctly: PASS")
    print("proof-backed chat applies sequence and preserves explicit negative: PASS")
    print("unknown premise and unlicensed connective abstain: PASS")
    print("fresh-process reload and `why?` preserve rule/proof provenance: PASS")
    print("scope: controlled, teacher-labeled connective induction; no broad language claim")


if __name__ == "__main__":
    main()
