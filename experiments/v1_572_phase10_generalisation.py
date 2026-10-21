"""Phase 10 generalisation contract: classes, back-off, analogies, curve."""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_generalisation import (  # noqa: E402
    ClassHierarchy, LexicalClass, analogical_candidates, evidence_weight,
    fact_coverage_curve,
)
from crms_generation import Fact, GenerationEngine, GenerationRequest  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402
from run_phase10_eval import FIXTURE  # noqa: E402

REPORT = PROJECT / "experiments" / "reports" / "phase10_generalisation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _request(case: dict) -> GenerationRequest:
    facts = tuple(Fact(
        fact_id=str(row["fact_id"]), subject=str(row.get("subject", "")),
        verb=str(row.get("verb", "")), object=str(row.get("object", "")),
        complement=str(row.get("complement", "")), role=str(row.get("role", "claim")),
        source=str(row.get("source", "")), span=str(row.get("span", "")),
        order=int(row.get("order", 0)), source_text=str(row.get("source_text", "")),
    ) for row in case["facts"])
    return GenerationRequest(
        prompt=str(case["prompt"]), genre=str(case["genre"]), facts=facts,
        audience=str(case.get("audience", "general")),
        style=str(case.get("style", "plain")),
        source_documents=tuple((str(doc["name"]), str(doc["text"]))
                               for doc in case.get("source_documents", ())))


def main() -> None:
    hierarchy = ClassHierarchy([
        LexicalClass("energy_source", ("energy source",)),
        LexicalClass("renewable_source", ("renewable source",), "energy_source"),
        LexicalClass("solar_power", ("solar power", "photovoltaic"), "renewable_source"),
        LexicalClass("wind_power", ("wind power",), "renewable_source"),
        LexicalClass("hydro_power", ("hydro power",), "renewable_source"),
        LexicalClass("fossil_power", ("coal power",), "energy_source"),
        LexicalClass("nuclear_power", ("nuclear power",)),
    ])
    require(hierarchy.generalise("photovoltaic") == "solar_power",
            "specific class did not resolve")
    require("energy_source" in hierarchy.ancestors("photovoltaic"),
            "parent class chain missing")
    require(hierarchy.related("solar power", "wind power"),
            "sibling classes did not relate")
    require(not hierarchy.related("solar power", "nuclear power"),
            "unrelated classes related")

    facts = (
        Fact("hydro", "Hydro power", "produces", object="electricity", role="criterion_a", source="hydro.txt", source_text="Hydro power produces electricity."),
        Fact("solar", "Solar power", "produces", object="electricity", role="criterion_a", source="solar.txt", source_text="Solar power produces electricity."),
        Fact("wind", "Wind power", "produces", object="electricity", role="criterion_b", source="wind.txt", source_text="Wind power produces electricity."),
        Fact("coal", "Coal power", "produces", object="electricity", role="criterion_b", source="coal.txt", source_text="Coal power produces electricity."),
    )
    require(evidence_weight(facts[1], {"solar.txt": 3}) >
            evidence_weight(facts[1], {"solar.txt": 1}),
            "evidence-count weight did not increase")
    candidates = analogical_candidates(facts[0], facts, hierarchy)
    require(candidates and all(not row["accepted"] for row in candidates),
            "analogical candidates must be report-only")
    require(any(row["fact_id"] == "solar" for row in candidates),
            "solar was not an analogical candidate")

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(row for row in fixture["cases"] if row["id"] == "explain-sky")
    engine = GenerationEngine(load_rules())
    curve = fact_coverage_curve(engine, _request(case), range(1, 7))
    require(any(row["status"] == "clarify" for row in curve),
            "coverage curve lacks a missing-fact point")
    require(any(row["status"] == "ok" for row in curve),
            "coverage curve never reaches a complete answer")
    report = {
        "format": "crms-phase10-generalisation",
        "version": 1,
        "classes": {
            name: {"members": list(item.members), "parent": item.parent}
            for name, item in hierarchy.classes.items()
        },
        "backoff": {
            "photovoltaic": list(hierarchy.ancestors("photovoltaic")),
            "solar_vs_wind": hierarchy.related("solar power", "wind power"),
        },
        "evidence_weights": {
            "one_source": evidence_weight(facts[1], {"solar.txt": 1}),
            "three_sources": evidence_weight(facts[1], {"solar.txt": 3}),
        },
        "analogical_candidates": candidates,
        "coverage_curve": curve,
        "gate": {
            "class_hierarchy": True,
            "backoff": True,
            "report_only_analogies": True,
            "evidence_weights": True,
            "coverage_curve_published": True,
        },
    }
    report["gate_passed"] = all(report["gate"].values())
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    require(report["gate_passed"], "generalisation gate failed")
    print("Lexical class hierarchy and back-off: PASS")
    print("Report-only analogical candidates: PASS")
    print("Evidence-count weights and fact-coverage curve: PASS")
    print(f"Report: {REPORT.relative_to(PROJECT)}")
    print("Phase 10 generalisation contract: PASS")


if __name__ == "__main__":
    main()
