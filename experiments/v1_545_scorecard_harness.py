"""Check that the scorecard harness detects passes, failures, and unsafe answers.

Run with: python3 experiments/v1_545_scorecard_harness.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_eval.report import write_report  # noqa: E402
from crms_eval.runner import run_suite  # noqa: E402
from crms_eval.schema import load_suite  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def task(task_id: str, *, contains: str | None = None, outcome: str = "answer",
         known_failure: bool = False) -> dict:
    raw = {
        "id": task_id,
        "category": "harness",
        "provenance": "authored",
        "documents": [{
            "path": "fixture.txt",
            "text": "Zeta was created by Ada.\n",
        }],
        "turns": ["Who created Zeta?"],
        "known_failure": known_failure,
        "expect": {"outcome": outcome},
    }
    if contains is not None:
        raw["expect"]["contains"] = [contains]
    return raw


def main() -> None:
    from crms_eval.schema import Task

    tasks = [
        Task.from_dict(task("harness-pass", contains="Ada created Zeta.")),
        Task.from_dict(task("harness-fail", contains="Nobody created Zeta.")),
        Task.from_dict(task("harness-unsafe", outcome="abstain")),
    ]
    outcome = run_suite(tasks, suite_name="harness")
    by_id = {row.id: row for row in outcome["results"]}

    require(by_id["harness-pass"].status == "pass",
            f"passing task was not detected: {by_id['harness-pass']}")
    require(by_id["harness-fail"].status == "fail"
            and any("missing required text" in item
                    for item in by_id["harness-fail"].failures),
            f"missing expected text was not a failure: {by_id['harness-fail']}")
    require(by_id["harness-unsafe"].status == "fail"
            and by_id["harness-unsafe"].unsafe,
            f"confident answer to an abstention expectation was not unsafe: "
            f"{by_id['harness-unsafe']}")
    summary = outcome["summary"]
    require(summary["passed"] == 1 and summary["failed"] == 2
            and summary["unsafe_answers"] == 1,
            f"summary counted outcomes incorrectly: {summary}")

    with tempfile.TemporaryDirectory(prefix="crms-scorecard-harness-") as folder:
        report_dir = Path(folder) / "report"
        json_path, markdown_path = write_report(
            report_dir, suite="harness", results=outcome["results"],
            summary=summary, metadata=outcome["metadata"])
        require(json_path.is_file() and markdown_path.is_file(),
                "report files were not written")
        markdown = markdown_path.read_text(encoding="utf-8")
        require("Gated failures" in markdown
                and "harness-fail" in markdown
                and "harness-unsafe" in markdown,
                "report did not list the gated failures")
        require('"unsafe_answers": 1' in json_path.read_text(encoding="utf-8"),
                "JSON report did not record the unsafe answer")

        duplicate = Path(folder) / "duplicate.jsonl"
        duplicate.write_text(
            '{"id":"same","category":"x","turns":["hi"]}\n'
            '{"id":"same","category":"x","turns":["hi"]}\n',
            encoding="utf-8")
        try:
            load_suite(duplicate)
        except ValueError as error:
            require("duplicate task id" in str(error),
                    f"duplicate id failed with the wrong error: {error}")
        else:
            raise SystemExit("duplicate task ids were accepted")

    print("scorecard harness detects pass, failure, and unsafe answer: PASS")
    print("scorecard report files and duplicate-id validation: PASS")


if __name__ == "__main__":
    main()
