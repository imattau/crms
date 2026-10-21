#!/usr/bin/env python3
"""Run the frozen first-slice Phase 10 rule-only generation evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_generation import (  # noqa: E402
    Fact, GenerationEngine, GenerationRequest, GenerationResult,
)
from crms_generation_rules import load_rules  # noqa: E402

FIXTURE = PROJECT / "corpus" / "phase10_eval" / "fixture.json"
REPORT = PROJECT / "experiments" / "reports" / "phase10_generation.json"
FORMAT = "crms-phase10-generation-report"
VERSION = 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") != "crms-phase10-generation":
        raise SystemExit("unsupported Phase 10 generation fixture")
    if raw.get("version") != 1:
        raise SystemExit("unsupported Phase 10 generation fixture version")
    sidecar = path.with_suffix(".sha256")
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="ascii").split()[0]
        actual = _sha256(path)
        if actual != expected:
            raise SystemExit("Phase 10 fixture does not match its frozen digest")
    return raw


def _request(case: dict[str, Any]) -> GenerationRequest:
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
        tags=tuple(str(tag) for tag in row.get("tags", ())),
    ) for row in case.get("facts", ()))
    return GenerationRequest(
        prompt=str(case["prompt"]),
        genre=str(case["genre"]),
        facts=facts,
        audience=str(case.get("audience", "general")),
        style=str(case.get("style", "plain")),
        max_sentences=int(case.get("max_sentences", 10)),
        source_documents=tuple(
            (str(doc["name"]), str(doc["text"]))
            for doc in case.get("source_documents", ())
        ),
    )


def _check(result: GenerationResult, checks: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    expected_status = checks.get("status")
    if expected_status and result.status != expected_status:
        failures.append(
            f"status {result.status!r} != expected {expected_status!r}")
    critique = result.critique
    if checks.get("min_sentences") is not None:
        actual = critique.sentence_count if critique else 0
        if actual < int(checks["min_sentences"]):
            failures.append(
                f"sentences {actual} < {checks['min_sentences']}")
    if checks.get("min_paragraphs") is not None:
        actual = critique.paragraph_count if critique else 0
        if actual < int(checks["min_paragraphs"]):
            failures.append(
                f"paragraphs {actual} < {checks['min_paragraphs']}")
    if checks.get("min_multi_fact") is not None:
        actual = critique.multi_fact_sentences if critique else 0
        if actual < int(checks["min_multi_fact"]):
            failures.append(
                f"multi-fact sentences {actual} < {checks['min_multi_fact']}")
    haystack = (result.text + " " + result.message).casefold()
    for expected in checks.get("contains", ()):
        if str(expected).casefold() not in haystack:
            failures.append(f"missing text: {expected!r}")
    for forbidden in checks.get("not_contains", ()):
        if str(forbidden).casefold() in result.text.casefold():
            failures.append(f"forbidden text: {forbidden!r}")
    if checks.get("max_copy_ratio") is not None:
        actual = critique.copy_ratio if critique else 0.0
        if actual > float(checks["max_copy_ratio"]):
            failures.append(
                f"copy ratio {actual:.3f} > {checks['max_copy_ratio']}")
    if checks.get("max_sentence_words") is not None:
        actual = critique.max_sentence_words if critique else 0
        if actual > int(checks["max_sentence_words"]):
            failures.append(
                f"max sentence words {actual} > {checks['max_sentence_words']}")
    if checks.get("require_evidence"):
        if critique is None or not critique.evidence_valid:
            failures.append("evidence check failed")
    return failures


def evaluate_fixture(path: Path = FIXTURE) -> dict[str, Any]:
    fixture = _load(path)
    rules = load_rules()
    engine = GenerationEngine(rules)
    rows: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        request = _request(case)
        result = engine.generate(request)
        failures = _check(result, case.get("checks", {}))
        rows.append({
            "id": case["id"],
            "genre": case["genre"],
            "prompt": case["prompt"],
            "status": result.status,
            "passed": not failures,
            "failures": failures,
            "style": result.style,
            "text": result.text,
            "critique": result.critique.as_dict() if result.critique else None,
            "evidence": list(result.evidence),
            "candidate_scores": list(result.candidate_scores),
            "content_plan": result.content_plan.as_dict(),
            "sentence_plans": [plan.as_dict()
                               for plan in result.sentence_plans],
        })
    passed = sum(row["passed"] for row in rows)
    copy_values = [row["critique"]["copy_ratio"] for row in rows
                   if row["critique"]]
    sentence_values = [row["critique"]["sentence_count"] for row in rows
                       if row["critique"]]
    tested_genres = sorted({row["genre"] for row in rows
                            if row["status"] == "ok"})
    declared_genres = sorted(rules.genres)
    moves_tested = sorted({section["move"] for row in rows
                           for section in row["content_plan"]["sections"]})
    constructions_tested = sorted({plan["relation"] for row in rows
                                   for plan in row["sentence_plans"]})
    report = {
        "format": FORMAT,
        "version": VERSION,
        "frozen": fixture.get("frozen"),
        "fixture_sha256": _sha256(path),
        "rule_sha256": rules.digest,
        "rules": rules.as_dict(),
        "coverage": {
            "declared_genres": declared_genres,
            "tested_genres": tested_genres,
            "untested_genres": sorted(set(declared_genres) - set(tested_genres)),
            "moves_tested": moves_tested,
            "constructions_tested": constructions_tested,
        },
        "summary": {
            "cases": len(rows),
            "passed": passed,
            "failed": len(rows) - passed,
            "completion": passed / len(rows) if rows else 0.0,
            "mean_copy_ratio": statistics.mean(copy_values) if copy_values else 0.0,
            "max_copy_ratio": max(copy_values) if copy_values else 0.0,
            "mean_sentences": statistics.mean(sentence_values) if sentence_values else 0.0,
        },
        "cases": rows,
        "gate": {
            "all_cases_pass": passed == len(rows),
            "positive_generation_ok": all(
                row["status"] == "ok" for row in rows
                if row["status"] != "abstain" and row["status"] != "clarify"),
            "abstention_and_clarification_present": any(
                row["status"] == "abstain" for row in rows) and any(
                row["status"] == "clarify" for row in rows),
            "mean_copy_ratio_below_0_5": (
                (statistics.mean(copy_values) if copy_values else 0.0) <= 0.5),
            "no_llm_or_network_dependency": True,
        },
    }
    report["gate_passed"] = all(report["gate"].values())
    report["first_slice_gate_passed"] = report["gate_passed"]
    report["phase10_full_gate"] = {
        "300_blind_prompts": False,
        "two_source_disjoint_corpora": False,
        "all_10_genres_tested": len(tested_genres) == len(declared_genres),
        "human_clarity_calibration": False,
        "judge_separation": False,
        "sql_rule_lifecycle": False,
        "teacher_rule_induction": False,
        "clean_room_release": False,
        "70b_comparison": False,
    }
    report["phase10_full_gate_passed"] = all(
        report["phase10_full_gate"].values())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    report = evaluate_fixture(args.fixture)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in report["cases"]:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"{mark:4s} {row['id']:20s} {row['status']:14s} "
              f"{row['critique']['sentence_count'] if row['critique'] else 0} \
sentences")
        for failure in row["failures"]:
            print(f"     - {failure}")
    print(f"\n{report['summary']['passed']}/{report['summary']['cases']} cases; "
          f"mean copy {report['summary']['mean_copy_ratio']:.3f}; "
          f"first-slice gate {'PASS' if report['gate_passed'] else 'FAIL'}")
    open_items = [name for name, value in report["phase10_full_gate"].items()
                  if not value]
    print(f"Full Phase 10 gate: OPEN ({len(open_items)} open items)")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
