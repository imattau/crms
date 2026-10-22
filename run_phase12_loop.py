#!/usr/bin/env python3
"""Phase 12 teacher loop driver.

    run_phase12_loop.py measure  --round N       measure train/dev, write the teacher brief
    run_phase12_loop.py apply P.json --round N   verify proposals, accept, remeasure dev, keep or roll back

State lives in a pattern-memory file (--memory). The independent set is never read here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_independent_eval import load_set  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_patterns import sentence_spans  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402
from crms_teacher_loop import (CorpusEngines, apply_proposals, failures, measure,  # noqa: E402
                               round_decision, split, write_brief)

DATA = PROJECT / "data"
INDEX = {"A": DATA / "crms_simplewiki_research.sqlite", "B": DATA / "crms_arxiv_cc0_ccby.sqlite"}
ORACLE = PROJECT / "corpus" / "phase11_eval" / "oracle_sample.json"


def setup(args):
    memory = PatternMemory(args.memory)
    if not memory.specs():
        memory.seed()
    sources = {c: IndexSentenceSource(CRMSSQLiteResearchIndex(str(p))) for c, p in INDEX.items()}
    items = load_set(args.set)
    train, dev = split(items)
    return memory, CorpusEngines(memory, sources), train, dev


def controls_for(train):
    oracle = json.loads(ORACLE.read_text())["items"]      # the full frozen sample guards relation questions
    extra = [{"id": f"O{i:03d}", "corpus": "A", "question": o["question"], "answerable": True,
              "gold": o["gold"], "support": ""} for i, o in enumerate(oracle)]
    return list(train) + extra


def corpus_sentences():
    import sqlite3
    c = sqlite3.connect(f"file:{INDEX['A']}?mode=ro", uri=True)
    out = []
    for (body,) in c.execute("SELECT substr(body,1,1500) FROM source_documents "
                             "ORDER BY (rowid*2654435761+3)%4294967296 LIMIT 120"):
        out += [body[a:b].strip() for a, b in sentence_spans(body)][:4]
    return [s for s in out if 25 < len(s) < 300]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["measure", "apply"])
    parser.add_argument("proposals", nargs="?")
    parser.add_argument("--set", default=str(PROJECT / "corpus" / "phase12_eval" / "train_set.json"))
    parser.add_argument("--memory", default="/tmp/phase12_loop_memory.sqlite")
    parser.add_argument("--round", type=int, default=1)
    parser.add_argument("--work", default="/tmp/phase12_loop")
    parser.add_argument("--precision", action="store_true",
                        help="replace the random-sentence fire-rate check by measured train precision")
    args = parser.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    memory, engines, train, dev = setup(args)

    if args.command == "measure":
        t, d = measure(engines, train), measure(engines, dev)
        previous_file = work / f"round_{args.round - 1}.json"
        previous = (json.loads(previous_file.read_text())["rejected"] if previous_file.is_file() else [])
        brief = write_brief(work / f"brief_{args.round}.json", failures(train, t["rows"]), engines,
                            round_no=args.round, previous=previous)
        (work / f"dev_before_{args.round}.json").write_text(json.dumps(d["summary"]))
        print("train", {k: t["summary"]["overall"][k] for k in ("correct", "wrong", "abstain", "utility")})
        print("dev  ", {k: d["summary"]["overall"][k] for k in ("correct", "wrong", "abstain", "utility")})
        print("brief types:", brief["counts_by_type"])
        return 0

    proposals = json.loads(Path(args.proposals).read_text())
    before = json.loads((work / f"dev_before_{args.round}.json").read_text())
    verdicts = apply_proposals(proposals, engines, controls_for(train), corpus_sentences(),
                               round_no=args.round,
                               precision_items=train if args.precision else ())
    after = measure(engines, dev)["summary"]
    decision = round_decision(before, after)
    accepted = [v["name"] for v in verdicts if v["accepted"]]
    if not decision["keep"]:
        for name in accepted:
            memory.set_spec_status(name, "retired", "round rolled back: dev wrong share rose or utility fell")
        memory.connection.commit()
        engines.refresh()
    report = {"round": args.round, "proposed": len(proposals), "accepted": accepted,
              "rejected": [{"name": v["name"], "reasons": v["reasons"]} for v in verdicts if not v["accepted"]],
              "decision": decision}
    (work / f"round_{args.round}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False)[:3500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
