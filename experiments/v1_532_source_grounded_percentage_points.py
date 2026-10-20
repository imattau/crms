"""Extract, calculate, and cite a numeric comparison from source text.

The main case uses a local CC BY PMC article and asks for the comparison
without supplying either value. A scratch conflicting corpus is a negative
control for source disagreement. This is one explicitly framed percentage-
point task, not general scientific number extraction.
"""

from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crms_chat import (
    _format_exact_decimal,
    _natural_percentage_point_evidence,
    _natural_percentage_point_question,
)
from crms_research import CRMSSQLiteResearchIndex


PROJECT = Path(__file__).resolve().parents[1]
SOURCE_DB = (PROJECT / "data" /
             "crms_project_model_academic_expanded_pmc.sqlite.memories" /
             "research.sqlite")
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_532_source_grounded_percentage_points.json"
SOURCE_DOCUMENT = "pmc:PMC13675955.v1.rb496c301cb6ab27e"
SOURCE_SENTENCE = (
    "In women, the fraction of non-reference chrX genotypes that were "
    "heterozygous was 0.605 on GRCh38 and 0.644 on T2T.")
MEASURE = (
    "the fraction of non-reference chrX genotypes that were "
    "heterozygous in women")
QUESTION = (f"How many percentage points higher was {MEASURE} "
            "on T2T than on GRCh38?")
OPPOSITE_DIRECTION = (f"How many percentage points lower was {MEASURE} "
                      "on T2T than on GRCh38?")
UNSUPPORTED = ("How many percentage points higher was the fraction of "
               "non-reference chrX genotypes that were unicorns in women "
               "on T2T than on GRCh38?")


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


def run_chat(root: Path, command: list[str], questions: tuple[str, ...]) -> list[str]:
    result = subprocess.run(
        command, input="\n".join((*questions, "/quit", "")),
        text=True, capture_output=True, cwd=root, timeout=90,
        env=os.environ.copy(), check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"fresh chat failed: {output[-3000:]}")
    replies = [line.split("CRMS>", 1)[1].strip()
               for line in result.stdout.splitlines() if "CRMS>" in line]
    require(len(replies) == len(questions),
            f"expected {len(questions)} replies, got {len(replies)}:\n{output}")
    return replies


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing local PMC index: {SOURCE_DB}")
    source = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)
    document = source.document(SOURCE_DOCUMENT)
    require(SOURCE_SENTENCE in document.text,
            "the pinned PMC article no longer contains the target sentence")
    require("Redistribution license: CC BY" in document.text[:1000],
            "the PMC record no longer exposes the expected license metadata")
    require(_natural_percentage_point_question(QUESTION) is not None,
            "the ordinary percentage-point question was not parsed")
    evidence = _natural_percentage_point_evidence(source, QUESTION)
    require(evidence is not None and "conflicts" not in evidence,
            f"source-linked values were not found: {evidence!r}")
    require(evidence["text"] == SOURCE_SENTENCE,
            f"the selected evidence was not the exact source sentence: {evidence!r}")
    operands = evidence["operands"]
    require([(row["label"], row["value"]) for row in operands]
            == [("T2T", "0.644"), ("GRCh38", "0.605")],
            f"operand labels or original decimal strings changed: {operands!r}")
    require(all(row["citation"] == evidence["citation"] for row in operands)
            and source.resolve_citation(operands[0]["citation"]) == SOURCE_SENTENCE
            and source.resolve_citation(operands[1]["citation"]) == SOURCE_SENTENCE,
            "both operand citations must resolve to the exact supporting sentence")
    independent_delta = (Decimal(operands[0]["value"])
                         - Decimal(operands[1]["value"])) * Decimal(100)
    require(independent_delta == Decimal("3.9")
            and evidence["difference"] == independent_delta
            and evidence["observed_direction"] == "higher",
            f"independent percentage-point calculation disagreed: {evidence!r}")
    require(_natural_percentage_point_evidence(source, UNSUPPORTED) is None,
            "a source without the requested measure produced numeric evidence")

    scratch = Path(tempfile.mkdtemp(prefix="crms-v1-532-", dir="/tmp"))
    try:
        replies = run_chat(
            scratch, command_for(scratch, SOURCE_DB, read_only=True),
            (QUESTION, OPPOSITE_DIRECTION, UNSUPPORTED))
        require("3.9 percentage points higher" in replies[0]
                and "(0.644 − 0.605) × 100 = 3.9" in replies[0]
                and document.title in replies[0]
                and "quoted evidence" in replies[0],
                f"fresh chat did not calculate and cite the source values: {replies[0]!r}")
        require("percentage points higher on T2T than on GRCh38" in replies[1]
                and "lower on T2T" not in replies[1],
                f"the answer repeated the requested direction instead of the data: {replies[1]!r}")
        require("can't calculate" in replies[2].casefold()
                and "3.9" not in replies[2],
                f"missing numeric evidence did not abstain: {replies[2]!r}")

        conflict_root = scratch / "conflict"
        conflict_root.mkdir()
        conflict_index_path = conflict_root / "research.sqlite"
        conflict_index = CRMSSQLiteResearchIndex(conflict_index_path)
        conflict_index.add_document(
            "study-a", "Study A", SOURCE_SENTENCE, "study-a.txt")
        conflict_index.add_document(
            "study-b", "Study B",
            SOURCE_SENTENCE.replace("0.644 on T2T", "0.650 on T2T"),
            "study-b.txt")
        conflict = _natural_percentage_point_evidence(
            conflict_index, QUESTION)
        require(conflict is not None and len(conflict.get("conflicts", [])) == 2,
                f"contradictory sources were not surfaced as conflicts: {conflict!r}")
        unscaled_question = (
            "How many percentage points higher was the score on CohortB "
            "than on CohortA?")
        conflict_index.add_document(
            "unscaled-score", "Unscaled score",
            "The score was 0.2 on CohortA and 0.3 on CohortB.",
            "score.txt")
        require(_natural_percentage_point_evidence(
                    conflict_index, unscaled_question) is None,
                "unit fractions without fraction/proportion semantics were scaled")
        unscaled_score_question = (
            "How many percentage points higher was the score on GroupB "
            "than on GroupA?")
        conflict_index.add_document(
            "unscaled-score-points", "Unscaled score points",
            "The score was 4.2 on GroupA and 5.1 on GroupB.",
            "score-points.txt")
        require(_natural_percentage_point_evidence(
                    conflict_index, unscaled_score_question) is None,
                "unitless score values were treated as percentages")
        conflict_replies = run_chat(
            conflict_root, command_for(conflict_root, conflict_index_path,
                                       read_only=False), (QUESTION,))
        require("disagree on the numeric comparison" in conflict_replies[0]
                and "can't choose one without review" in conflict_replies[0]
                and "percentage points higher" not in conflict_replies[0],
                f"chat selected one of conflicting numeric sources: {conflict_replies[0]!r}")
        conflict_index.close()

        report = {
            "experiment": "v1_532_source_grounded_percentage_points",
            "date": "2026-10-20",
            "method": (
                "A fixed natural-language percentage-point frame locates one "
                "assertion sentence containing the complete measure and both "
                "condition labels, extracts exact decimal strings, verifies "
                "the citation, and calculates with rational arithmetic."),
            "source": {
                "index": "data/crms_project_model_academic_expanded_pmc.sqlite.memories/research.sqlite",
                "document_id": SOURCE_DOCUMENT,
                "title": document.title,
                "license": "CC BY, recorded in the local PMC document metadata",
                "sentence": SOURCE_SENTENCE,
                "citation": evidence["citation"],
            },
            "calculation": {
                "operands": operands,
                "formula": "(0.644 - 0.605) * 100",
                "exact_percentage_point_difference": _format_exact_decimal(
                    evidence["difference"]),
                "formatted_result": "3.9 percentage points higher",
                "both_operand_citations_resolve_to_the_same_exact_sentence": True,
            },
            "chat": {
                "source_backed_query": replies[0],
                "query_direction_contradicted_by_source": replies[1],
                "unsupported_measure_abstention": replies[2],
                "conflicting_source_abstention": conflict_replies[0],
            },
            "controls": {
                "independent_decimal_oracle": "0.644 - 0.605 = 0.039; * 100 = 3.9",
                "unsupported_measure": "abstained",
            "unscaled_unitless_fraction": "abstained",
            "unscaled_unitless_score": "abstained",
                "opposite_requested_direction": "reported observed direction (higher)",
                "two_source_conflict": "abstained pending review",
            },
            "limitations": [
                "One explicitly framed percentage-point question and one CC BY article were evaluated.",
                "The measure and both labels must occur in one assertion sentence; table extraction and multi-sentence linkage are not covered.",
                "This does not establish general numeric extraction, scientific reasoning, or transfer across publishers.",
                "The domain route uses a bounded source pattern and is not an induced general-purpose math language model.",
            ],
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    source.close()
    print("source-grounded numeric operands and exact citations: PASS")
    print("fresh chat computes 3.9 percentage points from the article: PASS")
    print("opposite-direction and unsupported-measure controls: PASS")
    print("unitless fractional values do not silently become percentage points: PASS")
    print("conflicting source values abstain instead of selecting one: PASS")
    print("report:", REPORT)


if __name__ == "__main__":
    main()
