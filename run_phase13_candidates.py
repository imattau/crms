#!/usr/bin/env python3
"""Collect the sentences the chat's retrieval offers for each labelled question (Phase 13).

For every question in a labelled set this stores the candidate sentences from
`_top_retrieved_sentence_evidence` (the exact list the evidence gate sees), their retrieval rank and
title, and whether the sentence contains the gold answer. It is the training and evaluation data for
the learned responsiveness scorer, and it also measures the retrieval ceiling: the share of
answerable questions whose gold answer appears in some candidate."""
from __future__ import annotations

import argparse
import json
from multiprocessing import Pool
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

DATA = PROJECT / "data"
INDEX = {"A": DATA / "crms_simplewiki_research.sqlite", "B": DATA / "crms_arxiv_cc0_ccby.sqlite"}
_state: dict = {}


def _init() -> None:
    from crms_research import CRMSSQLiteResearchIndex
    import crms_chat
    _state["fn"] = crms_chat._top_retrieved_sentence_evidence
    _state["idx"] = {c: CRMSSQLiteResearchIndex(str(p)) for c, p in INDEX.items()}


def work(item: dict) -> dict:
    from crms_oracle_eval import matches
    rows = _state["fn"](_state["idx"][item["corpus"]], item["question"])
    out = []
    for rank, row in enumerate(rows):
        text = str(row.get("text", ""))
        out.append({"rank": rank, "text": text, "title": str(row.get("title") or row.get("source_title") or ""),
                    "citation": str(row.get("citation", "")),
                    "pos": bool(item["answerable"] and item["gold"] and matches(item["gold"], text))})
    return {"id": item["id"], "corpus": item["corpus"], "type": item.get("type", ""), "question": item["question"],
            "answerable": item["answerable"], "gold": item["gold"], "cands": out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sets", nargs="+")
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    items = []
    for path in args.sets:
        for it in json.loads(Path(path).read_text()):
            it.setdefault("answerable", True)
            items.append(it)
    with Pool(args.workers, initializer=_init) as pool:
        rows = pool.map(work, items, chunksize=8)
    with open(args.out, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    ans = [r for r in rows if r["answerable"]]
    hit = sum(1 for r in ans if any(c["pos"] for c in r["cands"]))
    print(f"{len(rows)} questions, {len(ans)} answerable; gold in a candidate for {hit} ({hit / max(1, len(ans)):.1%}); "
          f"mean candidates {sum(len(r['cands']) for r in rows) / len(rows):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
