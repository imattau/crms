#!/usr/bin/env python3
"""Phase 12 oracle evaluation on a fresh frozen sample (seed 20261101).

The Phase 11 sample was used to find failure causes and tune, so it is retired as a
blind set. This sample excludes every Phase 11 question. It compares the relation
layer with and without page-subject resolution, and (with --baseline) the quote
baseline and the combined system, under the reward rule (+1, -3, 0)."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_oracle_eval import baseline_chat, compare, grade, sample_questions  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

SAMPLE = PROJECT / "corpus" / "phase12_eval" / "oracle_sample_b.json"
RETIRED = PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json"
CACHE = PROJECT / "experiments" / "reports" / "phase12_baseline_answers.json"
REPORT = PROJECT / "experiments" / "reports" / "phase12_oracle.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(index: Path, seed: int, per_relation: int) -> list[dict]:
    lock = SAMPLE.with_suffix(".sha256")
    if not SAMPLE.is_file():
        retired = {i["question"] for i in json.loads(RETIRED.read_text())["items"]}
        items = sample_questions(index, per_relation=per_relation, seed=seed, exclude=retired)
        SAMPLE.write_text(json.dumps({"seed": seed, "per_relation": per_relation,
                                      "excludes": "phase11 oracle_sample.json",
                                      "items": items}, ensure_ascii=False, indent=1) + "\n")
        lock.write_text(digest(SAMPLE) + "\n")
        print(f"Froze {len(items)} questions (seed {seed})")
    elif lock.read_text().strip() != digest(SAMPLE):
        raise SystemExit("sample does not match its locked digest")
    return json.loads(SAMPLE.read_text())["items"]


def run_relation(index: Path, items: list[dict], subject_window: int) -> list:
    with PatternMemory(":memory:") as memory:
        memory.seed()
        source = IndexSentenceSource(CRMSSQLiteResearchIndex(str(index)),
                                     subject_window=subject_window)
        engine = RelationEngine(memory.language(), memory.specs(), source, memory.params())
        return [(a.answer if (a := engine.ask(it["question"])) else None) for it in items]


def summarise(items: list[dict], answers: list) -> dict:
    counts = {"correct": 0, "wrong": 0, "abstain": 0}
    for item, answer in zip(items, answers):
        counts[grade(item, answer) if answer else "abstain"] += 1
    answered = counts["correct"] + counts["wrong"]
    return {**counts, "wrong_rate_of_answered": round(counts["wrong"] / answered, 4) if answered else 0.0,
            "utility": counts["correct"] - 3 * counts["wrong"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=PROJECT / "data" / "crms_simplewiki_research.sqlite")
    parser.add_argument("--seed", type=int, default=20261101)
    parser.add_argument("--per-relation", type=int, default=150)
    parser.add_argument("--baseline", action="store_true", help="also run the quote baseline (slow)")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    items = load(args.index, args.seed, args.per_relation)
    before = run_relation(args.index, items, 0)
    after = run_relation(args.index, items, 6)
    report = {"phase": 12, "sample": {"questions": len(items), "digest": digest(SAMPLE)},
              "relation_without_subject_resolution": summarise(items, before),
              "relation_with_subject_resolution": summarise(items, after)}
    print("without:", report["relation_without_subject_resolution"])
    print("with:   ", report["relation_with_subject_resolution"])
    if args.baseline:
        if CACHE.is_file():
            base = json.loads(CACHE.read_text())["answers"]
        else:
            base = baseline_chat(PROJECT / "crms_chat.py", args.index, items, workers=args.workers)
            CACHE.write_text(json.dumps({"answers": base}, ensure_ascii=False) + "\n")
        report["oracle_comparison"] = compare(items, after, base)
        for name, row in report["oracle_comparison"]["systems"].items():
            print(f"{name:14s}", row)
        print("changes vs baseline:", report["oracle_comparison"]["changes_vs_baseline"])
    if not args.no_report:
        REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
