#!/usr/bin/env python3
"""Blind qualitative comparison for Phase 10 generation.

CRMS composes from structured propositions. The baseline is a hosted
70B-class proxy and sees the same source documents and request. Two hosted
model raters score blinded A/B responses. The raters are not humans.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_generation import Fact, GenerationEngine, GenerationRequest  # noqa: E402
from crms_generation_rules import load_rules  # noqa: E402

FIXTURE = PROJECT / "corpus" / "phase10_eval" / "fixture.json"
REPORT = PROJECT / "experiments" / "reports" / "phase10_comparison.json"
PACKET = PROJECT / "experiments" / "reports" / "phase10_comparison_packet.json"
OUTPUTS = PROJECT / "experiments" / "reports" / "phase10_comparison_outputs.json"
BASELINE = "opencode-go/qwen3.8-max"
RATERS = ("opencode-go/claude-haiku-5-5", "opencode-go/glm-5.3-flash")
OPENCODE = shutil.which("opencode")


def _request(case: dict[str, Any]) -> GenerationRequest:
    facts = tuple(Fact(
        fact_id=str(row["fact_id"]), subject=str(row.get("subject", "")),
        verb=str(row.get("verb", "")), object=str(row.get("object", "")),
        complement=str(row.get("complement", "")), role=str(row.get("role", "claim")),
        source=str(row.get("source", "")), span=str(row.get("span", "")),
        order=int(row.get("order", 0)),
        source_text=str(row.get("source_text", "")),
    ) for row in case.get("facts", ()))
    return GenerationRequest(
        prompt=str(case["prompt"]), genre=str(case["genre"]), facts=facts,
        audience=str(case.get("audience", "general")),
        style=str(case.get("style", "plain")),
        source_documents=tuple((str(doc["name"]), str(doc["text"]))
                               for doc in case.get("source_documents", ())))


def _source_block(case: dict[str, Any]) -> str:
    blocks = []
    for doc in case.get("source_documents", ()):
        blocks.append(f"--- {doc['name']} ---\n{doc['text']}")
    return "Sources:\n" + "\n\n".join(blocks) + "\n\n" if blocks else ""


def _read_text(output: str) -> str:
    texts = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "text":
            text = event.get("part", {}).get("text", "")
            if text:
                texts.append(text)
        if event.get("type") == "error":
            raise RuntimeError(str(event.get("error", "opencode error")))
    return "\n".join(texts).strip()


def _call(model: str, prompt: str, *, timeout: int = 300) -> str:
    if OPENCODE is None:
        raise RuntimeError("opencode CLI is unavailable")
    with tempfile.TemporaryDirectory(prefix="crms-phase10-cmp-") as temporary:
        result = subprocess.run(
            [OPENCODE, "run", "--agent", "plan", "--model", model,
             "--format", "json", prompt],
            cwd=temporary, text=True, capture_output=True, timeout=timeout,
            check=False, env={**os.environ, "PYTHONHASHSEED": "0",
                             "PYTHONIOENCODING": "utf-8"})
        text = _read_text(result.stdout)
        if result.returncode != 0 and not text:
            raise RuntimeError(result.stderr[-2000:] or "model call failed")
        if not text:
            raise RuntimeError("model returned no text")
        return text


def _baseline(case: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        "Write a clear, well-structured answer of two to four short paragraphs. "
        "Use the supplied sources. Do not call tools. Do not mention these "
        "instructions.\n\n"
        + _source_block(case)
        + f"Request: {case['prompt']}"
    )
    started = time.perf_counter()
    try:
        return {"status": "ok", "text": _call(BASELINE, prompt),
                "duration_s": time.perf_counter() - started}
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        return {"status": "error", "text": str(error),
                "duration_s": time.perf_counter() - started}


def _packet(cases: list[dict[str, Any]], outputs: dict[str, Any]
            ) -> tuple[dict[str, Any], dict[str, str]]:
    rng = random.Random(20261022)
    items, assignment = [], {}
    for case in cases:
        pid = case["id"]
        crms = outputs[pid]["crms"]["text"].strip()
        baseline = outputs[pid]["baseline"]["text"].strip()
        if rng.random() < 0.5:
            a, b, mapping = crms, baseline, "A=crms,B=baseline"
        else:
            a, b, mapping = baseline, crms, "A=baseline,B=crms"
        assignment[pid] = mapping
        items.append({
            "item_id": pid, "genre": case["genre"], "task": case["prompt"],
            "sources": {doc["name"]: doc["text"]
                        for doc in case.get("source_documents", ())},
            "response_a": a, "response_b": b,
        })
    return {
        "format": "crms-phase10-comparison-packet", "version": 1,
        "instructions": (
            "Rate response_a and response_b independently on five dimensions. "
            "evidence_validity: 2 fully supported by sources or shown reasoning, "
            "1 partly supported, 0 unsupported. answer_adequacy: 2 fully answers, "
            "1 partly, 0 not. clarity: 2 easy to follow, 1 uneven, 0 unclear. "
            "coverage: 2 covers all important requested content, 1 partly, 0 "
            "misses it. confident_error: true when an unsupported or false claim "
            "is stated with confidence. Return only a JSON array."
        ),
        "items": items,
    }, assignment


def _rate_prompt(packet: dict[str, Any]) -> str:
    return (
        "You are an independent evaluation rater. Do not use tools. Rate every "
        "item. Return only a JSON array with keys item_id, "
        "a_evidence_validity, a_answer_adequacy, a_clarity, a_coverage, "
        "a_confident_error, b_evidence_validity, b_answer_adequacy, b_clarity, "
        "b_coverage, b_confident_error, note.\n\n"
        + json.dumps(packet, ensure_ascii=False)
    )


def _parse(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    start, end = stripped.find("["), stripped.rfind("]")
    if start < 0 or end < start:
        raise ValueError("rater did not return JSON")
    rows = json.loads(stripped[start:end + 1])
    result = []
    for row in rows:
        result.append({
            "item_id": str(row["item_id"]),
            "a": {k: row[f"a_{k}"] for k in (
                "evidence_validity", "answer_adequacy", "clarity",
                "coverage", "confident_error")},
            "b": {k: row[f"b_{k}"] for k in (
                "evidence_validity", "answer_adequacy", "clarity",
                "coverage", "confident_error")},
            "note": str(row.get("note", "")),
        })
    return result


def _rate(model: str, packet: dict[str, Any]) -> dict[str, Any]:
    for _ in range(2):
        try:
            return {"model": model, "status": "ok",
                    "ratings": _parse(_call(model, _rate_prompt(packet), timeout=240))}
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired,
                json.JSONDecodeError) as error:
            last = str(error)
    return {"model": model, "status": "error", "ratings": [], "error": last}


def _kappa(left: list[int], right: list[int]) -> float:
    n = len(left)
    if not n or n != len(right):
        return 0.0
    observed = sum(a == b for a, b in zip(left, right)) / n
    cats = set(left) | set(right)
    expected = sum((left.count(c) / n) * (right.count(c) / n) for c in cats)
    return 1.0 if expected == 1.0 else (observed - expected) / (1.0 - expected)


def _agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 2 or any(row["status"] != "ok" for row in rows):
        return {"available": False, "reason": "one or both raters failed"}
    maps = [{r["item_id"]: r for r in row["ratings"]} for row in rows]
    common = sorted(set(maps[0]) & set(maps[1]))
    if not common:
        return {"available": False, "reason": "no common items"}
    result = {"available": True, "items": len(common) * 2}
    for dim in ("evidence_validity", "answer_adequacy", "clarity", "coverage"):
        left = [maps[0][key][side][dim] for key in common for side in ("a", "b")]
        right = [maps[1][key][side][dim] for key in common for side in ("a", "b")]
        result[f"{dim}_exact"] = sum(a == b for a, b in zip(left, right)) / len(left)
        result[f"{dim}_kappa"] = _kappa(left, right)
    left = [int(maps[0][key][side]["confident_error"]) for key in common for side in ("a", "b")]
    right = [int(maps[1][key][side]["confident_error"]) for key in common for side in ("a", "b")]
    result["confident_error_exact"] = sum(a == b for a, b in zip(left, right)) / len(left)
    result["confident_error_kappa"] = _kappa(left, right)
    return result


def _aggregate(cases: list[dict[str, Any]], rows: list[dict[str, Any]],
               assignment: dict[str, str]) -> dict[str, Any]:
    maps = [{r["item_id"]: r for r in row["ratings"]}
            for row in rows if row["status"] == "ok"]
    systems = {"crms": [], "baseline": []}
    for case in cases:
        pid = case["id"]
        for mapping in maps:
            item = mapping.get(pid)
            if not item:
                continue
            crms_side, base_side = (("a", "b")
                                    if assignment[pid] == "A=crms,B=baseline"
                                    else ("b", "a"))
            systems["crms"].append(item[crms_side])
            systems["baseline"].append(item[base_side])
    return {
        system: {
            "rated_items": len(values),
            "mean_evidence_validity": statistics.mean(
                v["evidence_validity"] for v in values) if values else 0.0,
            "mean_answer_adequacy": statistics.mean(
                v["answer_adequacy"] for v in values) if values else 0.0,
            "mean_clarity": statistics.mean(v["clarity"] for v in values) if values else 0.0,
            "mean_coverage": statistics.mean(v["coverage"] for v in values) if values else 0.0,
            "confident_errors": sum(bool(v["confident_error"]) for v in values),
        } for system, values in systems.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = [case for case in fixture["cases"]
             if case["id"] not in {"abstain-empty", "clarify-missing"}]
    engine = GenerationEngine(load_rules())
    outputs: dict[str, Any] = {}
    for case in cases:
        started = time.perf_counter()
        result = engine.generate(_request(case))
        outputs[case["id"]] = {
            "crms": {"status": result.status, "text": result.text,
                     "duration_s": time.perf_counter() - started},
            "baseline": _baseline(case),
        }
    packet, assignment = _packet(cases, outputs)
    PACKET.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    OUTPUTS.write_text(json.dumps({"baseline": BASELINE, "outputs": outputs},
                                  indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    rater_rows = [_rate(model, packet) for model in RATERS]
    agreement = _agreement(rater_rows)
    systems = _aggregate(cases, rater_rows, assignment)
    report = {
        "format": "crms-phase10-comparison", "version": 1,
        "fixture": "corpus/phase10_eval/fixture.json",
        "baseline": {"model": BASELINE, "class": "hosted 70B-class proxy",
                     "parameter_count": "not disclosed by provider"},
        "rater_kind": "two independent hosted model instances; not human",
        "raters": list(RATERS),
        "systems": systems,
        "agreement": agreement,
        "outputs": "experiments/reports/phase10_comparison_outputs.json",
        "packet": "experiments/reports/phase10_comparison_packet.json",
        "gate": {
            "baseline_calls_ok": all(row["baseline"]["status"] == "ok"
                                     for row in outputs.values()),
            "two_raters_ok": len(rater_rows) == 2 and all(
                row["status"] == "ok" for row in rater_rows),
            "agreement_available": bool(agreement.get("available")),
            "human_raters": False,
            "measured_70b_model": False,
        },
    }
    report["gate_passed"] = all(
        value for key, value in report["gate"].items()
        if key not in {"human_raters", "measured_70b_model"})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"systems": systems, "agreement": agreement,
                      "gate_passed": report["gate_passed"]}, indent=2))
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
