"""Learned responsiveness of a retrieved sentence to a question (Phase 13).

The hand-written gate thresholds can say "this sentence is about something else", but they were
tuned on a few hundred questions. This module keeps the gate's named deviations as features and
adds others (rarity-weighted term coverage, term density near the entity, answer-type fit, rank,
title), then learns the weights from thousands of LLM-authored question/answer examples scored
against the sentences the chat's own retrieval returns. The score is a logistic regression over
named features, so every decision comes with the features and weights that produced it; the weights
are plain table rows (`corpus/phase13_model/responsiveness_weights.json`, later a pattern table).

The chat asks `decide`: the best sentence is answered only when its probability of containing the
answer is high enough and the invariant checks (fragment, entity) agree; otherwise it abstains with
`low_responsiveness` and the strongest negative features as the typed reason.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from crms_intent_rules import words
from crms_word_rarity import weight as word_weight

_STOP = frozenset("""a an the of in on at by for to with from as is are was were be been being do does did
has have had and or that this these those it its their his her which who whom whose what when where why
how many much can could would should will shall may might must not no""".split())
_WH = ("what", "who", "whom", "whose", "when", "where", "which", "why", "how")
_CAUSE = frozenset({"because", "due", "since", "so", "order", "reason", "caused", "result"})
_LIST = frozenset({"including", "such", "include", "includes", "like", "namely"})


def _loose(word: str) -> str:
    w = word.casefold()
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            w = w[:-len(suffix)]
            break
    return w.rstrip("e")


def _bucket(n: float, edges: Sequence[float]) -> str:
    for e in edges:
        if n <= e:
            return f"<={e:g}"
    return f">{edges[-1]:g}"


# learned word associations: ASSOC[question stem][sentence stem] = lift (log odds that a sentence holding
# the second word answers a question holding the first, beyond the base rate). Set by `set_association`.
ASSOC: dict[str, dict[str, float]] = {}


# whether the corpus being searched is small (a personal collection, a short paper index): with few
# documents a sentence that shares the question's terms is more likely the answer
SMALL_INDEX = {"small": False}
SMALL_INDEX_DOCUMENTS = 5000


def set_index_small(small: bool) -> None:
    SMALL_INDEX["small"] = bool(small)


def set_association(table: Mapping[str, Mapping[str, float]] | None) -> None:
    ASSOC.clear()
    for q, row in (table or {}).items():
        ASSOC[q] = dict(row)


def content_stems(text: str) -> list[str]:
    return [_loose(w) for w in words(text) if w not in _STOP and not w.isdigit()]


def question_terms(question: str) -> tuple[str, list[str], list[str]]:
    """(wh word, content terms, capitalised entity words) of a question."""
    toks = question.replace("’", "'").split()
    low = words(question)
    wh = next((w for w in low if w in _WH), "other")
    terms = [w for w in low if w not in _STOP and not w.isdigit()]
    entity = [t.strip("?,.!;:\"'()").casefold() for t in toks[1:] if t[:1].isupper()]
    return wh, terms, [e for e in entity if e]


def features(question: str, sentence: str, title: str, rank: int, deviations: Sequence[str] = (),
             small_index: bool | None = None) -> dict[str, float]:
    """Named features of one (question, sentence) pair."""
    wh, terms, entity = question_terms(question)
    tokens = words(sentence)
    sentence_set = {_loose(t) for t in tokens}
    title_set = {_loose(t) for t in words(title)}
    small = SMALL_INDEX["small"] if small_index is None else small_index
    f: dict[str, float] = {"bias": 1.0}
    f[f"rank:{_bucket(rank, (0, 2, 5, 9))}"] = 1.0

    total = sum(word_weight(t) for t in terms) or 1.0
    present = [t for t in terms if _loose(t) in sentence_set]
    in_title = [t for t in terms if _loose(t) in title_set and _loose(t) not in sentence_set]
    f["cover_weighted"] = sum(word_weight(t) for t in present) / total
    if small:
        f["small_index"] = 1.0
        f["small_index|cover"] = f["cover_weighted"]
        f["small_index|rank0"] = 1.0 if rank == 0 else 0.0
    rare = [t for t in terms if word_weight(t) >= 6.0]
    rare_missing = [t for t in rare if _loose(t) not in sentence_set and _loose(t) not in title_set]
    f["rare_missing"] = float(len(rare_missing))
    f["rare_missing_any"] = 1.0 if rare_missing else 0.0
    f["rare_present_share"] = (sum(1 for t in rare if _loose(t) in sentence_set) / len(rare)) if rare else 1.0
    f["term_in_title_only"] = sum(word_weight(t) for t in in_title) / total
    f[f"n_terms:{_bucket(len(terms), (2, 4, 6))}"] = 1.0

    if ASSOC:
        # question words the sentence lacks but that it paraphrases (founded ~ established)
        sentence_stems = {_loose(t) for t in tokens if t not in _STOP}
        missing = [t for t in terms if _loose(t) not in sentence_stems]
        gains = []
        for t in missing:
            row = ASSOC.get(_loose(t))
            if row:
                best_lift = max((row.get(sx, 0.0) for sx in sentence_stems), default=0.0)
                gains.append((word_weight(t), best_lift))
        f["assoc_sum"] = (sum(w * g for w, g in gains if g > 0) / total) if gains else 0.0
        f["assoc_neg"] = (sum(w * -g for w, g in gains if g < 0) / total) if gains else 0.0

    # density: best window of 14 tokens
    weights_by_pos = [word_weight(t) if _loose(t) in {_loose(x) for x in terms} else 0.0 for t in tokens]
    best = 0.0
    for i in range(0, max(1, len(tokens) - 13)):
        best = max(best, sum(weights_by_pos[i:i + 14]))
    f["density"] = best / total

    # entity
    if entity:
        ent_in = [e for e in entity if _loose(e) in sentence_set]
        ent_title = [e for e in entity if _loose(e) in title_set]
        f["entity_all_in_sentence"] = 1.0 if len(ent_in) == len(entity) else 0.0
        f["entity_share_in_sentence"] = len(ent_in) / len(entity)
        f["entity_in_title"] = 1.0 if len(ent_title) == len(entity) else 0.0
    else:
        f["no_entity"] = 1.0

    # answer-type fit
    has_year = any(t.isdigit() and len(t) == 4 and t[:2] in ("10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20")
                   for t in tokens)
    has_num = any(t.isdigit() for t in tokens) or any(t in ("one", "two", "three", "four", "five", "six", "seven",
                                                          "eight", "nine", "ten", "hundred", "thousand", "million") for t in tokens)
    qset = {_loose(t) for t in terms}
    extra_caps = [w for w in sentence.replace("’", "'").split()[1:]
                  if w[:1].isupper() and _loose(w.strip("?,.!;:\"'()")) not in qset]
    f[f"{wh}|year"] = 1.0 if has_year else 0.0
    f[f"{wh}|number"] = 1.0 if has_num else 0.0
    f[f"{wh}|extra_caps:{_bucket(len(extra_caps), (0, 1, 3))}"] = 1.0
    f[f"{wh}|cause_cue"] = 1.0 if _CAUSE & set(tokens) else 0.0
    f[f"{wh}|list_cue"] = 1.0 if (_LIST & set(tokens) or ":" in sentence) else 0.0
    f[f"{wh}|copula"] = 1.0 if ({"is", "are", "was", "were"} & set(tokens[:8])) else 0.0

    # sentence shape
    f[f"len:{_bucket(len(tokens), (8, 14, 22, 35))}"] = 1.0
    f["starts_pronoun"] = 1.0 if tokens and tokens[0] in ("it", "he", "she", "they", "this", "these", "his", "her") else 0.0
    f["starts_lower"] = 1.0 if sentence[:1].islower() else 0.0
    f["ends_period"] = 1.0 if sentence.rstrip()[-1:] in ".!?" else 0.0
    f["has_equals_or_pipe"] = 1.0 if ("=" in sentence or "|" in sentence or " ; " in sentence) else 0.0
    for d in deviations:
        f[f"gate:{d}"] = 1.0
    f["gate_count"] = float(len(deviations))
    return f


def score(weights: Mapping[str, float], feats: Mapping[str, float]) -> float:
    return sum(weights.get(k, 0.0) * v for k, v in feats.items())


def probability(weights: Mapping[str, float], feats: Mapping[str, float]) -> float:
    z = max(-30.0, min(30.0, score(weights, feats)))
    return 1.0 / (1.0 + math.exp(-z))


def decide(question: str, candidates: Sequence[Mapping[str, Any]], weights: Mapping[str, float], *,
           threshold: float, margin: float = 0.0, deviation_fn=None) -> dict[str, Any]:
    """Pick the most responsive candidate or abstain with a typed reason.

    Each candidate needs `text` and optionally `title`; `deviation_fn(question, text, title)` supplies the
    gate's named deviations when given."""
    best = None
    scored = []
    for rank, row in enumerate(candidates):
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        title = str(row.get("title") or row.get("source_title") or "")
        deviations = list(deviation_fn(question, text, title)) if deviation_fn else []
        feats = features(question, text, title, rank, deviations)
        p = probability(weights, feats)
        scored.append((p, rank, row, feats))
    if not scored:
        return {"status": "no_candidates", "evidence": None, "reasons": []}
    scored.sort(key=lambda s: (-s[0], s[1]))
    p, _rank, row, feats = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    contributions = sorted(((weights.get(k, 0.0) * v, k) for k, v in feats.items()), key=lambda t: t[0])
    if p < threshold or p - second < margin and second >= threshold:
        worst = [k for c, k in contributions[:3] if c < 0]
        return {"status": "rejected", "evidence": row, "probability": round(p, 4),
                "dimensions": ["low_responsiveness"],
                "reasons": ["the sentence is unlikely to answer the question (p=%.2f): %s"
                            % (p, ", ".join(worst) or "weak evidence overall")]}
    return {"status": "accepted", "evidence": row, "probability": round(p, 4), "reasons": [],
            "why": [(k, round(c, 3)) for c, k in contributions[-3:]]}
