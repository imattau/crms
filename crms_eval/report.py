"""Write scorecard reports as JSON and Markdown."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .metrics import TaskResult


def write_report(path: Path, *, suite: str, results: list[TaskResult],
                 summary: dict[str, Any], metadata: dict[str, Any] | None = None
                 ) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md`` under ``path``."""

    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "suite": suite,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "metadata": metadata or {},
        "summary": summary,
        "tasks": [asdict(result) for result in results],
    }
    json_path = path / "report.json"
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path = path / "report.md"
    markdown_path.write_text(_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def _rate(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value * 100:.1f}%"
    return str(value)


def _markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        f"# CRMS scorecard: {payload['suite']}",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Tasks | {summary['total']} |",
        f"| Gated tasks | {summary['gated_total']} |",
        f"| Passed | {summary['passed']} |",
        f"| Failed | {summary['failed']} |",
        f"| Errors | {summary['errors']} |",
        f"| Pass rate | {_rate(summary['pass_rate'])} |",
        f"| Unsafe answers | {summary['unsafe_answers']} |",
        f"| Known failures | {summary['known_failures']} "
        f"({summary['known_failures_passed']} now passing) |",
        f"| Median task duration | {summary['duration_s']['median']} s |",
        f"| p95 task duration | {summary['duration_s']['p95']} s |",
        "",
        "## By category",
        "",
        "| Category | Total | Passed | Failed | Errors | Pass rate |",
        "|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(summary["by_category"].items()):
        lines.append(
            f"| {name} | {entry['total']} | {entry['passed']} | "
            f"{entry['failed']} | {entry['errors']} | "
            f"{_rate(entry['pass_rate'])} |")
    lines.extend(["", "## Tasks", "",
                  "| Task | Category | Result | Observed | Time |",
                  "|---|---|---|---|---|"])
    for task in payload["tasks"]:
        label = task["id"]
        if task["known_failure"]:
            label += " *(known failure)*"
        lines.append(
            f"| {label} | {task['category']} | {task['status']} | "
            f"{task['observed']} | {task['duration_s']:.2f}s |")
    failures = [task for task in payload["tasks"]
                if task["status"] != "pass" and not task["known_failure"]]
    if failures:
        lines.extend(["", "## Gated failures", ""])
        for task in failures:
            lines.append(f"### {task['id']} ({task['category']})")
            if task["notes"]:
                lines.append(f"_{task['notes']}_")
            for failure in task["failures"]:
                lines.append(f"- {failure}")
            lines.append("")
    known = [task for task in payload["tasks"] if task["known_failure"]]
    if known:
        lines.extend(["", "## Known failures", ""])
        for task in known:
            state = "passing" if task["status"] == "pass" else "still failing"
            lines.append(f"### {task['id']} — {state}")
            if task["notes"]:
                lines.append(f"_{task['notes']}_")
            for failure in task["failures"]:
                lines.append(f"- {failure}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
