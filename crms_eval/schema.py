"""Suite and task schema for the CRMS scorecard.

A suite is a JSONL file with one task per line. Blank lines and ``#`` comments
are ignored. Every task is self-contained: it declares its source fixtures,
chat turns, and the oracle that decides success.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

OUTCOMES = frozenset({"answer", "abstain", "clarify"})
INDEX_KINDS = frozenset({"json", "sqlite"})
RESTART = "__restart__"


@dataclass(frozen=True)
class Document:
    path: str
    text: str


@dataclass(frozen=True)
class Citation:
    source: str
    quote: str


@dataclass(frozen=True)
class Occurrence:
    text: str
    count: int


@dataclass(frozen=True)
class Expectation:
    """What a passing transcript must contain.

    ``contains`` and ``regex`` are positive checks; ``not_contains`` are
    negative checks. ``citations`` requires both the source label and the exact
    quote in the transcript. ``outcome`` states the expected answer class, so
    abstention and clarification are measured rather than guessed.
    """

    contains: tuple[str, ...] = ()
    not_contains: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    occurrences: tuple[Occurrence, ...] = ()
    outcome: str = "answer"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "Expectation":
        raw = raw or {}
        outcome = str(raw.get("outcome", "answer"))
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown expected outcome: {outcome!r}")
        return cls(
            contains=_strings(raw.get("contains")),
            not_contains=_strings(raw.get("not_contains")),
            regex=_strings(raw.get("regex")),
            citations=tuple(
                Citation(str(item["source"]), str(item["quote"]))
                for item in raw.get("citations", ())
            ),
            occurrences=tuple(
                Occurrence(str(item["text"]), int(item["count"]))
                for item in raw.get("occurrences", ())
            ),
            outcome=outcome,
        )


@dataclass(frozen=True)
class Task:
    id: str
    category: str
    provenance: str
    turns: tuple[str, ...]
    expectation: Expectation
    documents: tuple[Document, ...] = ()
    index_kind: str = "json"
    rule_depth: int = 2
    timeout_s: int = 180
    known_failure: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Task":
        missing = [key for key in ("id", "category", "turns") if key not in raw]
        if missing:
            raise ValueError(f"task missing required keys: {missing}")
        task_id = str(raw["id"])
        if not task_id or any(ch.isspace() for ch in task_id):
            raise ValueError(f"task id must be a non-empty slug: {task_id!r}")
        turns = tuple(str(turn) for turn in raw["turns"])
        if not turns:
            raise ValueError(f"task {task_id!r} has no turns")
        index_kind = str(raw.get("index_kind", "json"))
        if index_kind not in INDEX_KINDS:
            raise ValueError(f"task {task_id!r} has unknown index_kind: {index_kind!r}")
        rule_depth = int(raw.get("rule_depth", 2))
        if rule_depth not in (1, 2, 3, 4):
            raise ValueError(f"task {task_id!r} has invalid rule_depth: {rule_depth}")
        documents = tuple(
            Document(str(item["path"]), str(item["text"]))
            for item in raw.get("documents", ())
        )
        for document in documents:
            if not document.path or Path(document.path).is_absolute():
                raise ValueError(
                    f"task {task_id!r} document path must be relative: "
                    f"{document.path!r}")
        return cls(
            id=task_id,
            category=str(raw["category"]),
            provenance=str(raw.get("provenance", "authored")),
            turns=turns,
            expectation=Expectation.from_dict(raw.get("expect")),
            documents=documents,
            index_kind=index_kind,
            rule_depth=rule_depth,
            timeout_s=int(raw.get("timeout_s", 180)),
            known_failure=bool(raw.get("known_failure", False)),
            notes=str(raw.get("notes", "")),
        )


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def load_suite(path: str | Path) -> list[Task]:
    """Load and validate a JSONL suite."""

    suite_path = Path(path)
    tasks: list[Task] = []
    seen: set[str] = set()
    for line_number, line in enumerate(
            suite_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{suite_path}:{line_number}: invalid JSON: {error}") from error
        task = Task.from_dict(raw)
        if task.id in seen:
            raise ValueError(f"{suite_path}:{line_number}: duplicate task id {task.id!r}")
        seen.add(task.id)
        tasks.append(task)
    if not tasks:
        raise ValueError(f"{suite_path}: suite contains no tasks")
    return tasks


def iter_markers(turns: Iterable[str]) -> list[str]:
    return [turn for turn in turns if turn == RESTART]
