#!/usr/bin/env python3
"""Run the Phase 7 corpus gate: build, clean-room copy, and held-out scorecard."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_corpus_program import CorpusReader, build_core_corpus  # noqa: E402
from crms_phase7_benchmark import evaluate, load_fixture  # noqa: E402


DEFAULT_CORPUS = PROJECT / "data" / "phase7_core"
DEFAULT_FIXTURE = PROJECT / "corpus" / "phase7_eval" / "fixture.json"
DEFAULT_REPORT = PROJECT / "experiments" / "reports" / "phase7_corpus.json"


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def _evaluation_ids(fixture: dict) -> tuple[str, ...]:
    return tuple(
        item["document_id"]
        for item in fixture.get("evaluation_documents", ()))


def _build(fixture: dict, corpus: Path, *, shards: int, limit: int | None,
           near_dedup: bool, replace: bool,
           exclude_evaluation: bool = False) -> dict:
    holdout = _evaluation_ids(fixture) if exclude_evaluation else ()
    return build_core_corpus(
        corpus, shards=shards, holdout_ids=holdout,
        near_dedup=near_dedup, replace=replace, limit=limit, progress=True)


def _score(root: Path, fixture: dict, *, clean_room: bool
           ) -> tuple[dict, dict]:
    if not clean_room:
        reader = CorpusReader(root)
        try:
            summary = reader.summary()
            present = [document_id for document_id in _evaluation_ids(fixture)
                       if reader.contains_document(document_id)]
            report = evaluate(
                reader, fixture, corpus=summary,
                clean_room={
                    "copied": False,
                    "originals_required": True,
                    "evaluation_documents_present": present,
                    "evaluation_documents_expected": len(
                        fixture.get("evaluation_documents", ())),
                })
            return report, summary
        finally:
            reader.close()

    with tempfile.TemporaryDirectory(
            prefix="crms-phase7-clean-room-") as temporary:
        copied = Path(temporary) / "phase7-core-copy"
        shutil.copytree(root, copied)
        hidden = root.with_name(root.name + ".clean-room-hidden")
        if hidden.exists():
            raise FileExistsError(
                f"clean-room scratch path already exists: {hidden}")
        root.rename(hidden)
        try:
            reader = CorpusReader(copied)
            try:
                summary = reader.summary()
                present = [document_id for document_id in _evaluation_ids(fixture)
                           if reader.contains_document(document_id)]
                clean = {
                    "copied": True,
                    "originals_required": False,
                    "originals_hidden_during_eval": True,
                    "copy_is_temporary": True,
                    "evaluation_documents_present": present,
                    "evaluation_documents_expected": len(
                        fixture.get("evaluation_documents", ())),
                    "source_files_required": False,
                    "mode": ("corpus directory copied to a temporary model; "
                             "the original directory was moved aside for the "
                             "entire scoring run"),
                }
                report = evaluate(reader, fixture, corpus=summary,
                                  clean_room=clean)
                return report, summary
            finally:
                reader.close()
        finally:
            hidden.rename(root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the sharded corpus even if it exists")
    parser.add_argument("--build-only", action="store_true",
                        help="build or inspect without running the scorecard")
    parser.add_argument("--limit", type=int, default=None,
                        help="bounded build for smoke checks (fails the size gate)")
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--no-near-dedup", action="store_true")
    parser.add_argument("--no-clean-room", action="store_true",
                        help="score the original directory instead of a copy")
    parser.add_argument(
        "--exclude-evaluation-docs", action="store_true",
        help="diagnostic only: exclude the evaluation targets from ingestion")
    args = parser.parse_args()

    fixture = load_fixture(args.fixture)
    corpus = args.corpus.expanduser().resolve()
    if args.rebuild and corpus.exists():
        if (corpus / "model.json").is_file():
            shutil.rmtree(corpus)
    build_summary = None
    if args.rebuild or not (corpus / "model.json").is_file():
        build_summary = _build(
            fixture, corpus, shards=args.shards, limit=args.limit,
            near_dedup=not args.no_near_dedup, replace=True,
            exclude_evaluation=args.exclude_evaluation_docs)
    if args.build_only:
        if build_summary is None:
            reader = CorpusReader(corpus)
            try:
                build_summary = reader.summary()
            finally:
                reader.close()
        print(json.dumps(build_summary, indent=2, sort_keys=True))
        return 0

    report, summary = _score(
        corpus, fixture, clean_room=not args.no_clean_room)
    report["paths"] = {
        "corpus": _display(corpus),
        "fixture": _display(args.fixture),
        "report": _display(args.out),
    }
    report["build"] = {
        "built_in_this_run": build_summary is not None,
        "considered": build_summary.get("considered") if build_summary else None,
        "throughput": summary.get("throughput"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    overall = report["overall"]
    for name, row in report["slices"].items():
        print(f"{name:10s} {row['correct']:2d}/{row['tasks']:2d} "
              f"({row['completion']:.0%}) wrong={row['confident_wrong']} "
              f"invalid_citation={row['invalid_citations']} "
              f"target={row['target_matched']}/{row['tasks']} "
              f"median={row['median_ms']:.1f}ms p95={row['p95_ms']:.1f}ms")
    print(f"Negative controls: {overall['negative_abstained']}/"
          f"{overall['negative_total']} abstained")
    print(f"Corpus: {summary.get('documents', 0):,} documents, "
          f"{summary.get('words', 0):,} words, "
          f"{summary.get('shards', 0)} shards, "
          f"{summary.get('throughput', {}).get('documents_per_second', 0):,} docs/s")
    print(f"Licence coverage: {report['gate']['licence_coverage']:.1%}")
    print(f"Gate: {'PASS' if report['gate_passed'] else 'FAIL'}")
    print(f"Report: {args.out}")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
