"""Compare settlement fields from two exact-title, cited SimpleWiki pages."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_chat import (
    _answer_settlement_area_comparison,
    _answer_settlement_population_comparison,
    _natural_measure_comparison_request,
)
from crms_research import CRMSSQLiteResearchIndex

SOURCE_DB = PROJECT / "data" / "crms_simplewiki_research.sqlite"
REPORT = PROJECT / "experiments" / "reports" / \
    "v1_538_source_backed_settlement_comparison.json"
AREA_CONVERSION = Decimal("2.589988110336")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def run_cli(root: Path, questions: tuple[str, ...]) -> str:
    command = [
        sys.executable, str(PROJECT / "crms_chat.py"),
        "--index", str(SOURCE_DB), "--index-read-only",
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidates.json"),
    ]
    result = subprocess.run(
        command, input="\n".join((*questions, "/quit", "")),
        text=True, capture_output=True, cwd=root, timeout=90, check=False)
    output = result.stdout + result.stderr
    require(result.returncode == 0 and "Traceback" not in output,
            f"fresh CLI failed:\n{output[-2500:]}")
    return output


def main() -> None:
    require(SOURCE_DB.is_file(), f"missing source index: {SOURCE_DB}")
    index = CRMSSQLiteResearchIndex(SOURCE_DB, read_only=True)

    area_request = _answer_settlement_area_comparison(index, "Paris", "Rome")
    require(area_request is not None
            and "105.4 km²" in area_request
            and "496.3 sq mi" in area_request
            and "about 1285.4 km²" in area_request
            and "Rome's listed settlement area is larger" in area_request
            and "Prix de Rome" not in area_request,
            f"area fields were not compared without lexical decoys: {area_request}")
    area_citations = re.findall(
        r"wiki:simplewiki:\d+#sha256=[0-9a-f]+&chars=\d+:\d+",
        area_request)
    require(len(area_citations) == 2
            and [index.resolve_citation(citation) for citation in area_citations]
            == ["area_total_km2 = 105.4", "area_total_sq_mi = 496.3"],
            f"area citations do not resolve to exact fields: {area_citations}")
    expected_area = (Decimal("496.3") * AREA_CONVERSION).quantize(
        Decimal("0.1"))
    require(expected_area == Decimal("1285.4"),
            f"independent area conversion differs: {expected_area}")
    london_tokyo_area = _answer_settlement_area_comparison(
        index, "London", "Tokyo")
    require(london_tokyo_area is not None
            and "1572 km²" in london_tokyo_area
            and "2194.07 km²" in london_tokyo_area
            and "Tokyo's listed settlement area is larger" in london_tokyo_area,
            f"area comparison did not transfer to new exact-title pages: {london_tokyo_area}")

    parsed = _natural_measure_comparison_request(
        "Compare the population of Paris and Rome.")
    require(parsed == ("population", "Paris", "Rome"),
            f"population comparison wording was misparsed: {parsed}")
    population_request = _answer_settlement_population_comparison(
        index, "Paris", "Rome")
    require(population_request is not None
            and "2,140,526" in population_request
            and "2,879,728" in population_request
            and "different reference dates" in population_request
            and "larger for Rome" in population_request,
            f"dated population comparison was not qualified: {population_request}")
    population_citations = re.findall(
        r"wiki:simplewiki:\d+#sha256=[0-9a-f]+&chars=\d+:\d+",
        population_request)
    resolved_population_citations = [
        index.resolve_citation(citation) for citation in population_citations]
    require(len(resolved_population_citations) == 5
            and "population_total = 2,140,526"
                in resolved_population_citations
            and "population_blank1 = 2,879,728"
                in resolved_population_citations
            and "population_blank1_title = Comune"
                in resolved_population_citations
            and any("population_as_of = January 1, 2019 (est)" in item
                    for item in resolved_population_citations)
            and any("population_as_of = 30 April 2018" in item
                    for item in resolved_population_citations),
            "population citations do not expose both values and reference dates")
    new_york_los_angeles = _answer_settlement_population_comparison(
        index, "New York City", "Los Angeles")
    require(new_york_los_angeles is not None
            and "metropolitan population" in new_york_los_angeles
            and "20,140,470" in new_york_los_angeles
            and "13,200,998" in new_york_los_angeles
            and "may define metropolitan areas differently"
                in new_york_los_angeles,
            "schema variation did not select shared metro fields conservatively")
    metro_citations = re.findall(
        r"wiki:simplewiki:\d+#sha256=[0-9a-f]+&chars=\d+:\d+",
        new_york_los_angeles)
    resolved_metro_citations = [index.resolve_citation(c) for c in metro_citations]
    require(len(resolved_metro_citations) == 4
            and "population_metro = 20,140,470 (1st)"
                in resolved_metro_citations
            and "population_metro = 13,200,998 (2nd)"
                in resolved_metro_citations,
            "metro comparison citations did not resolve to both exact fields")

    with tempfile.TemporaryDirectory(prefix="crms-v1-538-") as temp:
        root = Path(temp)
        output = run_cli(root, (
            "What is the population of Paris?",
            "Compare Paris and Rome.",
            "why?",
            "Compare the population of Paris and Rome.",
            "Compare the population of New York City and Los Angeles.",
            "Compare the population of Paris and Atlantis.",
        ))
    lines = [line for line in output.splitlines() if "CRMS>" in line]
    require(len(lines) == 6
            and "2,140,526" in lines[0]
            and "Rome's listed settlement area is larger" in lines[1]
            and "105.4 km²" in lines[2] and "496.3 sq mi" in lines[2]
            and "2,140,526" not in lines[2]
            and "different reference dates" in lines[3]
            and "metropolitan population" in lines[4]
            and "may define metropolitan areas differently" in lines[4]
            and "I won't infer a comparison" in lines[5]
            and "Prix de Rome" not in lines[1],
            f"ordinary chat did not preserve comparison boundaries: {lines}")
    require("Traceback" not in output,
            "ordinary chat crashed during a comparison session")

    report = {
        "experiment": "v1_538_source_backed_settlement_comparison",
        "date": "2026-10-20",
        "source": {
            "index": str(SOURCE_DB.relative_to(PROJECT)),
            "collection": "SimpleWiki",
            "use": "read-only exact-title settlement infobox fields",
        },
        "checks": {
            "ordinary_chat_area_comparison": "pass",
            "ordinary_chat_population_comparison": "pass",
            "disjoint_page_pair_field_variants": "pass",
            "metropolitan_scope_and_boundary_caveat": "pass",
            "why_followup_stays_on_latest_comparison": "pass",
            "area_units_independently_normalized_to_km2": "pass",
            "exact_value_and_date_citations": "pass",
            "lexical_decoy_avoided": "pass",
            "unsupported_entity_pair_abstains": "pass",
        },
        "limitations": [
            "This is a narrow exact-title settlement comparison, not a general comparison engine.",
            "Population figures have different reference dates and are reported as supplied, without claiming same-date counts.",
            "The three page pairs are from the same SimpleWiki collection and were selected for schema coverage; they are not a representative or publisher-independent holdout.",
            "Area values are compared only after explicit unit normalization; no other settlement fields are compared.",
            "The task wording and expected interpretation are Codex-authored; the source values and citations are checked against the read-only index.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print("SimpleWiki exact-title area comparison and unit conversion: PASS")
    print("population comparison preserves both cited reference dates: PASS")
    print("lexical decoy excluded; unsupported pair does not guess: PASS")
    print("fresh ordinary CLI with read-only source index: PASS")
    print("report:", REPORT)
    index.close()


if __name__ == "__main__":
    main()
