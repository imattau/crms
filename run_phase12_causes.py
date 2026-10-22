#!/usr/bin/env python3
"""Phase 12: group the relation engine's failures on the frozen oracle sample by cause."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_failure_causes import group  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

SAMPLE = PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json"
REPORT = PROJECT / "experiments" / "reports" / "phase12_failure_causes.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=PROJECT / "data" / "crms_simplewiki_research.sqlite")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    items = json.loads(SAMPLE.read_text(encoding="utf-8"))["items"]
    with PatternMemory(":memory:") as memory:
        memory.seed()
        engine = RelationEngine(memory.language(), memory.specs(),
                                IndexSentenceSource(CRMSSQLiteResearchIndex(str(args.index))),
                                memory.params())
        report = group(engine, items)
    print(json.dumps({k: report[k] for k in ("questions", "causes", "pattern_addressable",
                                             "retrieval_problems")}, indent=1))
    for relation, row in report["per_relation"].items():
        print(f"{relation:12s}", row)
    if not args.no_report:
        REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("Report:", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
