"""Drive the real CRMS chat CLI in an isolated workspace.

The driver treats chat as a black box: it writes the task's source documents,
starts a fresh process, feeds turns, optionally restarts to exercise reload, and
returns the complete output. Fixture setup is deliberately limited to source
text so the harness cannot answer on the system's behalf.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .schema import RESTART, Task

PROJECT = Path(__file__).resolve().parents[1]
CHAT = PROJECT / "crms_chat.py"


class ChatError(RuntimeError):
    """A chat process failed to run to completion."""


@dataclass
class ChatOutput:
    transcript: str
    replies: list[str]
    segments: int
    duration_s: float


def _state_options(root: Path, task: Task) -> list[str]:
    index_name = "research.sqlite" if task.index_kind == "sqlite" else "research.json"
    return [
        "--knowledge", str(root / "knowledge.json"),
        "--rules", str(root / "rules.json"),
        "--index", str(root / index_name),
        "--math", str(root / "math.json"),
        "--translations", str(root / "translations.json"),
        "--dialogue-state", str(root / "dialogue.json"),
        "--rule-session", str(root / "rule-session.json"),
        "--candidate-session", str(root / "candidate-session.json"),
        "--math-session", str(root / "math-session.json"),
        "--translation-session", str(root / "translation-session.json"),
        "--feedback-db", str(root / "feedback.sqlite3"),
        "--rule-depth", str(task.rule_depth),
    ]


def _write_documents(root: Path, task: Task) -> Path | None:
    if not task.documents:
        return None
    sources = root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    for document in task.documents:
        target = sources / document.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document.text, encoding="utf-8")
    return sources


def _segments(turns: tuple[str, ...]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for turn in turns:
        if turn == RESTART:
            if not segments[-1]:
                raise ValueError("restart marker cannot start a transcript")
            segments.append([])
        else:
            segments[-1].append(turn)
    if not segments[-1]:
        raise ValueError("transcript cannot end with a restart marker")
    return segments


def _replies(transcript: str) -> list[str]:
    """Extract assistant replies from the CLI transcript.

    The CLI prints ``you> CRMS> ...`` and continuation lines without a prefix.
    A reply ends at the next ``you>`` prompt. This is only for reporting; all
    oracles run against the full transcript.
    """

    replies: list[str] = []
    current: list[str] | None = None
    for line in transcript.splitlines():
        marker = line.find("CRMS>")
        if marker >= 0:
            if current:
                replies.append("\n".join(current).strip())
            current = [line[marker + len("CRMS>"):].strip()]
            continue
        if current is None:
            continue
        if line.startswith("you>"):
            replies.append("\n".join(current).strip())
            current = None
            continue
        current.append(line)
    if current:
        replies.append("\n".join(current).strip())
    return [reply for reply in replies if reply]


def run_task(task: Task, *, root: Path | None = None,
             keep_workspace: bool = False) -> ChatOutput:
    """Run one task in a clean workspace and return its transcript."""

    temporary = root is None
    workspace = Path(root) if root is not None else Path(
        tempfile.mkdtemp(prefix=f"crms-scorecard-{task.id}-"))
    started = time.perf_counter()
    transcript_parts: list[str] = []
    segments_run = 0
    try:
        sources = _write_documents(workspace, task)
        segments = _segments(task.turns)
        for position, turns in enumerate(segments):
            segment_turns = list(turns)
            if position == 0 and sources is not None:
                segment_turns.insert(0, f"/source-dir {sources}")
            command = [sys.executable, str(CHAT), *_state_options(workspace, task)]
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = "0"
            environment["PYTHONIOENCODING"] = "utf-8"
            try:
                result = subprocess.run(
                    command,
                    input="\n".join([*segment_turns, "/quit"]) + "\n",
                    text=True,
                    capture_output=True,
                    cwd=workspace,
                    env=environment,
                    timeout=task.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ChatError(
                    f"chat timed out after {task.timeout_s}s in segment "
                    f"{position + 1}") from error
            output = result.stdout + result.stderr
            if (result.returncode != 0
                    or "Traceback (most recent call last)" in output):
                tail = output[-3000:]
                raise ChatError(
                    f"chat failed in segment {position + 1} "
                    f"(exit {result.returncode}):\n{tail}")
            transcript_parts.append(
                f"===== segment {position + 1} =====\n{output}")
            segments_run += 1
        transcript = "\n".join(transcript_parts)
    finally:
        if temporary and not keep_workspace:
            import shutil
            shutil.rmtree(workspace, ignore_errors=True)
    return ChatOutput(
        transcript=transcript,
        replies=_replies(transcript),
        segments=segments_run,
        duration_s=time.perf_counter() - started,
    )
