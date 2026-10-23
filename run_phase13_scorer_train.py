#!/usr/bin/env python3
"""Train and evaluate the learned responsiveness scorer on recorded retrieval candidates.

Training data: `run_phase13_candidates.py` output (question, retrieved sentences, which contain the
gold answer). Pointwise logistic regression with AdaGrad and L2; fixed seed. Evaluation replays the
chat's decision on held-out questions: take the best sentence by probability, answer if the probability
reaches the threshold, and compare with what the current hand-written gate does with the same
sentences."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT))

import crms_nl_gate as gate  # noqa: E402
from crms_responsiveness import content_stems, features, probability, set_association  # noqa: E402

OUT = PROJECT / "corpus" / "phase13_model" / "responsiveness_weights.json"


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def deviations(question: str, sentence: str, title: str) -> list[str]:
    kind = gate._answer_type(question)
    try:
        found, _score = gate._deviations(question, sentence, [], kind, title)
    except Exception:
        return []
    return sorted({d.dimension for d in found})


def build_association(rows: list[dict], min_count: int = 8) -> dict[str, dict[str, float]]:
    """Lift of (question stem, sentence stem) pairs over the base rate of a sentence being a positive."""
    pos_pairs: dict[tuple[str, str], int] = {}
    all_pairs: dict[tuple[str, str], int] = {}
    positives = total = 0
    for r in rows:
        q = set(content_stems(r["question"]))
        for c in r["cands"]:
            sx = set(content_stems(c["text"]))
            total += 1
            positives += 1 if c["pos"] else 0
            for a in q:
                for b in sx:
                    if a == b:
                        continue
                    all_pairs[(a, b)] = all_pairs.get((a, b), 0) + 1
                    if c["pos"]:
                        pos_pairs[(a, b)] = pos_pairs.get((a, b), 0) + 1
    base = positives / max(1, total)
    table: dict[str, dict[str, float]] = {}
    for (a, b), n in all_pairs.items():
        if n < min_count:
            continue
        rate = (pos_pairs.get((a, b), 0) + 1.0 * base * 5) / (n + 5)
        lift = math.log(rate / base)
        if abs(lift) >= 0.7:
            table.setdefault(a, {})[b] = round(max(-2.0, min(3.0, lift)), 2)
    return table


def featurise(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["feats"] = [features(r["question"], c["text"], c["title"], c["rank"],
                               deviations(r["question"], c["text"], c["title"]),
                               small_index=(r["corpus"] == "B")) for c in r["cands"]]
    return rows


def train(rows: list[dict], epochs: int, lr: float, l2: float, seed: int = 5) -> dict[str, float]:
    rng = random.Random(seed)
    examples = []
    for r in rows:
        for f, c in zip(r["feats"], r["cands"]):
            examples.append((f, 1.0 if c["pos"] else 0.0))
    # mismatched questions teach "no good sentence": a question paired with another question's candidates
    for r in rows:
        if rng.random() < 0.3:
            other = rng.choice(rows)
            if other["id"] != r["id"] and other["cands"]:
                for c in other["cands"][:6]:
                    examples.append((features(r["question"], c["text"], c["title"], c["rank"],
                                              deviations(r["question"], c["text"], c["title"]),
                                              small_index=(r["corpus"] == "B")), 0.0))
    weights: dict[str, float] = {}
    sq: dict[str, float] = {}
    pos_rate = sum(y for _f, y in examples) / len(examples)
    print(f"{len(examples)} examples, {pos_rate:.1%} positive")
    for epoch in range(epochs):
        rng.shuffle(examples)
        loss = 0.0
        for f, y in examples:
            p = probability(weights, f)
            loss -= math.log(max(p if y else 1 - p, 1e-9))
            err = p - y
            for k, v in f.items():
                if v:
                    g = err * v + l2 * weights.get(k, 0.0)
                    sq[k] = sq.get(k, 0.0) + g * g
                    weights[k] = weights.get(k, 0.0) - lr * g / (math.sqrt(sq[k]) + 1e-8)
        print(f"epoch {epoch + 1}: loss {loss / len(examples):.4f}")
    return {k: round(v, 4) for k, v in weights.items() if abs(v) > 1e-4}


def evaluate(rows: list[dict], weights: dict[str, float]) -> None:
    results = []
    for r in rows:
        if not r["cands"]:
            results.append((0.0, False, r))
            continue
        probs = [probability(weights, f) for f in r["feats"]]
        k = max(range(len(probs)), key=lambda i: (probs[i], -i))
        results.append((probs[k], bool(r["cands"][k]["pos"]), r))
    answerable = [x for x in results if x[2]["answerable"]]
    ceiling = sum(1 for x in answerable if any(c["pos"] for c in x[2]["cands"]))
    print(f"dev: {len(rows)} questions ({len(answerable)} answerable); retrieval ceiling {ceiling} "
          f"({ceiling / max(1, len(answerable)):.1%}); top-1 contains gold: "
          f"{sum(1 for p, ok, r in answerable if ok)}")
    print("learned scorer:")
    for tau in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        acc = [(ok, r) for p, ok, r in results if p >= tau and r["cands"]]
        good = sum(1 for ok, r in acc if ok)
        wrong = len(acc) - good
        unsafe = sum(1 for ok, r in acc if not r["answerable"])
        print(f"  tau {tau}: answered {len(acc):4d} correct {good:4d} wrong {wrong:4d} "
              f"wrong share {wrong / max(1, len(acc)):.2f}  unanswerable answered {unsafe}")
    # the current gate on the same candidates
    good = wrong = 0
    for r in rows:
        decision = gate.gate_quoted_evidence(r["question"], [{"text": c["text"], "title": c["title"],
                                                              "citation": c["citation"]} for c in r["cands"]])
        if decision["status"] != "accepted":
            continue
        text = str(decision["evidence"].get("text", ""))
        hit = any(c["text"] == text and c["pos"] for c in r["cands"])
        good += hit
        wrong += (not hit)
    print(f"current hand-written gate on the same candidates: answered {good + wrong} correct {good} "
          f"wrong {wrong} wrong share {wrong / max(1, good + wrong):.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", nargs="+")
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--lr", type=float, default=0.2)
    parser.add_argument("--l2", type=float, default=1e-4)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    rows = [r for path in args.candidates for r in load(path)]
    dev_ids = lambda r: r["id"].startswith("N4-") or (r["id"][:1] == "T" and int(r["id"][2:]) % 2 == 0)
    train_rows = [r for r in rows if not dev_ids(r)]
    # cross-fitting: a training question's association features come from the other folds, so the
    # feature never sees its own label; dev and inference use the table built from all training rows
    folds = 4
    tr = []
    for k in range(folds):
        set_association(build_association([r for i, r in enumerate(train_rows) if i % folds != k]))
        tr += featurise([r for i, r in enumerate(train_rows) if i % folds == k])
    association = build_association(train_rows)
    set_association(association)
    print(sum(len(v) for v in association.values()), "association pairs")
    dev = featurise([r for r in rows if dev_ids(r)])
    print(len(tr), "training questions,", len(dev), "dev questions")
    weights = train(tr, args.epochs, args.lr, args.l2)
    evaluate(dev, weights)
    if not args.no_save:
        Path(args.out).write_text(json.dumps({"trained_on": len(tr), "weights": weights}, indent=0, sort_keys=True) + "\n")
        Path(args.out).with_name("responsiveness_assoc.json").write_text(
            json.dumps(association, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
