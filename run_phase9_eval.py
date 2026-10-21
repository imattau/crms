#!/usr/bin/env python3
"""Run the Phase 9 external-validation lane.

Three measurements are kept separate:

1. a gated supported-subset scorecard;
2. independent-model-authored literary breadth probes, published as failures;
3. a blind qualitative comparison against a hosted 70B-class proxy.

The two raters are independent hosted model instances, not humans. The report
labels that boundary explicitly and leaves the human-rater gate open.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
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

from crms_eval.driver import _replies, run_task  # noqa: E402
from crms_eval.oracles import evaluate  # noqa: E402
from crms_eval.schema import Task  # noqa: E402

FIXTURE = PROJECT / "corpus" / "phase9_eval" / "fixture.json"
REPORT = PROJECT / "experiments" / "reports" / "phase9_external.json"
PACKET = PROJECT / "experiments" / "reports" / "phase9_rater_packet.json"
OUTPUTS = PROJECT / "experiments" / "reports" / "phase9_outputs.json"
BASELINE_MODEL = "opencode-go/qwen3.8-max"
RATER_MODELS = ("opencode-go/claude-haiku-5-5", "opencode-go/glm-5.3-flash")
FORMAT = "crms-phase9-external"
VERSION = 1
OPENCODE = shutil.which("opencode")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fixture(path: Path) -> tuple[dict[str, Any], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") != "crms-phase9-eval" or raw.get("version") != VERSION:
        raise SystemExit("unsupported Phase 9 fixture")
    sidecar = path.with_suffix(".sha256")
    digest = _sha256(path)
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="ascii").split()[0]
        if expected != digest:
            raise SystemExit("Phase 9 fixture does not match its frozen digest")
    return raw, digest


def _source_text(source_dir: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8")
            for path in sorted(source_dir.glob("*.txt"))}


def _task(raw: dict[str, Any], sources: dict[str, str]) -> Task:
    item = dict(raw)
    documents = []
    for name in item.get("documents", ()):
        if name not in sources:
            raise ValueError(f"unknown Phase 9 source: {name}")
        documents.append({"path": name, "text": sources[name]})
    item["documents"] = documents
    item.setdefault("provenance", "phase9")
    return Task.from_dict(item)


def _run_split(tasks: list[dict[str, Any]], sources: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for raw in tasks:
        task = _task(raw, sources)
        started = time.perf_counter()
        try:
            output = run_task(task)
            oracle = evaluate(task, output.transcript, output.replies)
            rows.append({
                "id": task.id,
                "category": task.category,
                "provenance": task.provenance,
                "status": "pass" if oracle.passed else "fail",
                "observed": oracle.observed,
                "unsafe": oracle.unsafe,
                "failures": list(oracle.failures),
                "duration_s": output.duration_s,
                "replies": output.replies,
                "transcript": output.transcript,
            })
        except (OSError, ValueError, RuntimeError) as error:
            rows.append({
                "id": task.id, "category": task.category,
                "provenance": task.provenance, "status": "error",
                "observed": "error", "unsafe": False,
                "failures": [str(error)], "duration_s": time.perf_counter() - started,
                "replies": [], "transcript": "",
            })
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(row["status"] == "pass" for row in rows)
    durations = [row["duration_s"] for row in rows]
    return {
        "tasks": len(rows),
        "passed": passed,
        "failed": sum(row["status"] == "fail" for row in rows),
        "errors": sum(row["status"] == "error" for row in rows),
        "completion": passed / len(rows) if rows else 0.0,
        "unsafe_answers": sum(bool(row["unsafe"]) for row in rows),
        "median_s": statistics.median(durations) if durations else 0.0,
        "p95_s": _p95(durations),
    }


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(0.95 * len(ordered)) - 1))]


def _source_block(names: list[str], sources: dict[str, str]) -> str:
    if not names:
        return ""
    blocks = []
    for name in names:
        blocks.append(f"--- {name} ---\n{sources[name]}")
    return "Sources:\n" + "\n\n".join(blocks) + "\n\n"


def _run_crms_probe(probe: dict[str, Any], sources: dict[str, str]) -> dict[str, Any]:
    raw = {
        "id": probe["id"], "category": probe["category"],
        "provenance": "phase9-comparison", "turns": probe["crms_turns"],
        "documents": list(probe.get("sources", ())), "expect": {},
        "rule_depth": int(probe.get("rule_depth", 2)),
    }
    task = _task(raw, sources)
    started = time.perf_counter()
    try:
        output = run_task(task)
        return {
            "system": "crms", "status": "ok",
            "text": "\n".join(output.replies),
            "duration_s": output.duration_s,
        }
    except (OSError, ValueError, RuntimeError) as error:
        return {
            "system": "crms", "status": "error", "text": str(error),
            "duration_s": time.perf_counter() - started,
        }


def _read_opencode_text(output: str) -> str:
    texts: list[str] = []
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
            raise RuntimeError(str(event.get("error", "opencode model error")))
    return "\n".join(texts).strip()


def _call_model(model: str, prompt: str, *, timeout: int = 300) -> str:
    if OPENCODE is None:
        raise RuntimeError("opencode CLI is not available")
    with tempfile.TemporaryDirectory(prefix="crms-phase9-model-") as temporary:
        command = [
            OPENCODE, "run", "--agent", "plan", "--model", model,
            "--format", "json", prompt,
        ]
        result = subprocess.run(
            command, cwd=temporary, text=True, capture_output=True,
            timeout=timeout, check=False,
            env={**os.environ, "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"},
        )
        output = result.stdout + result.stderr
        try:
            text = _read_opencode_text(result.stdout)
        except RuntimeError:
            text = ""
        if result.returncode != 0 and not text:
            raise RuntimeError(
                f"model call failed (exit {result.returncode}): {output[-2000:]}")
        if not text:
            raise RuntimeError(f"model returned no text: {output[-2000:]}")
        return text


def _run_baseline(probe: dict[str, Any], sources: dict[str, str],
                  model: str) -> dict[str, Any]:
    prompt = (
        "Answer the final user request in the prompt. Do not call tools. "
        "Be concise and do not mention this instruction.\n\n"
        + _source_block(list(probe.get("sources", ())), sources)
        + probe["baseline_prompt"]
    )
    started = time.perf_counter()
    try:
        text = _call_model(model, prompt)
        return {"system": "baseline", "status": "ok", "text": text,
                "duration_s": time.perf_counter() - started}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        return {"system": "baseline", "status": "error", "text": str(error),
                "duration_s": time.perf_counter() - started}


def _clean_for_rater(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("Plan plan-"):
            continue
        if line.startswith("CRMS state saved"):
            continue
        if line.startswith("1 source claim available"):
            continue
        if line.startswith("Say ‘yes’") or line.startswith("Say 'yes'"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _build_packet(probes: list[dict[str, Any]], outputs: dict[str, Any],
                  sources: dict[str, str]
                  ) -> tuple[dict[str, Any], dict[str, str]]:
    rng = random.Random(20261021)
    items = []
    assignment: dict[str, str] = {}
    for probe in probes:
        pid = probe["id"]
        crms = _clean_for_rater(outputs[pid]["crms"]["text"])
        baseline = outputs[pid]["baseline"]["text"].strip()
        if rng.random() < 0.5:
            a, b, mapping = crms, baseline, "A=crms,B=baseline"
        else:
            a, b, mapping = baseline, crms, "A=baseline,B=crms"
        assignment[pid] = mapping
        items.append({
            "item_id": pid,
            "category": probe["category"],
            "task": probe["baseline_prompt"],
            "sources": {name: sources[name]
                        for name in probe.get("sources", ())},
            "response_a": a,
            "response_b": b,
        })
    return {
        "format": "crms-phase9-rater-packet", "version": 1,
        "instructions": (
            "Rate response_a and response_b independently. evidence_validity: 2 "
            "when every factual claim is supported by the supplied source or a "
            "shown calculation, 1 when partly supported, 0 when unsupported. "
            "answer_adequacy: 2 when the user's request is fully answered, 1 "
            "when partly answered, 0 when not answered. confident_error: true "
            "when the response asserts an unsupported or false fact with "
            "confidence. Return only a JSON array."
        ),
        "items": items,
    }, assignment


def _rater_prompt(packet: dict[str, Any]) -> str:
    return (
        "You are an independent evaluation rater. Do not use tools. Read the "
        "rubric and rate every item. Return only a JSON array, one object per "
        "item, with keys item_id, a_evidence_validity, a_answer_adequacy, "
        "a_confident_error, b_evidence_validity, b_answer_adequacy, "
        "b_confident_error, note. Do not rate style or length.\n\n"
        + json.dumps(packet, ensure_ascii=False)
    )


def _parse_ratings(text: str) -> list[dict[str, Any]]:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end < start:
        raise ValueError("rater did not return a JSON array")
    data = json.loads(stripped[start:end + 1])
    ratings = []
    for row in data:
        ratings.append({
            "item_id": str(row["item_id"]),
            "a": {
                "evidence_validity": int(row["a_evidence_validity"]),
                "answer_adequacy": int(row["a_answer_adequacy"]),
                "confident_error": bool(row["a_confident_error"]),
            },
            "b": {
                "evidence_validity": int(row["b_evidence_validity"]),
                "answer_adequacy": int(row["b_answer_adequacy"]),
                "confident_error": bool(row["b_confident_error"]),
            },
            "note": str(row.get("note", "")),
        })
    return ratings


def _rate(model: str, packet: dict[str, Any]) -> dict[str, Any]:
    prompt = _rater_prompt(packet)
    last_error = ""
    for attempt in range(2):
        try:
            text = _call_model(model, prompt, timeout=240)
            return {"model": model, "status": "ok", "ratings": _parse_ratings(text)}
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired,
                json.JSONDecodeError) as error:
            last_error = str(error)
    return {"model": model, "status": "error", "ratings": [], "error": last_error}


def _kappa(left: list[int], right: list[int]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    n = len(left)
    observed = sum(a == b for a, b in zip(left, right)) / n
    categories = set(left) | set(right)
    expected = sum((left.count(c) / n) * (right.count(c) / n)
                   for c in categories)
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def _agreement(ratings: list[dict[str, Any]]) -> dict[str, Any]:
    if len(ratings) != 2 or any(row["status"] != "ok" for row in ratings):
        return {"available": False, "reason": "one or both raters failed"}
    by_rater = []
    for row in ratings:
        by_rater.append({item["item_id"]: item for item in row["ratings"]})
    common = sorted(set(by_rater[0]) & set(by_rater[1]))
    if not common:
        return {"available": False, "reason": "no common rated items"}
    adequacy_l = [by_rater[0][key][side]["answer_adequacy"]
                  for key in common for side in ("a", "b")]
    adequacy_r = [by_rater[1][key][side]["answer_adequacy"]
                  for key in common for side in ("a", "b")]
    evidence_l = [by_rater[0][key][side]["evidence_validity"]
                  for key in common for side in ("a", "b")]
    evidence_r = [by_rater[1][key][side]["evidence_validity"]
                  for key in common for side in ("a", "b")]
    error_l = [int(by_rater[0][key][side]["confident_error"])
               for key in common for side in ("a", "b")]
    error_r = [int(by_rater[1][key][side]["confident_error"])
               for key in common for side in ("a", "b")]
    total = len(common) * 2
    return {
        "available": True,
        "items": total,
        "adequacy_exact_agreement": sum(a == b for a, b in zip(adequacy_l, adequacy_r)) / total,
        "adequacy_kappa": _kappa(adequacy_l, adequacy_r),
        "evidence_exact_agreement": sum(a == b for a, b in zip(evidence_l, evidence_r)) / total,
        "evidence_kappa": _kappa(evidence_l, evidence_r),
        "confident_error_exact_agreement": sum(a == b for a, b in zip(error_l, error_r)) / total,
        "confident_error_kappa": _kappa(error_l, error_r),
    }


def _aggregate(probes: list[dict[str, Any]], ratings: list[dict[str, Any]],
               assignment: dict[str, str]) -> dict[str, Any]:
    by_rater = []
    for row in ratings:
        if row["status"] == "ok":
            by_rater.append({item["item_id"]: item for item in row["ratings"]})
    systems: dict[str, list[dict[str, Any]]] = {"crms": [], "baseline": []}
    per_probe = []
    for probe in probes:
        pid = probe["id"]
        values = []
        for mapping in by_rater:
            item = mapping.get(pid)
            if not item:
                continue
            is_crms_a = assignment[pid] == "A=crms,B=baseline"
            crms_side, baseline_side = (("a", "b") if is_crms_a else ("b", "a"))
            for system, side in (("crms", crms_side), ("baseline", baseline_side)):
                values.append({
                    "system": system,
                    "evidence_validity": item[side]["evidence_validity"],
                    "answer_adequacy": item[side]["answer_adequacy"],
                    "confident_error": item[side]["confident_error"],
                })
        for value in values:
            systems[value["system"]].append(value)
        per_probe.append({"id": pid, "category": probe["category"],
                          "ratings": values})
    aggregate = {}
    for system, rows in systems.items():
        aggregate[system] = {
            "rated_items": len(rows),
            "mean_evidence_validity": statistics.mean(
                row["evidence_validity"] for row in rows) if rows else 0.0,
            "mean_answer_adequacy": statistics.mean(
                row["answer_adequacy"] for row in rows) if rows else 0.0,
            "confident_errors": sum(row["confident_error"] for row in rows),
        }
    return {"systems": aggregate, "per_probe": per_probe}


def _failure_taxonomy(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        if row["status"] == "pass":
            continue
        failures = " ".join(row["failures"]).lower()
        if row["unsafe"]:
            counts["confident answer where abstention required"] += 1
        elif "citation" in failures:
            counts["citation or exact-quote mismatch"] += 1
        elif "expected abstention" in failures:
            counts["abstention classification"] += 1
        elif "missing required" in failures or "forbidden" in failures:
            counts["retrieval or grounding omitted required content"] += 1
        elif "error" in row["status"]:
            counts["harness or process error"] += 1
        else:
            counts["other"] += 1
    return dict(sorted(counts.items()))


def _section2_status(supported: dict[str, Any], breadth: dict[str, Any],
                     comparison: dict[str, Any]) -> dict[str, Any]:
    return {
        "met": False,
        "reason": (
            "The bounded Phase 9 lane validates a supported subset and publishes "
            "breadth failures. It does not meet the full section 2 scale targets "
            "(~300 ordinary tasks, 1M-fact/2GB p95, 70B parity) and its raters "
            "are automated model instances, not humans."
        ),
        "missing": [
            "~300 ordinary tasks across 10 categories",
            "human independent raters for evidence validity and answer adequacy",
            "p95 turn <2 s at 1M facts and a 2 GB index",
            "qualitative comparison against a measured 70B parameter model, not a hosted proxy",
            "second-publisher transfer and sustained three-round learning efficacy at section 2 thresholds",
        ],
        "supported_completion": supported["completion"],
        "breadth_completion": breadth["completion"],
        "comparison": comparison.get("systems", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path, default=REPORT)
    parser.add_argument("--baseline-model", default=BASELINE_MODEL)
    parser.add_argument("--skip-baseline", action="store_true")
    parser.add_argument("--skip-raters", action="store_true")
    parser.add_argument("--no-breadth", action="store_true")
    args = parser.parse_args()

    fixture, digest = _load_fixture(args.fixture)
    source_dir = args.fixture.parent / fixture.get("source_dir", "sources")
    sources = _source_text(source_dir)
    started = time.perf_counter()

    supported_rows = _run_split(fixture["supported_tasks"], sources)
    breadth_rows = [] if args.no_breadth else _run_split(fixture["breadth_tasks"], sources)
    supported = _summary(supported_rows)
    breadth = _summary(breadth_rows) if breadth_rows else {
        "tasks": 0, "passed": 0, "failed": 0, "errors": 0,
        "completion": 0.0, "unsafe_answers": 0, "median_s": 0.0, "p95_s": 0.0,
    }

    probes = fixture.get("comparison_probes", [])
    outputs: dict[str, Any] = {}
    if not args.skip_baseline:
        for probe in probes:
            crms = _run_crms_probe(probe, sources)
            baseline = _run_baseline(probe, sources, args.baseline_model)
            outputs[probe["id"]] = {"crms": crms, "baseline": baseline}
    packet, assignment = (_build_packet(probes, outputs, sources)
                          if outputs else ({"items": []}, {}))
    if outputs:
        PACKET.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        OUTPUTS.write_text(json.dumps({
            "format": "crms-phase9-outputs", "version": 1,
            "baseline_model": args.baseline_model,
            "probes": probes, "outputs": outputs,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rater_rows: list[dict[str, Any]] = []
    if packet["items"] and not args.skip_raters:
        for model in RATER_MODELS:
            rater_rows.append(_rate(model, packet))
    agreement = _agreement(rater_rows)
    comparison = _aggregate(probes, rater_rows, assignment) if outputs else {
        "systems": {}, "per_probe": [],
    }
    comparison["baseline"] = {
        "model": args.baseline_model,
        "class": "hosted 70B-class proxy",
        "parameter_count": "not disclosed by provider",
    }
    comparison["rater_kind"] = "two independent hosted model instances; not human"
    comparison["rater_models"] = list(RATER_MODELS)

    report = {
        "format": FORMAT,
        "version": VERSION,
        "frozen": fixture.get("frozen"),
        "fixture_sha256": digest,
        "fixture_path": str(args.fixture.resolve().relative_to(PROJECT)),
        "scorecard": {
            "supported": supported,
            "breadth": breadth,
            "breadth_provenance": "independent model author; not used for tuning",
        },
        "failure_taxonomy": _failure_taxonomy(breadth_rows),
        "supported_rows": [
            {key: row[key] for key in (
                "id", "category", "provenance", "status", "observed", "unsafe",
                "failures", "duration_s", "replies")}
            for row in supported_rows
        ],
        "breadth_rows": [
            {key: row[key] for key in (
                "id", "category", "provenance", "status", "observed", "unsafe",
                "failures", "duration_s", "replies")}
            for row in breadth_rows
        ],
        "comparison": comparison,
        "rater_packet": str(PACKET.resolve().relative_to(PROJECT)),
        "outputs_file": str(OUTPUTS.resolve().relative_to(PROJECT)),
        "licence_inventory": "corpus/phase9_eval/licence_inventory.json",
        "runtime": {"total_s": time.perf_counter() - started},
    }
    report["section2"] = _section2_status(supported, breadth, comparison)
    report["gate"] = {
        "supported_completion_at_least_80pct": supported["completion"] >= 0.8,
        "zero_confident_wrong_supported": supported["unsafe_answers"] == 0,
        "breadth_failures_published": bool(breadth_rows),
        "two_raters_attempted": len(rater_rows) == 2,
        "rater_agreement_reported": bool(agreement.get("available")),
        "comparison_reported": bool(outputs),
        "licence_inventory_published": (PROJECT / "corpus" / "phase9_eval" / "licence_inventory.json").is_file(),
        "limitations_published": True,
        "human_independent_raters": False,
    }
    report["gate_passed"] = all(
        value for key, value in report["gate"].items()
        if key != "human_independent_raters")
    report["external_human_gate_passed"] = (
        report["gate"]["human_independent_raters"]
        and report["gate"]["rater_agreement_reported"])
    report["full_section2_gate_passed"] = False
    report["rater_agreement"] = agreement
    report["rater_rows"] = rater_rows

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"Supported subset: {supported['passed']}/{supported['tasks']} "
          f"({supported['completion']:.1%}); unsafe={supported['unsafe_answers']}")
    print(f"Breadth probes: {breadth['passed']}/{breadth['tasks']} "
          f"({breadth['completion']:.1%}); unsafe={breadth['unsafe_answers']}")
    print(f"Raters: {'agreement available' if agreement.get('available') else 'unavailable'}")
    print(f"Comparison probes: {len(outputs)}")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'} "
          f"(human external gate: {'PASS' if report['external_human_gate_passed'] else 'OPEN'})")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
