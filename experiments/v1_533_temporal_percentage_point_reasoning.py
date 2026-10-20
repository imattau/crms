"""Transfer numeric-source reasoning to a dated proportion and new question frame.

The source uses explicit percentages, yearly labels, and parenthesized counts.
This is a document-disjoint PMC example, not publisher-independent transfer.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import _natural_percentage_point_evidence
from crms_research import CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = (PROJECT / "data" /
             "crms_project_model_academic_expanded_pmc.sqlite.memories" /
             "research.sqlite")
SOURCE_DOCUMENT = "pmc:PMC13675696.v1.r2afb793f4ee80c68"
SOURCE_SENTENCE = (
    "The proportion of XDR isolates increased from 1.7% (1/58) in 2018 to "
    "22.0% (24/109) in 2023 (p < 0.001), based on isolates with phenotypic "
    "data available for all four antimicrobials.")
QUESTION = (
    "How many percentage points did the proportion of XDR isolates increase "
    "from 2018 to 2023?")
ALTERNATE_QUESTION = (
    "How many percentage points did the proportion of XDR isolates rise "
    "between 2018 and 2023?")
CONTRADICTORY_QUESTION = (
    "How many percentage points did the proportion of XDR isolates decrease "
    "from 2018 to 2023?")
UNSUPPORTED_QUESTION = (
    "How many percentage points did the proportion of unicorn isolates "
    "increase from 2018 to 2023?")
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_533_temporal_percentage_point_reasoning.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def command_for(root: Path, index_path: Path, *, read_only: bool) -> list[str]:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--index", str(index_path),
        "--dialogue-state", str(root / "dialogue.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
    ]
    if read_only:
        command.append("--index-read-only")
    return command


def run_chat(root: Path, index_path: Path, questions: tuple[str, ...], *,
             read_only: bool) -> list[str]:
    result = subprocess.run(
        command_for(root, index_path, read_only=read_only),
        input="\n".join((*questions, "/quit", "")),
        text=True, capture_output=True, cwd=root, timeout=90,
        env=os.environ.copy(), check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"fresh chat failed: {output[-2500:]}")
    replies = [chunk.split("\nyou> ", 1)[0].strip()
               for chunk in result.stdout.split("you> CRMS> ")[1:]]
    require(len(replies) == len(questions),
            f"expected {len(questions)} replies, got {len(replies)}:\n{output}")
    return replies


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing local PMC index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    document = source.document(SOURCE_DOCUMENT)
    require(SOURCE_SENTENCE in document.text,
            "the pinned source record no longer contains the tested sentence")
    require("Redistribution license: CC BY" in document.text[:1000],
            "the source record no longer exposes the expected license metadata")
    result = _natural_percentage_point_evidence(source, QUESTION)
    require(result is not None and "conflicts" not in result
            and result["text"] == SOURCE_SENTENCE,
            f"dated numeric pair was not extracted from its exact sentence: {result!r}")
    require(result["input_unit"] == "percent" and result["scale"] == 1
            and result["observed_direction"] == "higher",
            f"explicit percent units or temporal direction were mishandled: {result!r}")
    operands = result["operands"]
    require([(item["label"], item["value"]) for item in operands]
            == [("2023", "22.0"), ("2018", "1.7")],
            f"wrong temporal operands: {operands!r}")
    require(all(source.resolve_citation(item["citation"]) == SOURCE_SENTENCE
                for item in operands),
            "each operand citation must resolve to the exact source sentence")
    oracle = Decimal(operands[0]["value"]) - Decimal(operands[1]["value"])
    require(oracle == Decimal("20.3") and result["difference"] == oracle,
            f"independent percentage-point oracle disagreed: {result!r}")
    require(_natural_percentage_point_evidence(
                source, UNSUPPORTED_QUESTION) is None,
            "unsupported measure found a numeric pair")

    scratch = Path(tempfile.mkdtemp(prefix="crms-v1-533-", dir="/tmp"))
    try:
        replies = run_chat(
            scratch, SOURCE_DB,
            (QUESTION, "why?", ALTERNATE_QUESTION,
             CONTRADICTORY_QUESTION, UNSUPPORTED_QUESTION),
            read_only=True)
        require("20.3 percentage points higher in 2023 than in 2018" in replies[0]
                and "(22.0% − 1.7%) = 20.3" in replies[0]
                and document.title in replies[0],
                f"fresh chat omitted the dated calculation or source: {replies[0]!r}")
        require(SOURCE_SENTENCE in replies[1]
                and result["citation"] in replies[1]
                and "not been accepted as a fact" in replies[1],
                f"why? did not explain the exact cited premise: {replies[1]!r}")
        require("20.3 percentage points higher in 2023 than in 2018" in replies[2]
                and "(22.0% − 1.7%) = 20.3" in replies[2],
                f"alternate question frame failed: {replies[2]!r}")
        require("20.3 percentage points higher in 2023 than in 2018" in replies[3]
                and "decrease" not in replies[3].casefold(),
                f"a false requested direction overrode the source: {replies[3]!r}")
        require("can't calculate" in replies[4].casefold()
                and "20.3" not in replies[4],
                f"unsupported metric did not abstain: {replies[4]!r}")

        conflict_root = scratch / "conflict"
        conflict_root.mkdir()
        conflict_index_path = conflict_root / "research.sqlite"
        conflict_index = CRMSSQLiteResearchIndex(conflict_index_path)
        conflict_index.add_document(
            "study-a", "Study A", SOURCE_SENTENCE, "study-a.txt")
        conflict_index.add_document(
            "study-b", "Study B",
            SOURCE_SENTENCE.replace("1.7% (1/58)", "2.1% (2/95)"),
            "study-b.txt")
        conflict = _natural_percentage_point_evidence(
            conflict_index, QUESTION)
        require(conflict is not None and len(conflict.get("conflicts", [])) == 2,
                f"different dated values were not flagged: {conflict!r}")
        conflict_reply = run_chat(
            conflict_root, conflict_index_path, (QUESTION,), read_only=False)[0]
        require("disagree on the numeric comparison" in conflict_reply
                and "can't choose one without review" in conflict_reply
                and "20.3 percentage points" not in conflict_reply,
                f"chat selected one of two conflicting sources: {conflict_reply!r}")
        conflict_index.close()

        report = {
            "experiment": "v1_533_temporal_percentage_point_reasoning",
            "date": "2026-10-20",
            "source": {
                "document_id": SOURCE_DOCUMENT,
                "title": document.title,
                "license": "CC BY, recorded in the local PMC document metadata",
                "sentence": SOURCE_SENTENCE,
                "citation": result["citation"],
            },
            "calculation": {
                "operands": operands,
                "formula": "22.0% - 1.7%",
                "difference_percentage_points": str(oracle),
                "both_operand_citations_resolve_to_the_exact_sentence": True,
            },
            "questions": {
                "from_to": QUESTION,
                "between_rise": ALTERNATE_QUESTION,
                "contradictory_direction": CONTRADICTORY_QUESTION,
                "unsupported_measure": UNSUPPORTED_QUESTION,
            },
            "chat": {
                "answer": replies[0],
                "why_answer": replies[1],
                "alternate_question_frame": replies[2],
                "wrong_direction_control": replies[3],
                "unsupported_measure_control": replies[4],
                "conflicting_source_control": conflict_reply,
            },
            "limitations": [
                "This is one dated comparison from a second source document in the same PMC collection.",
                "It tests the from-year-to-year language frame, explicit percentages, and inline parenthetical counts.",
                "It does not establish publisher-independent transfer, table extraction, or general scientific reasoning.",
                "The article restricts the denominator to isolates with phenotype data available for all four antimicrobials; the extracted sentence is cited verbatim.",
            ],
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
        source.close()

    print("different-document dated proportion and explicit-percent extraction: PASS")
    print("fresh chat computes 20.3 percentage points and explains the exact citation: PASS")
    print("wrong-direction, unsupported-measure, and source-conflict controls: PASS")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
