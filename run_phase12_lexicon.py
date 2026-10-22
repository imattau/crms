#!/usr/bin/env python3
"""Add induced verbs to a pattern memory only if the oracle bank does not get worse.

Candidates come from the corpus (crms_lexicon_growth). The full frozen Phase 11
oracle sample is answered before and after; the verbs are kept only when wrong
answers do not rise and utility does not fall."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_lexicon_growth import grow  # noqa: E402
from crms_oracle_eval import grade  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

INDEX_A = PROJECT / "data" / "crms_simplewiki_research.sqlite"
INDEX_B = PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"
ORACLE = PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json"


def bank(memory: PatternMemory, items: list[dict]) -> dict:
    engine = RelationEngine(memory.language(), memory.specs(),
                            IndexSentenceSource(CRMSSQLiteResearchIndex(str(INDEX_A))), memory.params())
    counts = {"correct": 0, "wrong": 0, "abstain": 0}
    for item in items:
        answer = engine.ask(item["question"])
        counts[grade(item, answer.answer) if answer else "abstain"] += 1
    counts["utility"] = counts["correct"] - 3 * counts["wrong"]
    return counts


def texts(path: Path, limit: int):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for (body,) in connection.execute(
            "SELECT substr(body,1,4000) FROM source_documents "
            "ORDER BY (rowid*2654435761+5)%4294967296 LIMIT ?", (limit,)):
        yield body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", default="/tmp/phase12_loop_memory.sqlite")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--min-passive", type=int, default=8)
    parser.add_argument("--group", type=int, default=16)
    parser.add_argument("--out", default="/tmp/phase12_loop/lexicon.json")
    args = parser.parse_args()
    items = json.loads(ORACLE.read_text())["items"]
    memory = PatternMemory(args.memory)
    before = bank(memory, items)
    found = grow(texts(INDEX_A, 25000), memory.language().verbs, limit=args.limit, min_passive=args.min_passive)
    memory.log_change("data", f"induce verbs from the corpus ({len(found)} candidates)", reference="lexicon-growth")
    kept, dropped, current = [], [], before
    for start in range(0, len(found), args.group):
        group = found[start:start + args.group]
        for c in group:
            memory.put_verb(c["lemma"], c["forms"])
        memory.connection.commit()
        after = bank(memory, items)
        if after["wrong"] <= current["wrong"] and after["utility"] >= current["utility"]:
            kept += group
            current = after
        else:                       # this group made the bank worse: take it back out
            for c in group:
                memory.connection.execute("DELETE FROM pat_verb WHERE lemma=?", (c["lemma"],))
            memory.connection.commit()
            dropped += group
        print("group", start // args.group, "kept" if group[0] in kept else "dropped", current, flush=True)
    after, keep = current, bool(kept)
    found = kept
    report = {"candidates": len(found), "kept": keep, "before": before, "after": after,
              "verbs": [c["lemma"] for c in found]}
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("candidates", "kept", "before", "after")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
