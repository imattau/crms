"""Phase 10 first-slice contract: rule-only multi-genre composition.

Checks the visible rule file, all frozen generation cases, determinism,
evidence attachment, causal fusion, procedural ordering, and abstention /
clarification behavior. No LLM or network is used.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generation import (  # noqa: E402
    Fact, GenerationEngine, GenerationRequest, copy_ratio,
)
from crms_generation_rules import load_rules  # noqa: E402
from run_phase10_eval import FIXTURE, evaluate_fixture  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def request_for(case_id: str) -> GenerationRequest:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(case for case in fixture["cases"] if case["id"] == case_id)
    facts = tuple(Fact(
        fact_id=str(row["fact_id"]),
        subject=str(row.get("subject", "")),
        verb=str(row.get("verb", "")),
        object=str(row.get("object", "")),
        complement=str(row.get("complement", "")),
        role=str(row.get("role", "claim")),
        source=str(row.get("source", "")),
        span=str(row.get("span", "")),
        order=int(row.get("order", 0)),
        source_text=str(row.get("source_text", "")),
    ) for row in case["facts"])
    return GenerationRequest(
        prompt=str(case["prompt"]), genre=str(case["genre"]), facts=facts,
        audience=str(case.get("audience", "general")),
        style=str(case.get("style", "plain")),
        source_documents=tuple(
            (str(doc["name"]), str(doc["text"]))
            for doc in case.get("source_documents", ())),
    )


def main() -> None:
    rules = load_rules()
    require(len(rules.genres) >= 10, "Phase 10 rule file lost genre coverage")
    require("cause" in rules.constructions, "missing cause construction")
    require("contrast" in rules.constructions, "missing contrast construction")
    require(len(rules.digest) == 64, "rule digest is not sha256")

    report = evaluate_fixture(FIXTURE)
    require(report["gate_passed"], "Phase 10 generation gate failed")
    require(report["summary"]["passed"] == report["summary"]["cases"],
            "not all Phase 10 cases passed")
    require(report["summary"]["mean_copy_ratio"] <= 0.5,
            "mean copy ratio exceeds first-slice target")
    require(report["gate"]["abstention_and_clarification_present"],
            "abstention/clarification controls missing")

    engine = GenerationEngine(rules)
    first = engine.generate(request_for("explain-sky"))
    second = engine.generate(request_for("explain-sky"))
    require(first.status == "ok", "explanation did not generate")
    require(first.text == second.text, "generation is not deterministic")
    require("Because" in first.text, "causal fusion construction missing")
    require("Rayleigh scattering" in first.text, "definition move missing")
    require(all(plan.fact_ids for plan in first.sentence_plans),
            "a sentence plan has no evidence id")
    require(len(first.evidence) >= 6, "evidence ledger is incomplete")
    require(first.critique is not None and first.critique.passed,
            "explanation critic failed")
    require(first.critique.copy_ratio <= 0.75,
            "explanation copy ratio exceeds first-slice limit")

    procedure = engine.generate(request_for("procedure-tea"))
    require(procedure.status == "ok", "procedure did not generate")
    require("First" in procedure.text and "Finally" in procedure.text,
            "procedure ordering transitions missing")
    require("Taste the tea" in procedure.text,
            "imperative realization lost capitalization")

    comparison = engine.generate(request_for("compare-energy"))
    require(comparison.status == "ok", "comparison did not generate")
    require("whereas" in comparison.text, "contrast construction missing")

    analysis = engine.generate(request_for("analysis-remote"))
    require(analysis.status == "ok", "analysis did not generate")
    require("However" in analysis.text, "counterpoint transition missing")

    abstain = engine.generate(request_for("abstain-empty"))
    require(abstain.status == "abstain", "empty evidence did not abstain")
    clarify = engine.generate(request_for("clarify-missing"))
    require(clarify.status == "clarify", "missing required move did not clarify")

    source_text = request_for("explain-sky").source_text()
    ratio = copy_ratio(first.text, [source_text])
    require(ratio <= 0.75, f"copy ratio too high: {ratio:.3f}")

    print("Phase 10 rule file: 10 genres, visible constructions: PASS")
    print("Frozen cases 7/7, mean copy <= 0.5, evidence attached: PASS")
    print("Deterministic explanation, causal fusion, definition: PASS")
    print("Procedure ordering, contrast, counterpoint: PASS")
    print("Abstention and clarification controls: PASS")
    print("Phase 10 first-slice contract: PASS")


if __name__ == "__main__":
    main()
