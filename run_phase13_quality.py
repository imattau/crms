#!/usr/bin/env python3
"""Phase 13 workstream A: run the shipped chat on a labelled set and bucket every wrong answer.

Development data only (training set, oracle samples). Writes answers, the gate trace, and the
bucketed wrong answers so selection and answerability errors can be fixed from evidence.
Blind sets are measured separately with --label and never inspected here."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_independent_eval import load_set, oracle_label, summarise  # noqa: E402
from run_phase12_gate import run_all  # noqa: E402


def bucket(item: dict, answer: str, label: str) -> str:
    """Why a wrong (or unsafe) answer was wrong, from the answer text alone."""
    if label != "wrong":
        return label
    if not item["answerable"]:
        return "unanswerable_answered"
    low = answer.lower()
    gold = (item.get("gold") or "").lower().strip()
    if "?" in answer[:200] and ("did you mean" in low or "which one" in low or "clarif" in low):
        return "clarification_prompt"
    if gold and gold.split()[0] in low:
        return "gold_words_present_wrong_span"
    return "unresponsive_sentence"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", default=str(PROJECT / "corpus" / "phase12_eval" / "train_set.json"))
    parser.add_argument("--label", default="train")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--extra", nargs="*", default=[])
    args = parser.parse_args()
    items = load_set(args.set)
    rows = run_all(items, args.extra, args.workers)
    labels = [oracle_label(i, r["answer"], version=2) for i, r in zip(items, rows)]
    buckets = collections.Counter(bucket(i, r["answer"], l) for i, r, l in zip(items, rows, labels))
    types = collections.defaultdict(collections.Counter)
    for i, l in zip(items, labels):
        types[i.get("type", "?")][l] += 1
    summary = summarise(items, labels)
    out = {"label": args.label, "summary": summary["overall"], "buckets": dict(buckets),
           "by_type": {t: dict(c) for t, c in sorted(types.items())},
           "rows": [{"id": i["id"], "type": i.get("type"), "question": i["question"], "gold": i["gold"],
                     "answer": r["answer"], "label": l, "bucket": bucket(i, r["answer"], l),
                     "gate": r["gate"][-1] if r["gate"] else None, "trace": r["gate"]}
                    for i, r, l in zip(items, rows, labels)]}
    Path(PROJECT / "experiments" / "reports").mkdir(exist_ok=True)
    (PROJECT / "experiments" / "reports" / f"phase13_quality_{args.label}.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: out[k] for k in ("label", "summary", "buckets")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
