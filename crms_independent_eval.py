"""Independent evaluation tooling (Phase 12, workstream 1).

An author session writes questions from corpus passages and sees nothing of the
system. This module runs the system on that set, turns the answers into rating
sheets for judge sessions, and scores the judges: percent agreement, Cohen's kappa,
and each judge's agreement with the deterministic oracle label. The author, judges
and builder are LLM sessions, so every figure is labelled model-validated.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from crms_oracle_eval import _ABSTAIN, matches

LABELS = ("correct", "wrong", "abstain")


def load_set(path: str | Path) -> list[dict[str, Any]]:
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    for item in items:
        for key in ("id", "corpus", "question", "answerable", "gold", "support"):
            if key not in item:
                raise ValueError(f"{item.get('id', '?')}: missing {key!r}")
    return items


def oracle_label(item: Mapping[str, Any], answer: str | None) -> str:
    """Deterministic label: abstain, correct (gold matched) or wrong.

    An unanswerable question has no gold, so any non-abstaining answer is wrong."""
    if not answer or _ABSTAIN.search(answer):
        return "abstain"
    if not item["answerable"]:
        return "wrong"
    return "correct" if matches(item["gold"], answer) else "wrong"


def summarise(items: Sequence[Mapping[str, Any]], labels: Sequence[str]) -> dict[str, Any]:
    """Correct / wrong / abstain reported separately, overall and per corpus.

    `coverage` counts answerable questions answered; `unsafe` counts answers given to
    unanswerable questions; wrong share is of answered."""
    def one(rows):
        c = collections.Counter(label for _i, label in rows)
        answered = c["correct"] + c["wrong"]
        answerable = [(i, l) for i, l in rows if i["answerable"]]
        unanswerable = [(i, l) for i, l in rows if not i["answerable"]]
        return {"questions": len(rows), **{k: c[k] for k in LABELS},
                "wrong_share_of_answered": round(c["wrong"] / answered, 4) if answered else 0.0,
                "coverage_answerable": round(sum(l == "correct" for _i, l in answerable)
                                             / len(answerable), 4) if answerable else 0.0,
                "unsafe_on_unanswerable": sum(l != "abstain" for _i, l in unanswerable),
                "unanswerable": len(unanswerable),
                "utility": c["correct"] - 3 * c["wrong"]}
    pairs = list(zip(items, labels))
    out = {"overall": one(pairs)}
    for corpus in sorted({i["corpus"] for i in items}):
        out[corpus] = one([(i, l) for i, l in pairs if i["corpus"] == corpus])
    return out


def kappa(a: Sequence[str], b: Sequence[str]) -> dict[str, float]:
    """Percent agreement and Cohen's kappa for two raters' categorical labels."""
    if len(a) != len(b) or not a:
        raise ValueError("raters must label the same non-empty list")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = collections.Counter(a), collections.Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    k = 1.0 if expected == 1 else (observed - expected) / (1 - expected)
    return {"n": n, "agreement": round(observed, 4), "kappa": round(k, 4)}


def rating_sheet(items: Sequence[Mapping[str, Any]], answers: Sequence[str],
                 sources: Sequence[str], indices: Sequence[int]) -> list[dict[str, Any]]:
    """Rows for a judge session: no oracle label, no system internals."""
    rows = []
    for k in indices:
        item = items[k]
        rows.append({"row": k, "question": item["question"],
                     "reference_answer": item["gold"] if item["answerable"] else "(not answerable from the passage)",
                     "reference_support": item["support"],
                     "system_answer": answers[k], "system_cited_source": sources[k]})
    return rows


def judge_report(items: Sequence[Mapping[str, Any]], answers: Sequence[str],
                 judge_a: Mapping[int, str], judge_b: Mapping[int, str]) -> dict[str, Any]:
    rows = sorted(set(judge_a) & set(judge_b))
    a = [judge_a[r] for r in rows]
    b = [judge_b[r] for r in rows]
    oracle = [oracle_label(items[r], answers[r]) for r in rows]
    return {"rated": len(rows), "judge_vs_judge": kappa(a, b),
            "judge_a_vs_oracle": kappa(a, oracle), "judge_b_vs_oracle": kappa(b, oracle),
            "model_validated": True}
