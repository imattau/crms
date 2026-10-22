"""A small, inspectable extractive reader (Phase 13, workstream B).

Hand-written specs cover one question shape each and the shapes are heavy-tailed. This reader
generalises across shapes the way a pre-trained model would, but every part of it is visible:

* candidates are phrases the pattern layer already finds (noun phrases, numbers, dates, clause
  tails) in the retrieved sentences;
* each candidate is described by named features (question word and candidate type, the word before
  the candidate, overlap of rarity-weighted question terms near it, distance from the entity, ...);
* the score is a linear sum of feature weights stored in a plain table, so the reason for any answer
  is the list of features and weights that produced it;
* it answers only when its calibrated confidence passes a threshold; otherwise it abstains with a
  typed reason (`low_confidence`, `no_candidate`).

Training (`run_phase13_reader_train.py`) learns the weights from LLM-authored triples by
softmax regression, in pure Python and deterministically. Nothing here calls a model at run time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from crms_patterns import PatternLanguage, Token, chunk, tokenize
from crms_word_rarity import weight as word_weight

_WH = ("what", "who", "whom", "whose", "when", "where", "which", "why", "how")
_STOP = frozenset("""a an the of in on at by for to with from as is are was were be been being do does did
has have had and or that this these those it its their his her which who whom whose what when where why
how many much""".split())
_MONTHS = frozenset({"january", "february", "march", "april", "may", "june", "july", "august",
                     "september", "october", "november", "december"})
MAX_CANDIDATES = 60


@dataclass(frozen=True)
class QuestionInfo:
    wh: str
    second: str            # the word after the wh-word ("many", "is", "did", ...)
    terms: tuple[str, ...]   # content words (lower case)
    entity: tuple[str, ...]  # longest capitalised or multi-word run (lower case)
    verbs: frozenset[str]


def analyse_question(question: str, language: PatternLanguage) -> QuestionInfo:
    toks = [t for t in tokenize(question, language) if t.kind != "PUNCT"]
    low = [t.low for t in toks]
    wh = next((w for w in low if w in _WH), "other")
    k = low.index(wh) if wh in low else 0
    second = low[k + 1] if k + 1 < len(low) else ""
    terms = tuple(w for w in low if w not in _STOP and not w.isdigit())
    # entity: the longest run of capitalised tokens after the wh-word (or any run of >=2 content words)
    best: list[str] = []
    run: list[str] = []
    for t in toks[k + 1:]:
        if t.kind == "CAP" and t.low not in _WH:
            run.append(t.low)
        else:
            if len(run) > len(best):
                best = run
            run = []
    if len(run) > len(best):
        best = run
    verbs = frozenset(lemma for t in toks for lemma in language.lemmas(t) if t.low not in _STOP)
    return QuestionInfo(wh, second, terms, tuple(best), verbs)


@dataclass
class Candidate:
    sentence_index: int
    start: int
    end: int
    kind: str              # np | num | date | tail
    text: str


def candidates(sentence: str, tokens: Sequence[Token], language: PatternLanguage,
               sentence_index: int) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[tuple[int, int, str]] = set()

    def add(i: int, j: int, kind: str) -> None:
        if j <= i or (i, j, kind) in seen:
            return
        seen.add((i, j, kind))
        out.append(Candidate(sentence_index, i, j, kind,
                             sentence[tokens[i].start:tokens[j - 1].end]))

    starts = chunk(tokens, language)
    for i in range(len(tokens)):
        for c in starts.get(i, []):
            if c.type == "NP":
                add(c.i, c.j, "np")
        t = tokens[i]
        if t.kind == "NUM":
            add(i, i + 1, "num")
            if i + 1 < len(tokens) and tokens[i + 1].low in ("million", "billion", "thousand", "percent", "%"):
                add(i, i + 2, "num")
        if t.low in _MONTHS and i + 1 < len(tokens) and tokens[i + 1].kind == "NUM":
            end = i + 2
            if end < len(tokens) and tokens[end].kind == "NUM":
                end += 1
            add(i, end, "date")
        if "COP" in t.cls or t.low in ("because", "by", "using", "via"):
            j = i + 1
            while j < len(tokens) and tokens[j].text not in (",", ";", ":"):
                j += 1
            add(i + 1, j, "tail")
    return out[:MAX_CANDIDATES]


def _bucket(n: int, edges: Sequence[int] = (1, 2, 3, 5, 8, 13)) -> str:
    for e in edges:
        if n <= e:
            return f"<={e}"
    return f">{edges[-1]}"


def features(q: QuestionInfo, tokens: Sequence[Token], cand: Candidate, *, title: str,
             sentence_rank: int, language: PatternLanguage) -> dict[str, float]:
    """Named features of one candidate; every key is readable."""
    f: dict[str, float] = {}
    low = [t.low for t in tokens]
    span = tokens[cand.start:cand.end]
    span_low = {t.low for t in span}
    prev = tokens[cand.start - 1] if cand.start > 0 else None
    prev2 = tokens[cand.start - 2] if cand.start > 1 else None
    nxt = tokens[cand.end] if cand.end < len(tokens) else None
    ctype = ("cap" if any(t.kind == "CAP" for t in span) else "plain")
    if cand.kind in ("num", "date", "tail"):
        ctype = cand.kind
    elif span and all(t.kind == "NUM" for t in span):
        ctype = "num"
    key = f"{q.wh}|{q.second if q.wh in ('how', 'what') else '*'}"
    f[f"type:{key}|{ctype}"] = 1.0
    f[f"type:{q.wh}|{ctype}"] = 1.0
    if prev is not None:
        f[f"prev:{q.wh}|{prev.low}"] = 1.0
        f[f"prevclass:{q.wh}|{'prep' if 'PREP' in prev.cls else 'cop' if 'COP' in prev.cls else 'det' if 'DET' in prev.cls else 'punct' if prev.kind == 'PUNCT' else 'word'}"] = 1.0
    if prev2 is not None and prev is not None:
        f[f"prev2:{q.wh}|{prev2.low}_{prev.low}"] = 1.0
    next_kind = "end" if nxt is None else (nxt.low if nxt.kind == "PUNCT" else "word")
    f[f"next:{q.wh}|{next_kind}"] = 1.0
    f[f"len:{q.wh}|{ctype}|{_bucket(cand.end - cand.start)}"] = 1.0
    f["at_sentence_start"] = 1.0 if cand.start == 0 else 0.0

    # overlap of rarity-weighted question terms with the sentence and with the window around the candidate
    present = [w for w in q.terms if w in low]
    total = sum(word_weight(w) for w in q.terms) or 1.0
    f["sentence_overlap"] = sum(word_weight(w) for w in present) / total
    window = set(low[max(0, cand.start - 6):cand.start]) | set(low[cand.end:cand.end + 6])
    f["window_overlap"] = sum(word_weight(w) for w in q.terms if w in window) / total
    f["candidate_in_question"] = len(span_low & set(q.terms)) / max(1, len(span_low))
    f["missing_rare_terms"] = sum(1.0 for w in q.terms if w not in low and word_weight(w) >= 6.0)

    # entity position
    ent = list(q.entity)
    if ent:
        pos = [i for i in range(len(low) - len(ent) + 1) if low[i:i + len(ent)] == ent]
        f["entity_present"] = 1.0 if pos else 0.0
        if pos:
            d = min(min(abs(cand.start - (p + len(ent))), abs(p - cand.end)) for p in pos)
            f[f"entity_dist:{_bucket(d)}"] = 1.0
            f[f"entity_side:{q.wh}|{'after' if any(p + len(ent) <= cand.start for p in pos) else 'before'}"] = 1.0
            f["candidate_overlaps_entity"] = 1.0 if any(p < cand.end and p + len(ent) > cand.start for p in pos) else 0.0
        else:
            f["entity_in_title"] = 1.0 if all(w in title.lower() for w in ent) else 0.0

    # the question's verb stands next to the candidate
    verb_near = False
    for t in tokens[max(0, cand.start - 4):cand.end + 4]:
        if q.verbs & set(language.lemmas(t)):
            verb_near = True
    f["verb_near"] = 1.0 if verb_near else 0.0
    f[f"verb_near:{q.wh}"] = 1.0 if verb_near else 0.0
    f[f"sentence_rank:{min(sentence_rank, 3)}"] = 1.0
    # cue words before the candidate for reason and method questions
    before = set(low[max(0, cand.start - 5):cand.start])
    for cue in ("because", "due", "so", "in", "order", "by", "using", "through", "via", "such", "including", "called", "known"):
        if cue in before:
            f[f"cue:{q.wh}|{cue}"] = 1.0
    f["bias"] = 1.0
    return f


def score(weights: Mapping[str, float], feats: Mapping[str, float]) -> float:
    return sum(weights.get(k, 0.0) * v for k, v in feats.items())


def read(question: str, sentences: Sequence[Mapping[str, Any]], weights: Mapping[str, float],
         language: PatternLanguage, *, threshold: float = 0.5, margin: float = 0.0) -> dict[str, Any]:
    """Best span across the sentences, or a typed abstention.

    Returns {status, answer, sentence, title, confidence, why} where `why` lists the five strongest
    feature contributions for the chosen span."""
    q = analyse_question(question, language)
    pool: list[tuple[Candidate, dict[str, float], Mapping[str, Any]]] = []
    for rank, row in enumerate(sentences):
        text = str(row.get("text", ""))
        toks = tokenize(text, language)
        if not toks:
            continue
        for cand in candidates(text, toks, language, rank):
            pool.append((cand, features(q, toks, cand, title=str(row.get("title", "")),
                                        sentence_rank=rank, language=language), row))
    if not pool:
        return {"status": "no_candidate", "answer": "", "confidence": 0.0}
    scores = [score(weights, f) for _c, f, _r in pool]
    peak = max(scores)
    exps = [math.exp(s - peak) for s in scores]
    total = sum(exps)
    order = sorted(range(len(pool)), key=lambda k: -scores[k])
    top = order[0]
    conf = exps[top] / total
    second = exps[order[1]] / total if len(order) > 1 else 0.0
    cand, feats, row = pool[top]
    contributions = sorted(((weights.get(k, 0.0) * v, k) for k, v in feats.items()), reverse=True)[:5]
    result = {"status": "answered", "answer": cand.text, "sentence": str(row.get("text", "")),
              "title": str(row.get("title", "")), "citation": row.get("citation", ""),
              "confidence": round(conf, 4), "margin": round(conf - second, 4),
              "why": [(k, round(w, 3)) for w, k in contributions]}
    if conf < threshold or conf - second < margin:
        result["status"] = "low_confidence"
    return result
