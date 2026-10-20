"""Run a scorecard suite and produce structured results."""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any, Iterable

from .driver import ChatError, run_task
from .metrics import TaskResult, summarize
from .oracles import evaluate
from .schema import Task

PROJECT = Path(__file__).resolve().parents[1]


def run_task_result(task: Task, *, keep_workspace: bool = False) -> TaskResult:
    try:
        output = run_task(task, keep_workspace=keep_workspace)
    except (ChatError, OSError, ValueError) as error:
        return TaskResult(
            id=task.id,
            category=task.category,
            provenance=task.provenance,
            status="error",
            observed="error",
            failures=(str(error),),
            unsafe=False,
            duration_s=0.0,
            known_failure=task.known_failure,
            notes=task.notes,
        )
    oracle = evaluate(task, output.transcript, output.replies)
    return TaskResult(
        id=task.id,
        category=task.category,
        provenance=task.provenance,
        status="pass" if oracle.passed else "fail",
        observed=oracle.observed,
        failures=oracle.failures,
        unsafe=oracle.unsafe,
        duration_s=output.duration_s,
        known_failure=task.known_failure,
        notes=task.notes,
    )


def run_suite(tasks: Iterable[Task], *, suite_name: str = "suite",
              keep_workspaces: bool = False,
              fail_fast: bool = False) -> dict[str, Any]:
    results: list[TaskResult] = []
    for task in tasks:
        result = run_task_result(task, keep_workspace=keep_workspaces)
        results.append(result)
        if fail_fast and result.status != "pass" and not task.known_failure:
            break
    return {
        "suite": suite_name,
        "results": results,
        "summary": summarize(results),
        "metadata": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "project": str(PROJECT),
        },
    }
