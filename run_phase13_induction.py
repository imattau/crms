#!/usr/bin/env python3
"""Phase 13 B: induce relation specs from the LLM-authored triples and run them through the verifier.

Triples (corpus/phase13_model/triples/ or the scratch shards) are aligned and generalised by
`crms_spec_induction`; every candidate then faces the same gate as a teacher's proposal: replay,
held-out, contrast, verb-swap, bank non-regression on the full oracle sample plus the training
questions, and measured precision on the labelled triples. Accepted specs enter a pattern memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_spec_induction import propose  # noqa: E402
from crms_teacher_loop import apply_proposals, measure, split  # noqa: E402
import run_phase12_loop as L  # noqa: E402

NEW = Path("/tmp/claude-1000/-home-lostcause-workspace-crms/3b018ec3-f4d3-4a5c-a2d0-c3a5e8acaf8a/scratchpad/p13data")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", default="/tmp/phase13_induction_memory.sqlite")
    parser.add_argument("--min-group", type=int, default=4)
    parser.add_argument("--max-specs", type=int, default=40)
    parser.add_argument("--out", default="/tmp/phase13_induction_report.json")
    args = parser.parse_args()

    class A:                       # reuse the loop's setup
        memory = args.memory
        set = str(PROJECT / "corpus" / "phase12_eval" / "train_set.json")
    memory, engines, train, dev = L.setup(A)
    triples = []
    for k in range(1, 7):
        triples += json.loads((NEW / f"pretrain_{k}_triples.json").read_text())
    language = memory.language()
    candidates = propose(triples, language, min_group=args.min_group, max_specs=args.max_specs)
    print(len(candidates), "candidates from", len(triples), "triples")
    before = measure(engines, dev)["summary"]
    precision_items = [{"id": t["id"], "corpus": t["corpus"], "question": t["question"], "answerable": True,
                        "gold": t["gold"], "support": t["support"], "title": t["title"]} for t in triples]
    verdicts = apply_proposals(candidates, engines, L.controls_for(train), L.corpus_sentences(),
                               round_no=900, precision_items=precision_items, pool_precision=True)
    after = measure(engines, dev)["summary"]
    accepted = [v["name"] for v in verdicts if v["accepted"]]
    report = {"candidates": len(candidates), "accepted": accepted,
              "rejected": [{"name": v["name"], "reasons": v["reasons"]} for v in verdicts if not v["accepted"]],
              "dev_before": before["overall"], "dev_after": after["overall"]}
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("candidates", "accepted", "dev_before", "dev_after")}, indent=1))
    for r in report["rejected"][:10]:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
