#!/usr/bin/env python3
"""Train the extractive reader's feature weights from LLM-authored triples (deterministic).

Training pools hold the supporting sentence plus distractors from the same passage and from other
passages; positives are candidate spans that match the author's answer. Softmax regression with
AdaGrad and L2, in pure Python with a fixed shuffle. Dev evaluation uses the separate training set
(`corpus/phase12_eval/train_set.json`) on its own passages and reports accuracy and the
coverage/wrong trade-off for several confidence thresholds."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

from crms_pattern_defaults import seeded_resources  # noqa: E402
from crms_patterns import sentence_spans, tokenize  # noqa: E402
from crms_span_reader import analyse_question, candidates, features, read, score  # noqa: E402

OLD = Path("/tmp/claude-1000/-home-lostcause--claude-spares-spare-O1Pw5p/3b018ec3-f4d3-4a5c-a2d0-c3a5e8acaf8a/scratchpad/indep")
NEW = Path("/tmp/claude-1000/-home-lostcause-workspace-crms/3b018ec3-f4d3-4a5c-a2d0-c3a5e8acaf8a/scratchpad/p13data")
OUT = PROJECT / "corpus" / "phase13_model" / "reader_weights.json"
language = seeded_resources()[0]


def split_passage(text: str) -> list[str]:
    return [text[a:b].strip() for a, b in sentence_spans(text) if 25 < len(text[a:b].strip()) < 400]


def f1(candidate: str, gold: str) -> float:
    c = [t.low for t in tokenize(candidate, language)]
    g = [t.low for t in tokenize(gold, language)]
    if not c or not g:
        return 0.0
    common = sum(min(c.count(w), g.count(w)) for w in set(c))
    if not common:
        return 0.0
    p, r = common / len(c), common / len(g)
    return 2 * p * r / (p + r)


def build_pool(triple: dict, passages: dict[str, list[str]], titles: list[str], rng: random.Random
               ) -> list[dict]:
    own = passages.get(triple["title"], [])
    others = [s for s in own if s != triple["support"]]
    rng.shuffle(others)
    rows = [{"text": triple["support"], "title": triple["title"]}]
    rows += [{"text": s, "title": triple["title"]} for s in others[:4]]
    for _ in range(2):
        t = rng.choice(titles)
        if t != triple["title"] and passages.get(t):
            rows.append({"text": rng.choice(passages[t]), "title": t})
    rng.shuffle(rows)
    return rows


def examples(triples, passages, titles, seed):
    rng = random.Random(seed)
    data = []
    for tr in triples:
        pool = build_pool(tr, passages, titles, rng)
        q = analyse_question(tr["question"], language)
        cands = []
        for rank, row in enumerate(pool):
            toks = tokenize(row["text"], language)
            for c in candidates(row["text"], toks, language, rank):
                feats = features(q, toks, c, title=row["title"], sentence_rank=rank, language=language)
                positive = (row["text"] == tr["support"] and tr.get("answerable", True)
                            and tr["gold"] and f1(c.text, tr["gold"]) >= 0.8)
                cands.append((feats, positive))
        data.append(cands)
    return data


def train(data, epochs=8, lr=0.3, l2=1e-4, seed=7):
    weights: dict[str, float] = {}
    grad_sq: dict[str, float] = {}
    rng = random.Random(seed)
    usable = [d for d in data if any(p for _f, p in d)]
    print(f"{len(usable)} of {len(data)} examples have a positive candidate")
    for epoch in range(epochs):
        rng.shuffle(usable)
        loss = 0.0
        for cands in usable:
            scores = [score(weights, f) for f, _p in cands]
            peak = max(scores)
            exps = [math.exp(s - peak) for s in scores]
            z = sum(exps)
            pos = sum(e for e, (_f, p) in zip(exps, cands) if p)
            loss -= math.log(max(pos / z, 1e-12))
            grads: dict[str, float] = {}
            for e, (f, p) in zip(exps, cands):
                # d(-log P(positives)) / d score = P(c) - [c positive] * P(c) / P(positives)
                coef = e / z - ((e / pos) if p else 0.0)
                if abs(coef) < 1e-9:
                    continue
                for k, v in f.items():
                    if v:
                        grads[k] = grads.get(k, 0.0) + coef * v
            for k, g in grads.items():
                g += l2 * weights.get(k, 0.0)
                grad_sq[k] = grad_sq.get(k, 0.0) + g * g
                weights[k] = weights.get(k, 0.0) - lr * g / (math.sqrt(grad_sq[k]) + 1e-8)
        print(f"epoch {epoch + 1}: mean loss {loss / len(usable):.3f}")
    return {k: round(v, 4) for k, v in weights.items() if abs(v) > 1e-3}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--l2", type=float, default=1e-4)
    parser.add_argument("--lr", type=float, default=0.3)
    parser.add_argument("--drop", default="", help="comma list of feature prefixes to remove")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    drops = tuple(x for x in args.drop.split(",") if x)
    passages: dict[str, list[str]] = {}
    triples = []
    for k in range(1, 7):
        for p in json.loads((NEW / f"pretrain_{k}.json").read_text()):
            passages[p["title"]] = split_passage(p["text"])
        triples += json.loads((NEW / f"pretrain_{k}_triples.json").read_text())
    titles = sorted(passages)
    print(len(triples), "training triples,", len(titles), "passages")
    data = examples(triples, passages, titles, seed=3)
    if drops:
        data = [[({k: v for k, v in f.items() if not k.startswith(drops)}, p) for f, p in d] for d in data]
    weights = train(data, epochs=args.epochs, lr=args.lr, l2=args.l2)
    Path(args.out).write_text(json.dumps({"trained_on": len(triples), "features": len(weights), "weights": weights},
                              indent=0, sort_keys=True) + "\n")
    print(len(weights), "weights ->", args.out)

    # development evaluation on the separate training set, on its own passages
    dev_passages: dict[str, list[str]] = {}
    for name in ("train_A.json", "train_B.json"):
        for p in json.loads((OLD / name).read_text()):
            dev_passages[p["title"]] = split_passage(p["text"])
    dev = json.loads((PROJECT / "corpus" / "phase12_eval" / "train_set.json").read_text())
    rng = random.Random(11)
    results = []
    for tr in dev:
        pool = build_pool(tr, dev_passages, sorted(dev_passages), rng)
        out = read(tr["question"], pool, weights, language, threshold=0.0)
        hit = out["status"] != "no_candidate" and tr["answerable"] and (
            f1(out["answer"], tr["gold"]) >= 0.5 or tr["gold"].lower() in out["answer"].lower())
        results.append((tr, out, bool(hit)))
    answerable = [r for r in results if r[0]["answerable"]]
    print("dev answerable top-1 accuracy (oracle pool):",
          round(sum(h for _t, _o, h in answerable) / len(answerable), 3), f"of {len(answerable)}")
    for tau in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
        ans = [r for r in results if r[1]["confidence"] >= tau and r[1]["status"] != "no_candidate"]
        good = sum(1 for t, o, h in ans if h)
        wrong = len(ans) - good
        unsafe = sum(1 for t, o, h in ans if not t["answerable"])
        print(f"tau {tau}: answered {len(ans)} correct {good} wrong {wrong} (unanswerable answered {unsafe}) "
              f"wrong share {wrong / max(1, len(ans)):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
