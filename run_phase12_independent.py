#!/usr/bin/env python3
"""Phase 12: run the system on the independently authored set (never used for tuning).

Corpus A is answered from the Simple English Wikipedia index, corpus B from the arXiv
index. Each question gets the relation layer first and the unchanged chat as fallback
(the Phase 11 combined system), and the chat alone. Output: answers with their cited
source, deterministic labels, and per-corpus summaries."""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_independent_eval import load_set, oracle_label, summarise  # noqa: E402
from crms_oracle_eval import chat_answer  # noqa: E402
from crms_pattern_memory import PatternMemory  # noqa: E402
from crms_pattern_sources import IndexSentenceSource  # noqa: E402
from crms_relation_specs import RelationEngine  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402

SET = PROJECT / "corpus" / "phase12_eval" / "independent_set.json"
INDEX = {"A": PROJECT / "data" / "crms_simplewiki_research.sqlite",
         "B": PROJECT / "data" / "crms_arxiv_cc0_ccby.sqlite"}
OUT = PROJECT / "experiments" / "reports" / "phase12_independent_answers.json"
REPORT = PROJECT / "experiments" / "reports" / "phase12_independent.json"


def split_source(text: str) -> tuple[str, str]:
    import re
    sources = re.findall(r"\[Source:([^\]]*)\]", text)
    cleaned = re.sub(r"\[Source:[^\]]*\]", "", text)
    cleaned = re.sub(r"\s*you>\s*$", "", cleaned.strip())     # the chat prompt echoed after the answer
    return cleaned.strip(), "; ".join(s.strip() for s in sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--memory", help="pattern memory holding the learned specs (default: the seed)")
    parser.add_argument("--rerun-relation", action="store_true",
                        help="keep the stored chat answers and recompute the relation layer only")
    parser.add_argument("--tag", default="", help="suffix for the output files")
    args = parser.parse_args()
    lock = SET.with_suffix(".sha256").read_text().strip()
    if hashlib.sha256(SET.read_bytes()).hexdigest() != lock:
        raise SystemExit("independent set does not match its digest")
    items = load_set(SET)
    out = OUT.with_name(OUT.stem + args.tag + OUT.suffix)
    report_path = REPORT.with_name(REPORT.stem + args.tag + REPORT.suffix)
    if args.rerun_relation and OUT.is_file():
        stored = json.loads(OUT.read_text())["rows"]
        rows = []
        for corpus in ("A", "B"):
            with PatternMemory(args.memory or ":memory:") as memory:
                if not args.memory:
                    memory.seed()
                engine = RelationEngine(memory.language(), memory.specs(),
                                        IndexSentenceSource(CRMSSQLiteResearchIndex(str(INDEX[corpus]))),
                                        memory.params())
                for k, (item, old) in enumerate(zip(items, stored)):
                    if item["corpus"] != corpus:
                        continue
                    a = engine.ask(item["question"])
                    r_ans, r_src = (a.answer, a.title) if a else (None, "")
                    combined, combined_src = (r_ans, r_src) if r_ans else (old["chat"], old["chat_source"])
                    rows.append((k, {"id": item["id"], "chat": old["chat"], "chat_source": old["chat_source"],
                                     "relation": r_ans, "combined": combined, "combined_source": combined_src}))
        rows = [r for _k, r in sorted(rows, key=lambda x: x[0])]
    elif args.reuse and OUT.is_file():
        rows = json.loads(OUT.read_text())["rows"]
    else:
        def chat(item):
            raw = chat_answer(PROJECT / "crms_chat.py", INDEX[item["corpus"]], item["question"],
                              keep_source=True)
            return split_source(raw)
        with ThreadPoolExecutor(args.workers) as pool:
            chats = list(pool.map(chat, items))
        relation = []
        for corpus in ("A", "B"):
            with PatternMemory(":memory:") as memory:
                memory.seed()
                engine = RelationEngine(memory.language(), memory.specs(),
                                        IndexSentenceSource(CRMSSQLiteResearchIndex(str(INDEX[corpus]))),
                                        memory.params())
                for k, item in enumerate(items):
                    if item["corpus"] == corpus:
                        a = engine.ask(item["question"])
                        relation.append((k, (a.answer, a.title) if a else (None, "")))
        relation = [r for _k, r in sorted(relation)]
        rows = []
        for item, (c_ans, c_src), (r_ans, r_src) in zip(items, chats, relation):
            combined, combined_src = (r_ans, r_src) if r_ans else (c_ans, c_src)
            rows.append({"id": item["id"], "chat": c_ans, "chat_source": c_src,
                         "relation": r_ans, "combined": combined, "combined_source": combined_src})
        out.write_text(json.dumps({"set_digest": lock, "rows": rows}, ensure_ascii=False, indent=1) + "\n")
    report = {"phase": 12, "set_digest": lock, "model_validated": True}
    for system in ("chat", "relation", "combined"):
        labels = [oracle_label(i, r[system]) for i, r in zip(items, rows)]
        report[system] = summarise(items, labels)
        o = report[system]["overall"]
        print(f"{system:9s}", {k: o[k] for k in ("correct", "wrong", "abstain", "wrong_share_of_answered",
                                              "coverage_answerable", "unsafe_on_unanswerable", "utility")})
    report_path.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
