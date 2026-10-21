#!/usr/bin/env python3
"""Phase 11 Stage A evaluation.

1. Phase 10 parity (frozen generation suite).
2. A frozen infobox-oracle sample (`corpus/phase11_eval/oracle_sample.json`, digest
   locked): the relation layer alone, the quote baseline (the unchanged chat
   answering the same questions), and relation-first with baseline fallback, each
   graded correct / wrong / abstain under the reward rule (+1, -3, 0).

Gate thresholds are provisional until the baseline is frozen; open items are listed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_oracle_eval import baseline_chat, compare, sample_questions  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402
from run_phase10_eval import evaluate_fixture  # noqa: E402

REPORT = PROJECT / "experiments" / "reports" / "phase11_stage_a.json"
SAMPLE = PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json"
BASELINE_CACHE = PROJECT / "experiments" / "reports" / "phase11_baseline_answers.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_sample(index: Path, per_relation: int, seed: int, resample: bool) -> list[dict]:
    digest_file = SAMPLE.with_suffix(".sha256")
    if resample or not SAMPLE.is_file():
        items = sample_questions(index, per_relation=per_relation, seed=seed)
        SAMPLE.parent.mkdir(parents=True, exist_ok=True)
        SAMPLE.write_text(json.dumps({"seed": seed, "per_relation": per_relation,
                                      "items": items}, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
        digest_file.write_text(_digest(SAMPLE) + "\n", encoding="utf-8")
        print(f"Froze a new oracle sample: {len(items)} questions (seed {seed})")
    elif digest_file.read_text(encoding="utf-8").strip() != _digest(SAMPLE):
        raise SystemExit("oracle sample does not match its locked digest")
    return json.loads(SAMPLE.read_text(encoding="utf-8"))["items"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=PROJECT / "data" / "crms_simplewiki_research.sqlite")
    parser.add_argument("--per-relation", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20261023)
    parser.add_argument("--resample", action="store_true", help="replace the frozen sample")
    parser.add_argument("--baseline-chat", type=Path, default=PROJECT / "crms_chat.py")
    parser.add_argument("--reuse-baseline", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    summary = evaluate_fixture()["summary"]
    parity = {"cases": summary["cases"], "passed": summary["passed"],
              "mean_copy_ratio": summary.get("mean_copy_ratio")}
    print("Phase 10 parity:", parity)

    comparison = None
    if args.index.is_file():
        items = load_sample(args.index, args.per_relation, args.seed, args.resample)
        with PatternMemory(":memory:") as memory:
            memory.seed()
            engine = RelationEngine(memory.language(), memory.specs(),
                                    IndexSentenceSource(CRMSSQLiteResearchIndex(str(args.index))),
                                    memory.params())
            relation = [(a.answer if (a := engine.ask(it["question"])) else None) for it in items]
        if args.reuse_baseline and BASELINE_CACHE.is_file():
            baseline = json.loads(BASELINE_CACHE.read_text(encoding="utf-8"))["answers"]
        else:
            baseline = baseline_chat(args.baseline_chat, args.index, items, workers=args.workers)
            BASELINE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            BASELINE_CACHE.write_text(json.dumps({"chat": str(args.baseline_chat.name),
                                                  "answers": baseline}, ensure_ascii=False) + "\n",
                                      encoding="utf-8")
        comparison = compare(items, relation, baseline)
        comparison["sample"] = {"questions": len(items), "digest": _digest(SAMPLE)}
        for name, row in comparison["systems"].items():
            print(f"{name:14s}", row)
        print("changes vs baseline:", comparison["changes_vs_baseline"])
    else:
        print(f"Index not found, oracle comparison skipped: {args.index}")

    gate = None
    if comparison:
        base = comparison["systems"]["baseline"]
        comb = comparison["systems"]["combined"]
        gate = {"combined_wrong_rate_not_above_baseline": comb["wrong_rate_of_answered"] <= base["wrong_rate_of_answered"],
                "combined_utility_not_below_baseline": comb["utility"] >= base["utility"],
                "no_correct_answer_lost": comparison["changes_vs_baseline"]["lost"] == 0}
        print("gate checks:", gate)
    report = {"phase": 11, "stage": "A", "status": "open", "phase10_parity": parity,
              "oracle_comparison": comparison, "oracle_gate_checks": gate,
              "open_items": ["registry rule-family integration and packaged-model tables",
                             "clean-room run of the intake path and the oracle runner",
                             "independent hand-authored intake suite",
                             "critic checks for relation and role order",
                             "sentence-boundary regex in the checks module"]}
    if not args.no_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
