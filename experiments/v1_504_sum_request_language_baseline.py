"""Freeze a small wording-coverage baseline for proof-backed aggregation.

Prompts were authored as a held-out development packet after v1_503. This is
not an independent benchmark: the same developer specifies the target meaning
and evaluates the replies. Every prompt is run in a fresh CLI process.
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

from v1_497_composition_derived_practice import run_chat, require
from v1_500_learned_and_reasoned_composition import learn_components
from v1_502_reasoned_numeric_aggregation import (
    build_knowledge, sum_training_data,
)
from v1_503_sum_first_reasoned_composition import teach_sum_phrase
from crms_math import CRMSMath
from crms_research import CRMSResearchIndex
from crms_task_composition import compose_verified_filter
from crms_translation import CRMSTranslation


VALUES = "23, 5, 23, and 8"
EXPECTED_TOTAL = 51
CASES = (
    ("control_filter_then_sum",
     f"Filter {VALUES} to values Mira reaches, then sum the values."),
    ("control_sum_first",
     f"Sum every value in {VALUES} that Mira reaches."),
    ("operation_synonym",
     f"Add up every value in {VALUES} that Mira reaches."),
    ("wh_total_frame",
     f"What is the total of the values Mira reaches among {VALUES}?"),
    ("list_first_imperative",
     f"From {VALUES}, add together only the numbers Mira reaches."),
    ("two_clause_pronoun",
     f"Mira reaches some of {VALUES}. Add up the ones she reaches."),
    ("wh_filter_and_aggregate",
     f"Which values in {VALUES} does Mira reach, and what do they sum to?"),
    ("possessive_nominalization",
     f"Take the total of all values Mira reaches from {VALUES}."),
)


def main() -> None:
    knowledge = build_knowledge()
    procedures = learn_components()
    sum_training_data(procedures)
    teach_sum_phrase(procedures)
    index = CRMSResearchIndex()

    records = []
    with tempfile.TemporaryDirectory(prefix="crms-sum-language-baseline-") as d:
        root = Path(d)
        sources = {
            "knowledge.sqlite3": root / "source-model.sqlite3",
            "procedures.json": root / "source-procedures.json",
            "sources.json": root / "source-index.json",
        }
        knowledge.save(sources["knowledge.sqlite3"])
        procedures.save(sources["procedures.json"])
        index.save(sources["sources.json"])
        CRMSMath().save(root / "math.json")
        CRMSTranslation().save(root / "translations.json")

        for case_id, request in CASES:
            api_result = compose_verified_filter(request, knowledge, procedures)
            with tempfile.TemporaryDirectory(
                    prefix=f"crms-{case_id}-", dir=root) as session_name:
                session = Path(session_name)
                local_paths = {}
                for name, source in sources.items():
                    local = session / name
                    shutil.copy2(source, local)
                    local_paths[name] = local
                shutil.copy2(root / "math.json", session / "math.json")
                shutil.copy2(root / "translations.json",
                             session / "translations.json")
                output = run_chat(
                    session, local_paths["knowledge.sqlite3"],
                    local_paths["procedures.json"],
                    local_paths["sources.json"], (request,))
            chat_answered = f"Their total is {EXPECTED_TOTAL}." in output
            records.append({
                "case_id": case_id,
                "request": request,
                "expected_total": EXPECTED_TOTAL,
                "composition_status": (api_result.status
                                        if api_result else "no_route"),
                "composition_output": (list(api_result.output_values)
                                       if api_result else []),
                "chat_answered_with_expected_total": chat_answered,
                "chat_output": output.strip(),
            })

    report = {
        "experiment": "v1_504_sum_request_language_baseline",
        "status": "frozen_development_baseline",
        "authorship": "Codex-authored after v1_503; not independent validation",
        "model_state": "proof/rule corpus and learned sum phrases from v1_502/v1_503",
        "cases": records,
        "summary": {
            "count": len(records),
            "composition_answered": sum(
                item["composition_status"] == "answered" for item in records),
            "fresh_chat_answered": sum(
                item["chat_answered_with_expected_total"] for item in records),
            "unanswered_case_ids": [
                item["case_id"] for item in records
                if not item["chat_answered_with_expected_total"]],
        },
        "limitations": [
            "One relation, one small value set, and one aggregate task family.",
            "All requests are authored by the same evaluator and are not an independent benchmark.",
            "This measures language-frame coverage, not mathematical correctness across domains.",
        ],
    }
    report_path = (PROJECT / "experiments" / "reports" /
                   "v1_504_sum_request_language_baseline.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"fresh-process chat answered: {report['summary']['fresh_chat_answered']}/"
          f"{report['summary']['count']}")
    print("unanswered: " + ", ".join(report["summary"]["unanswered_case_ids"]))
    print(f"report: {report_path.relative_to(PROJECT)}")
    require(report["summary"]["fresh_chat_answered"] >= 2
            and report["summary"]["fresh_chat_answered"] < len(records),
            "baseline no longer shows both positive controls and wording gaps")


if __name__ == "__main__":
    main()
