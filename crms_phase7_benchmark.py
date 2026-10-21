"""Frozen Phase 7 corpus evaluation and gate.

The positive tasks are checked against the exact cited source passage, not
against the retriever's own ranking. A citation is valid only when the stored
digest/offset reference resolves back to text containing an accepted expected
phrase. Negative controls require an explicit abstention.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Sequence

FORMAT = "crms-phase7-eval"
VERSION = 1
POSITIVE_TARGET = 0.80
NEGATIVE_TARGET = 0.90


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    text = (text.replace("\u2019", "'").replace("\u2018", "'")
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2013", "-").replace("\u2014", "-"))
    return " ".join(text.split())


def _contains(haystack: str, needles: Sequence[str]) -> bool:
    normalized = _normalize(haystack)
    return any(_normalize(needle) in normalized for needle in needles)


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def load_fixture(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    sidecar = source.with_suffix(".sha256")
    if sidecar.is_file():
        expected = sidecar.read_text(encoding="ascii").split()[0]
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if expected != actual:
            raise ValueError("Phase 7 fixture does not match its frozen digest")
    if payload.get("format") != FORMAT:
        raise ValueError("not a CRMS Phase 7 evaluation fixture")
    if payload.get("version") != VERSION:
        raise ValueError("unsupported Phase 7 evaluation fixture version")
    if not isinstance(payload.get("tasks"), list) or not payload["tasks"]:
        raise ValueError("evaluation fixture has no positive tasks")
    if not isinstance(payload.get("negative_controls"), list):
        raise ValueError("evaluation fixture has no negative controls")
    for task in payload["tasks"]:
        if task.get("kind") != "positive":
            raise ValueError(f"positive task has the wrong kind: {task.get('id')}")
        if not task.get("expected_any"):
            raise ValueError(f"positive task has no expected phrase: {task.get('id')}")
    return payload


def _row_for_positive(reader, task: Mapping[str, Any]) -> dict[str, Any]:
    result = reader.answer_question(task["question"])
    answer = str(result.get("answer", ""))
    citation = str(result.get("citation", ""))
    cited_text = ""
    citation_error = ""
    if citation:
        try:
            cited_text = reader.resolve_citation(citation)
        except Exception as error:  # a bad citation is a failed task, not a crash
            citation_error = str(error)
    expected = list(task.get("expected_any", ()))
    answer_match = _contains(answer, expected)
    cited_match = _contains(cited_text, expected)
    citation_valid = bool(citation and cited_text and not citation_error
                          and cited_match)
    answered = result.get("status") == "answered"
    target = task.get("target_document_id")
    return {
        "task": task["id"],
        "domain": task.get("domain", "unknown"),
        "question": task["question"],
        "expected_any": expected,
        "target_document_id": target,
        "status": result.get("status"),
        "answer": answer,
        "citation": citation,
        "resolved_chars": len(cited_text),
        "citation_error": citation_error,
        "document_id": result.get("document_id", ""),
        "title": result.get("title", ""),
        "score": result.get("score", 0.0),
        "matched_terms": result.get("matched_terms", []),
        "coverage": result.get("coverage", 0.0),
        "latency_ms": result.get("latency_ms", 0.0),
        "answer_match": answer_match,
        "cited_match": cited_match,
        "citation_valid": citation_valid,
        "target_matched": bool(target and result.get("document_id") == target),
        "correct": bool(answered and answer_match and citation_valid),
        "confident_wrong": bool(answered and not answer_match),
        "invalid_citation": bool(answered and not citation_valid),
    }


def _row_for_negative(reader, task: Mapping[str, Any]) -> dict[str, Any]:
    result = reader.answer_question(task["question"])
    answered = result.get("status") == "answered"
    return {
        "task": task["id"],
        "domain": "negative",
        "question": task["question"],
        "status": result.get("status"),
        "answer": result.get("answer", ""),
        "citation": result.get("citation", ""),
        "document_id": result.get("document_id", ""),
        "title": result.get("title", ""),
        "score": result.get("score", 0.0),
        "matched_terms": result.get("matched_terms", []),
        "coverage": result.get("coverage", 0.0),
        "latency_ms": result.get("latency_ms", 0.0),
        "abstained": not answered,
    }


def _slice(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    correct = sum(1 for row in rows if row.get("correct"))
    wrong = sum(1 for row in rows if row.get("confident_wrong"))
    invalid = sum(1 for row in rows if row.get("invalid_citation"))
    latencies = [float(row.get("latency_ms", 0.0)) for row in rows]
    return {
        "tasks": total,
        "correct": correct,
        "completion": correct / total if total else 0.0,
        "confident_wrong": wrong,
        "invalid_citations": invalid,
        "target_matched": sum(1 for row in rows if row.get("target_matched")),
        "median_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": _percentile(latencies, 0.95),
    }


def evaluate(reader, fixture: Mapping[str, Any], *,
             corpus: Mapping[str, Any] | None = None,
             clean_room: Mapping[str, Any] | None = None
             ) -> dict[str, Any]:
    """Run the frozen fixture and return counts, rates, and a gate decision."""
    positive_rows = [_row_for_positive(reader, task)
                     for task in fixture["tasks"]]
    negative_rows = [_row_for_negative(reader, task)
                     for task in fixture["negative_controls"]]

    slices: dict[str, dict[str, Any]] = {}
    for row in positive_rows:
        slices.setdefault(row["domain"], []).append(row)
    slices = {name: _slice(rows) for name, rows in sorted(slices.items())}
    negative_slice = _slice(negative_rows)

    all_rows = positive_rows + negative_rows
    latencies = [float(row.get("latency_ms", 0.0)) for row in all_rows]
    overall = {
        "tasks": len(positive_rows),
        "correct": sum(1 for row in positive_rows if row["correct"]),
        "completion": (sum(1 for row in positive_rows if row["correct"])
                       / len(positive_rows)) if positive_rows else 0.0,
        "confident_wrong": sum(
            1 for row in positive_rows if row["confident_wrong"]),
        "invalid_citations": sum(
            1 for row in positive_rows if row["invalid_citation"]),
        "target_matched": sum(
            1 for row in positive_rows if row["target_matched"]),
        "negative_total": len(negative_rows),
        "negative_abstained": sum(
            1 for row in negative_rows if row["abstained"]),
        "negative_answered": sum(
            1 for row in negative_rows if not row["abstained"]),
        "median_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": _percentile(latencies, 0.95),
    }

    corpus = dict(corpus or {})
    licence = dict(corpus.get("licence_coverage", {})) if corpus else {}
    throughput = dict(corpus.get("throughput", {})) if corpus else {}
    clean_room = dict(clean_room or {})
    gate = {
        "minimum_positive_completion": POSITIVE_TARGET,
        "positive_completion": overall["completion"],
        "completion_met": overall["completion"] >= POSITIVE_TARGET,
        "zero_confident_wrong": overall["confident_wrong"] == 0,
        "zero_invalid_citations": overall["invalid_citations"] == 0,
        "negative_abstention_target": NEGATIVE_TARGET,
        "negative_abstention": (
            overall["negative_abstained"] / max(1, overall["negative_total"])),
        "negative_abstention_met": (
            overall["negative_abstained"]
            / max(1, overall["negative_total"])) >= NEGATIVE_TARGET,
        "corpus_words": corpus.get("words", 0),
        "corpus_word_target_met": int(corpus.get("words", 0)) >= 50_000_000,
        "licence_coverage": licence.get("coverage", 0.0),
        "licence_coverage_met": licence.get("coverage", 0.0) >= 1.0,
        "shards": corpus.get("shards", 0),
        "sharded_index": int(corpus.get("shards", 0)) >= 4,
        "throughput_reported": bool(throughput),
        "latency_reported": bool(latencies),
        "clean_room_copy": bool(clean_room.get("copied")),
        "originals_required": bool(clean_room.get("originals_required", True)),
    }
    gate_passed = all((
        gate["completion_met"],
        gate["zero_confident_wrong"],
        gate["zero_invalid_citations"],
        gate["negative_abstention_met"],
        gate["corpus_word_target_met"],
        gate["licence_coverage_met"],
        gate["sharded_index"],
        gate["throughput_reported"],
        gate["latency_reported"],
        gate["clean_room_copy"],
        not gate["originals_required"],
    ))
    return {
        "format": FORMAT,
        "version": VERSION,
        "fixture": {
            "frozen": fixture.get("frozen"),
            "evaluation_documents": len(fixture.get("evaluation_documents", [])),
            "positive_tasks": len(positive_rows),
            "negative_controls": len(negative_rows),
            "domains": sorted(slices),
        },
        "gate": gate,
        "gate_passed": gate_passed,
        "overall": overall,
        "slices": slices,
        "negative": negative_slice,
        "corpus": corpus,
        "clean_room": clean_room,
        "rows": positive_rows,
        "negative_rows": negative_rows,
    }


def main() -> int:
    from crms_corpus_program import CorpusReader
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    fixture = load_fixture(args.fixture)
    reader = CorpusReader(args.corpus)
    try:
        report = evaluate(reader, fixture, corpus=reader.summary())
    finally:
        reader.close()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
