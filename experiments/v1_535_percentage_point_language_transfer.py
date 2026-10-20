"""Evaluate additional natural-language frames for cited point changes.

This uses held-out question wording against an existing CC BY PMC sentence.
The questions and expected calculations are frozen here before assessing the
runtime route. It measures one bounded source-grounded math task family.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _natural_percentage_point_evidence,
    _natural_percentage_point_question,
)
from crms_research import CRMSSQLiteResearchIndex
from v1_532_source_grounded_percentage_points import command_for, run_chat


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = (PROJECT / "data" /
             "crms_project_model_academic_expanded_pmc.sqlite.memories" /
             "research.sqlite")
SOURCE_DOCUMENT = "pmc:PMC13675955.v1.rb496c301cb6ab27e"
SOURCE_SENTENCE = (
    "In women, the fraction of non-reference chrX genotypes that were "
    "heterozygous was 0.605 on GRCh38 and 0.644 on T2T.")
MEASURE = (
    "the fraction of non-reference chrX genotypes that were "
    "heterozygous in women")
CANONICAL = (
    f"How many percentage points higher was {MEASURE} "
    "on T2T than on GRCh38?")
INCREASE_FROM_TO = (
    f"By how many percentage points did {MEASURE} increase "
    "from GRCh38 to T2T?")
GROW_BETWEEN = (
    f"How many percentage points did {MEASURE} grow "
    "between GRCh38 and T2T?")
CHANGE_FROM_TO = (
    f"What was the percentage-point change in {MEASURE} "
    "from GRCh38 to T2T?")
CONTRADICTORY_DIRECTION = (
    f"How many percentage points did {MEASURE} decrease "
    "from GRCh38 to T2T?")
UNSUPPORTED_MEASURE = (
    "By how many percentage points did the fraction of unicorn genotypes "
    "increase from GRCh38 to T2T?")
UNSUPPORTED_LABEL = (
    f"How many percentage points did {MEASURE} increase "
    "from GRCh3 to T2T?")
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_535_percentage_point_language_transfer.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing local PMC index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    document = source.document(SOURCE_DOCUMENT)
    require(SOURCE_SENTENCE in document.text,
            "pinned source no longer contains the numeric assertion")
    require("Redistribution license: CC BY" in document.text[:1000],
            "source record no longer exposes its CC BY license")

    supported = (CANONICAL, INCREASE_FROM_TO, GROW_BETWEEN, CHANGE_FROM_TO)
    evidence_rows = []
    for question in supported:
        parsed = _natural_percentage_point_question(question)
        require(parsed is not None,
                f"supported natural-language frame did not parse: {question}")
        evidence = _natural_percentage_point_evidence(source, question)
        require(evidence is not None and "conflicts" not in evidence,
                f"frame did not retrieve its source evidence: {question}: {evidence}")
        require(evidence["text"] == SOURCE_SENTENCE,
                f"wrong sentence selected for {question}: {evidence}")
        operands = evidence["operands"]
        require([(row["label"], row["value"]) for row in operands]
                == [("T2T", "0.644"), ("GRCh38", "0.605")],
                f"wrong labelled values for {question}: {operands}")
        require(all(source.resolve_citation(row["citation"]) == SOURCE_SENTENCE
                    for row in operands),
                f"operand citation failed for {question}")
        oracle = ((Decimal("0.644") - Decimal("0.605")) * Decimal(100))
        require(evidence["difference"] == oracle == Decimal("3.9"),
                f"independent percentage-point check failed: {evidence}")
        evidence_rows.append({
            "question": question,
            "parsed": list(parsed),
            "difference_percentage_points": str(evidence["difference"]),
            "citation_resolves_to_exact_sentence": True,
        })

    for question in (UNSUPPORTED_MEASURE, UNSUPPORTED_LABEL):
        parsed = _natural_percentage_point_question(question)
        require(parsed is not None,
                f"negative should reach the point-comparison route: {question}")
        require(_natural_percentage_point_evidence(source, question) is None,
                f"unsupported measure/label found numeric values: {question}")

    scratch = Path(tempfile.mkdtemp(prefix="crms-v1-535-", dir="/tmp"))
    try:
        questions = (*supported, CONTRADICTORY_DIRECTION,
                     UNSUPPORTED_MEASURE, UNSUPPORTED_LABEL)
        replies = run_chat(
            scratch, command_for(scratch, SOURCE_DB, read_only=True), questions)
        require(all("3.9 percentage points" in reply for reply in replies[:4]),
                f"one supported chat frame failed to calculate: {replies[:4]}")
        require("3.9 percentage points higher" in replies[1]
                and "3.9 percentage points higher" in replies[2]
                and "3.9 percentage points higher" in replies[3]
                and "The comparison is" in replies[4]
                and "3.9 percentage points higher" in replies[4]
                and "decrease" not in replies[4].casefold(),
                f"source direction did not override request wording: {replies[1:5]}")
        for reply in replies[5:]:
            require("can't calculate the percentage-point difference" in reply
                    and "grounded count" not in reply.casefold()
                    and "3.9 percentage points" not in reply,
                    f"negative did not get a specific abstention: {reply}")
        require(all(document.title in reply for reply in replies[:5]),
                "source-backed result omitted the cited article title")
        chat_rows = list(replies)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        source.close()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({
        "experiment": "v1_535_percentage_point_language_transfer",
        "date": "2026-10-20",
        "status": "pass",
        "source": {
            "document_id": SOURCE_DOCUMENT,
            "title": document.title,
            "license": "CC BY, as recorded in the local PMC snapshot",
            "sentence": SOURCE_SENTENCE,
        },
        "held_out_question_frames": evidence_rows,
        "controls": {
            "contradictory_direction": CONTRADICTORY_DIRECTION,
            "unsupported_measure": UNSUPPORTED_MEASURE,
            "unsupported_label": UNSUPPORTED_LABEL,
            "fresh_chat_replies": chat_rows,
        },
        "limitations": [
            "One source sentence and one measure/condition pair were used.",
            "The new wording varies syntax but not the domain or underlying evidence.",
            "The questions were authored during development, not by independent participants.",
            "This does not establish broad scientific number understanding or publisher transfer.",
        ],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("four natural comparison frames parse and select the exact same cited sentence: PASS")
    print("fresh chat calculates 3.9 pp, follows source direction, and cites the paper: PASS")
    print("unicorn measure, unsupported label, and contradictory direction controls: PASS")
    print("scope: one source-grounded percentage-point task family")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
