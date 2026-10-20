"""Append-only learning instrumentation for typed plan executions.

Every completed or failed plan records the request, route, frame, actions,
step outcomes, evidence references, and the failure that would have been worth
learning from. The log is deliberately plain JSONL so it can be inspected,
replayed, and summarized without coupling to the chat process.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

FORMAT = "crms-plan-log"
VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _evidence(steps: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in steps:
        for item in step.get("evidence", ()) or ():
            if not isinstance(item, Mapping):
                continue
            rows.append({
                "kind": str(item.get("kind", "")),
                "ref": str(item.get("ref", "")),
                "source": item.get("source"),
            })
    return rows


def _actions(steps: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(step.get("action", "")) for step in steps
            if isinstance(step, Mapping) and step.get("action")]


def record_plan(
        *, request: str, route: str, status: str,
        goal: str | None = None, domain: str | None = None,
        frame_id: str | None = None, plan: Mapping[str, Any] | None = None,
        steps: Iterable[Mapping[str, Any]] = (),
        failures: Iterable[str] = ()) -> dict[str, Any]:
    step_rows = [dict(step) for step in steps if isinstance(step, Mapping)]
    failure_rows = [str(value) for value in failures if str(value).strip()]
    actions = _actions(step_rows)
    evidence = _evidence(step_rows)
    learning = None
    if status != "answered" and failure_rows:
        learning = {
            "kind": "failure",
            "action": actions[-1] if actions else None,
            "reason": failure_rows[0],
        }
    elif status == "answered" and evidence:
        learning = {
            "kind": "success",
            "rules": sorted({
                row["ref"] for row in evidence
                if row["kind"] in {"rule", "procedure"}
            }),
        }
    return {
        "format": FORMAT,
        "version": VERSION,
        "at": _now(),
        "request": request,
        "route": route,
        "status": status,
        "goal": goal,
        "domain": domain,
        "request_frame_id": frame_id,
        "plan_artifact_id": (plan or {}).get("artifact_id"),
        "actions": actions,
        "steps": [
            {
                "step_id": str(step.get("step_id", "")),
                "status": str(step.get("status", "")),
                "reason_code": str(step.get("reason_code", "")),
            }
            for step in step_rows
        ],
        "evidence": evidence,
        "failures": failure_rows,
        "learning_candidate": learning,
    }


def append_plan(path: str | Path, record: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False,
                                sort_keys=True) + "\n")


def load_plan_log(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("format") == FORMAT:
            records.append(item)
    return records


def summarize_plan_log(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    total = len(rows)
    answered = sum(1 for row in rows if row.get("status") == "answered")
    by_route: dict[str, int] = {}
    by_goal: dict[str, int] = {}
    by_status: dict[str, int] = {}
    frames: set[str] = set()
    actions: set[str] = set()
    procedures: set[str] = set()
    failures: list[str] = []
    for row in rows:
        route = str(row.get("route") or "")
        by_route[route] = by_route.get(route, 0) + 1
        goal = str(row.get("goal") or row.get("domain") or "")
        by_goal[goal] = by_goal.get(goal, 0) + 1
        status = str(row.get("status") or "")
        by_status[status] = by_status.get(status, 0) + 1
        frame = row.get("request_frame_id")
        if isinstance(frame, str) and frame:
            frames.add(frame)
        actions.update(str(action) for action in row.get("actions", ()) if action)
        for item in row.get("evidence", ()) or ():
            if isinstance(item, Mapping) and item.get("kind") in {
                    "rule", "procedure"}:
                procedures.add(str(item.get("ref", "")))
        failures.extend(str(value) for value in row.get("failures", ()) if value)
    return {
        "total": total,
        "answered": answered,
        "success_rate": (answered / total) if total else 0.0,
        "by_route": dict(sorted(by_route.items())),
        "by_goal": dict(sorted(by_goal.items())),
        "by_status": dict(sorted(by_status.items())),
        "distinct_frames": len(frames),
        "distinct_actions": len(actions),
        "distinct_procedures": len(procedures),
        "failure_count": len(failures),
    }


def plan_trace(plan: Mapping[str, Any] | None,
               results: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Merge planned actions/checks with executed step status and evidence."""
    if not isinstance(plan, Mapping):
        return [dict(step) for step in results if isinstance(step, Mapping)]
    by_id = {
        str(step.get("step_id", "")): dict(step)
        for step in results if isinstance(step, Mapping)
    }
    trace: list[dict[str, Any]] = []
    for planned in plan.get("steps", ()) or ():
        if not isinstance(planned, Mapping):
            continue
        step_id = str(planned.get("id", ""))
        executed = by_id.get(step_id, {})
        trace.append({
            "step_id": step_id,
            "action": str(planned.get("action", "")),
            "check": dict(planned.get("check") or {}),
            "status": str(executed.get("status", "planned")),
            "detail": str(executed.get("detail", "")),
            "reason_code": str(executed.get("reason_code", "")),
            "evidence": executed.get("evidence", planned.get("evidence", ())),
        })
    return trace


def render_plan_line(plan: Mapping[str, Any] | None,
                     steps: Iterable[Mapping[str, Any]]) -> str:
    """One-line plan trace: actions, statuses, checks, and evidence refs."""
    plan = plan or {}
    step_rows = [step for step in steps if isinstance(step, Mapping)]
    actions = []
    for step in step_rows:
        check = step.get("check") or {}
        check_kind = check.get("kind", "") if isinstance(check, Mapping) else ""
        actions.append(
            f"{step.get('step_id')} {step.get('action')} "
            f"[{step.get('status')}"
            + (f"; {check_kind}" if check_kind else "") + "]")
    evidence = []
    for step in step_rows:
        for item in step.get("evidence", ()) or ():
            if isinstance(item, Mapping):
                evidence.append(
                    f"{item.get('kind')}:{str(item.get('ref', ''))[:80]}")
    text = f"Plan {plan.get('artifact_id', '')}: " + " -> ".join(actions)
    if evidence:
        text += ". Evidence: " + "; ".join(evidence[:6])
    return text + "."


def render_plan_explanation(record: Mapping[str, Any]) -> str:
    lines = [
        f"Plan {(record.get('plan') or {}).get('artifact_id', 'unknown')} "
        f"for {record.get('goal') or record.get('domain') or 'request'}:"
    ]
    for step in record.get("steps", ()) or ():
        if not isinstance(step, Mapping):
            continue
        detail = str(step.get("detail") or "").strip()
        check = step.get("check") or {}
        check_text = ""
        if isinstance(check, Mapping):
            check_text = f"; check={check.get('kind', '')}"
        lines.append(
            f"- {step.get('step_id')}: {step.get('action')} "
            f"[{step.get('status')}]{check_text}"
            + (f" — {detail}" if detail else ""))
        for evidence in step.get("evidence", ()) or ():
            if isinstance(evidence, Mapping):
                source = evidence.get("source")
                lines.append(
                    f"  evidence: {evidence.get('kind')} "
                    f"{evidence.get('ref')}"
                    + (f" ({source})" if source else ""))
    if record.get("failures"):
        lines.append("Failures: " + "; ".join(record["failures"]))
    return "\n".join(lines)
