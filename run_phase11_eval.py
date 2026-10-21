#!/usr/bin/env python3
"""Phase 11 Stage A evaluation: Phase 10 parity plus an infobox-oracle intake sample.

The gate thresholds are provisional until a baseline is frozen; this run records
the numbers and marks every open item.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_oracle_eval import evaluate, sample_questions  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402
from run_phase10_eval import evaluate_fixture  # noqa: E402

REPORT = PROJECT / "experiments" / "reports" / "phase11_stage_a.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=PROJECT / "data" / "crms_simplewiki_research.sqlite")
    parser.add_argument("--per-relation", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()

    phase10 = evaluate_fixture()
    summary = phase10["summary"]
    parity = {"cases": summary["cases"], "passed": summary["passed"],
              "mean_copy_ratio": summary.get("mean_copy_ratio")}
    print("Phase 10 parity:", parity)

    oracle = None
    if args.index.is_file():
        with PatternMemory(":memory:") as memory:
            memory.seed()
            index = CRMSSQLiteResearchIndex(str(args.index))
            engine = RelationEngine(memory.language(), memory.specs(),
                                    IndexSentenceSource(index), memory.params())
            items = sample_questions(args.index, per_relation=args.per_relation, seed=args.seed)
            oracle = evaluate(engine, items)
            oracle["seed"] = args.seed
        print({k: v for k, v in oracle.items() if k not in ("wrong_examples", "per_relation")})
    else:
        print(f"Index not found, oracle sample skipped: {args.index}")

    report = {
        "phase": 11, "stage": "A", "status": "open",
        "phase10_parity": parity, "oracle_sample": oracle,
        "open_items": ["quote-baseline comparison on the same sample", "pattern-based clarity and critic rules",
                       "registry family and packaged-model tables", "full experiment suite diff recorded",
                       "independent hand-authored intake suite", "clean-room copy run"],
    }
    if not args.no_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
