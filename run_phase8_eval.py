#!/usr/bin/env python3
"""Run the frozen Phase 8 clean-room release scorecard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import hashlib

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_eval.driver import _replies  # noqa: E402
from crms_eval.oracles import evaluate  # noqa: E402
from crms_eval.schema import RESTART, Task  # noqa: E402
from crms_package import export_model_database  # noqa: E402
from crms_phase8_model import build_release, open_release  # noqa: E402
from crms_rule_registry import RuleRegistry  # noqa: E402
from crms_model import CRMSModel  # noqa: E402

FORMAT = "crms-phase8-eval"
VERSION = 1
DEFAULT_FIXTURE = PROJECT / "corpus" / "phase8_eval" / "fixture.json"
DEFAULT_RELEASE = PROJECT / "data" / "phase8_release"
DEFAULT_REPORT = PROJECT / "experiments" / "reports" / "phase8_release.json"
CHAT = PROJECT / "crms_chat.py"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def _state_options(root: Path) -> list[str]:
    return [
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--index", str(root / "research.sqlite"),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidate-session.json"),
        "--math-session", str(root / "math-session.json"),
        "--translation-session", str(root / "translation-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
        "--rule-depth", "2",
    ]


def _run_chat(root: Path, turns: list[str], *, model_db: Path | None = None,
              timeout: int = 180) -> str:
    if model_db is None:
        command = [sys.executable, str(CHAT), *_state_options(root)]
    else:
        command = [
            sys.executable, str(CHAT), "--model-db", str(model_db),
            "--dialogue-state", str(root / "dialogue.json"),
            "--rule-session", str(root / "rule-session.json"),
            "--candidate-session", str(root / "candidate-session.json"),
            "--math-session", str(root / "math-session.json"),
            "--translation-session", str(root / "translation-session.json"),
            "--feedback-db", str(root / "feedback.sqlite3"),
            "--rule-depth", "2",
        ]
    result = subprocess.run(
        command, input="\n".join([*turns, "/quit"]) + "\n", text=True,
        capture_output=True, cwd=root, timeout=timeout, check=False,
        env={**__import__("os").environ, "PYTHONHASHSEED": "0",
             "PYTHONIOENCODING": "utf-8"})
    output = result.stdout + result.stderr
    if (result.returncode != 0
            or "Traceback (most recent call last)" in output):
        raise RuntimeError(
            f"chat failed (exit {result.returncode}):\n{output[-3000:]}")
    return output


def _segments(turns: tuple[str, ...]) -> list[list[str]]:
    parts: list[list[str]] = [[]]
    for turn in turns:
        if turn == RESTART:
            if not parts[-1]:
                raise ValueError("restart cannot start a transcript")
            parts.append([])
        else:
            parts[-1].append(turn)
    if not parts[-1]:
        raise ValueError("transcript cannot end with a restart")
    return parts


def _build_seed(fixture: dict, root: Path) -> tuple[Path, float]:
    started = time.perf_counter()
    sources = root / "sources"
    sources.mkdir(parents=True)
    for item in fixture["sources"]:
        target = sources / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item["text"], encoding="utf-8")
    turns = [turn.replace("__SOURCES__", str(sources))
             for turn in fixture["seed_turns"]]
    _run_chat(root, turns)
    if not (root / "knowledge.json").is_file():
        raise RuntimeError("seed chat did not create knowledge memory")
    if not (root / "rules.json").is_file():
        CRMSModel().save(root / "rules.json")
    model = root / "model.sqlite"
    export_model_database(
        model, knowledge=root / "knowledge.json", rules=root / "rules.json",
        math=root / "math.json" if (root / "math.json").is_file() else None,
        research_index=root / "research.sqlite")
    return model, time.perf_counter() - started


def _build_registry(path: Path) -> None:
    registry = RuleRegistry()
    registry.propose(
        rule_id="phase8-sum", family="procedure",
        statement="Sum every value in an integer list.",
        scope="Phase 8 fixture integer lists",
        payload={"operation": "sum", "steps": [{"operation": "sum_values"}]},
        provenance=({"source": "phase8-fixture", "kind": "procedure"},),
        trust="taught")
    registry.validate(
        "phase8-sum", oracle="phase8-fixture-replay", passed=True,
        cases=2, independent_sources=1,
        detail="fixture examples replay the sum procedure")
    registry.activate("phase8-sum", mode="review", authoriser="phase8-fixture")
    registry.save(path)


def _licence_rows(fixture: dict) -> list[dict]:
    rows = []
    by_path = {item["path"]: item for item in fixture["sources"]}
    for row in fixture["licences"]:
        item = dict(row)
        source = by_path[item.pop("path")]
        item["body_sha256"] = _sha256_text(source["text"])
        rows.append(item)
    return rows


def _build_release(fixture: dict, release: Path) -> tuple[dict, float]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="crms-phase8-seed-") as temporary:
        seed = Path(temporary)
        model, _ = _build_seed(fixture, seed)
        registry = seed / "registry.sqlite"
        _build_registry(registry)
        inspect = build_release(
            release, model_db=model, licences=_licence_rows(fixture),
            dependencies=fixture["dependencies"],
            dependency_edges=fixture["edges"], registry_db=registry,
            corrections=fixture["corrections"], replace=True)
    return inspect, time.perf_counter() - started


def _run_task(task: Task, model_dir: Path, workspace: Path,
              timeout: int = 180) -> tuple[str, list[str], float]:
    started = time.perf_counter()
    task_root = workspace / task.id
    task_root.mkdir(parents=True)
    copied_model = task_root / "release"
    shutil.copytree(model_dir, copied_model)
    transcript_parts: list[str] = []
    for segment, turns in enumerate(_segments(task.turns), start=1):
        output = _run_chat(task_root, list(turns),
                           model_db=copied_model / "model.sqlite",
                           timeout=timeout)
        transcript_parts.append(
            f"===== segment {segment} =====\n{output}")
    transcript = "\n".join(transcript_parts)
    return transcript, _replies(transcript), time.perf_counter() - started


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(0.95 * len(ordered)) - 1))
    return ordered[index]


def _score(fixture: dict, release: Path, *, clean_room: bool) -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="crms-phase8-run-") as temporary:
        root = Path(temporary)
        if clean_room:
            release_copy = root / "release-copy"
            shutil.copytree(release, release_copy)
            hidden = release.with_name(release.name + ".clean-room-hidden")
            if hidden.exists():
                raise FileExistsError(f"clean-room scratch exists: {hidden}")
            release.rename(hidden)
            try:
                result = _score_release(fixture, release_copy, root)
            finally:
                hidden.rename(release)
            result["clean_room"] = {
                "copied": True,
                "originals_hidden_during_eval": True,
                "originals_required": False,
                "source_directory_required": False,
                "mode": ("release copied to a temporary directory; the "
                         "original release was moved aside for the entire run; "
                         "each task received a fresh copy of the release"),
            }
            return result
        result = _score_release(fixture, release, root)
        result["clean_room"] = {
            "copied": False,
            "originals_hidden_during_eval": False,
            "originals_required": True,
            "source_directory_required": False,
        }
        return result


def _score_release(fixture: dict, release: Path, root: Path) -> dict:
    started = time.perf_counter()
    rows = []
    durations = []
    for raw in fixture["tasks"]:
        task = Task.from_dict(raw)
        try:
            transcript, replies, duration = _run_task(
                task, release, root, timeout=task.timeout_s)
            oracle = evaluate(task, transcript, replies)
            row = {
                "id": task.id, "category": task.category,
                "status": "pass" if oracle.passed else "fail",
                "observed": oracle.observed, "failures": list(oracle.failures),
                "unsafe": oracle.unsafe, "duration_s": duration,
            }
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            row = {
                "id": task.id, "category": task.category, "status": "error",
                "observed": "error", "failures": [str(error)], "unsafe": False,
                "duration_s": 0.0,
            }
        durations.append(row["duration_s"])
        rows.append(row)
    release_info = open_release(release)
    try:
        inspect = release_info.inspect()
        verification = release_info.verify()
        lineage = release_info.lineage("derived:sum-mira")
        corrections = release_info.corrections()
        evidence = release_info.evidence()
    finally:
        release_info.close()
    passed = sum(1 for row in rows if row["status"] == "pass")
    unsafe = sum(1 for row in rows if row["unsafe"])
    return {
        "rows": rows,
        "overall": {
            "tasks": len(rows), "passed": passed,
            "failed": sum(1 for row in rows if row["status"] == "fail"),
            "errors": sum(1 for row in rows if row["status"] == "error"),
            "pass_rate": passed / len(rows) if rows else 0.0,
            "unsafe_answers": unsafe,
            "median_task_s": statistics.median(durations) if durations else 0.0,
            "p95_task_s": _p95(durations),
        },
        "release": inspect,
        "verification": verification,
        "lineage": {
            "node": lineage["node"]["id"],
            "inputs": [edge["source"] for edge in lineage["inputs"]],
            "dependents": [edge["target"] for edge in lineage["dependents"]],
        },
        "corrections": corrections,
        "evidence": evidence,
        "release_bytes": inspect["total_bytes"],
        "model_bytes": inspect["model_bytes"],
        "scoring_s": time.perf_counter() - started,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--release", type=Path, default=DEFAULT_RELEASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--no-clean-room", action="store_true")
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    if fixture.get("format") != FORMAT or fixture.get("version") != VERSION:
        raise SystemExit("unsupported Phase 8 fixture")
    sidecar = args.fixture.with_suffix(".sha256")
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="ascii").split()[0]
        actual = hashlib.sha256(args.fixture.read_bytes()).hexdigest()
        if expected != actual:
            raise SystemExit("Phase 8 fixture does not match its frozen digest")
    release_started = time.perf_counter()
    if args.rebuild or not (args.release / "release.json").is_file():
        release_info, build_s = _build_release(fixture, args.release)
    else:
        existing = open_release(args.release)
        try:
            release_info = existing.inspect()
        finally:
            existing.close()
        build_s = 0.0
    result = _score(
        fixture, args.release, clean_room=not args.no_clean_room)
    result.update({
        "format": FORMAT, "version": VERSION,
        "fixture": {
            "frozen": fixture.get("frozen"),
            "tasks": len(fixture["tasks"]),
            "sources": len(fixture["sources"]),
        },
        "paths": {
            "release": _display(args.release),
            "fixture": _display(args.fixture),
            "report": _display(args.out),
        },
        "runtime": {
            "build_s": build_s,
            "scoring_s": result.pop("scoring_s", 0.0),
            "total_s": time.perf_counter() - release_started,
            "release_bytes": result["release_bytes"],
            "model_bytes": result["model_bytes"],
            "median_task_s": result["overall"]["median_task_s"],
            "p95_task_s": result["overall"]["p95_task_s"],
        },
    })
    gate = {
        "all_tasks_pass": result["overall"]["pass_rate"] == 1.0,
        "zero_unsafe": result["overall"]["unsafe_answers"] == 0,
        "integrity_valid": bool(result["verification"]["valid"]),
        "read_only": bool(result["release"]["read_only"]),
        "model_schema_v4": result["release"]["model_schema"] >= 4,
        "lineage_present": bool(result["lineage"]["inputs"]),
        "corrections_present": bool(result["corrections"]),
        "evidence_present": bool(result["evidence"]),
        "clean_room_copy": bool(result["clean_room"]["copied"]),
        "originals_not_required": not bool(
            result["clean_room"]["originals_required"]),
        "size_and_runtime_reported": (
            result["release_bytes"] > 0
            and result["runtime"]["total_s"] > 0),
    }
    result["gate"] = gate
    result["gate_passed"] = all(gate.values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Release: {release_info['total_bytes']:,} bytes; "
          f"{release_info['research']['documents']} sources; "
          f"{release_info['dependencies']['nodes']} dependency nodes")
    for row in result["rows"]:
        print(f"{row['status'].upper():5s} {row['id']:24s} "
              f"{row['duration_s']:.2f}s")
    print(f"Overall: {result['overall']['passed']}/{result['overall']['tasks']} "
          f"({result['overall']['pass_rate']:.1%})")
    print(f"Gate: {'PASS' if result['gate_passed'] else 'FAIL'}")
    print(f"Report: {args.out}")
    return 0 if result["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
