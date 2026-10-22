"""Induce relation specs from labelled (question, sentence, answer) triples (Phase 13, workstream B).

An LLM author writes triples in bulk: a question, the sentence that states the answer, and the
answer as an exact span of that sentence. Each triple is aligned (entity in the question and the
sentence, answer span in the sentence) and turned into a question frame and a sentence pattern in
the Phase 11 pattern language:

    question   Who directed E       ->  X[who] V.any:v TAIL:E     (the verb is bound if the sentence uses it)
    sentence   E was directed by A  ->  E COP V.part[@v] P[by] NP[cap]:A

Triples that share the same frame and sentence pattern are one candidate spec once enough of them
agree. The induced candidate is only a proposal: the Phase 11 verifier (replay, held-out, contrast,
fire rate, bank non-regression) and the measured precision gate decide, exactly as for a teacher's.
"""
from __future__ import annotations

import collections
import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from crms_patterns import PatternLanguage, Token, chunk, tokenize

_WH = frozenset({"what", "who", "whom", "when", "where", "which", "how", "why", "whose"})
_MONTHS = frozenset({"january", "february", "march", "april", "may", "june", "july", "august",
                     "september", "october", "november", "december"})
_STOP = frozenset({"the", "a", "an", "of", "in", "on", "at", "by", "for", "to", "and", "or", "is", "was",
                   "are", "were", "did", "does", "do", "has", "have", "had"}) | _WH
MAX_BETWEEN = 12


def _gap(n: int) -> str:
    """Gap element for n unknown tokens, bucketed so triples with similar spacing agree."""
    return "...{0,2}" if n <= 1 else "...{0,4}" if n <= 3 else "...{0,8}" if n <= 7 else "...{0,13}"


@dataclass(frozen=True)
class Induced:
    frame: str
    pattern: str
    entity: str
    answer: str
    verb: str


def _find(seq: Sequence[str], sub: Sequence[str], skip: tuple[int, int] | None = None) -> int | None:
    for i in range(len(seq) - len(sub) + 1):
        if list(seq[i:i + len(sub)]) == list(sub):
            if skip and not (i + len(sub) <= skip[0] or i >= skip[1]):
                continue
            return i
    return None


def _entity(q: list[Token], s: list[Token], answer: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """The question phrase that also occurs in the sentence outside the answer: the run with the most
    capitalised tokens, then the longest. Verbs and function words cannot start or end it
    (so "founded Acme" is not an entity, "Acme" is). Returns (q_start, q_end, s_start, s_end)."""
    q_low = [t.low for t in q]
    s_low = [t.low for t in s]

    def edge_ok(t: Token) -> bool:
        return t.low not in _STOP and "VERB" not in t.cls and not t.cls & {"PREP", "DET", "AUX", "COP", "CONJ"}

    best = None
    best_key = (-1, -1)
    for i in range(len(q)):
        if not edge_ok(q[i]):
            continue
        for j in range(len(q), i, -1):
            if not edge_ok(q[j - 1]):
                continue
            run = q_low[i:j]
            k = _find(s_low, run, skip=answer)
            if k is None:
                continue
            caps = sum(1 for t in q[i:j] if t.kind == "CAP")
            if (caps, j - i) > best_key:
                best_key = (caps, j - i)
                best = (i, j, k, k + len(run))
            break
    return best


def _verb_lemmas(token: Token, language: PatternLanguage) -> set[str]:
    return set(language.lemmas(token))


def _answer_element(s: list[Token], span: tuple[int, int], gold: str, language: PatternLanguage
                    ) -> str:
    """Typed element for numbers, dates and noun phrases; otherwise a bounded span that stops at
    the token that follows the answer in the sentence (or the sentence end)."""
    i, j = span
    words = [t.low for t in s[i:j]]
    if all(t.kind == "NUM" for t in s[i:j]):
        return "NUM:A" if j - i == 1 else "NUMRANGE:A"
    if words and words[0] in _MONTHS:
        return "DATE:A"
    starts = chunk(s, language)
    if any(c.type == "NP" and c.j == j for c in starts.get(i, [])):
        return "NP[cap]:A" if any(t.kind == "CAP" for t in s[i:j]) else "NP:A"
    n = j - i
    if j >= len(s):
        return "TAIL:A"
    nxt = s[j]
    anchor = "," if nxt.text == "," else f"X[{nxt.low}]"
    return f"...{{{max(1, n - 1)},{n + 2}}}:A {anchor}"


def induce(question: str, sentence: str, gold: str, language: PatternLanguage) -> Induced | None:
    q = [t for t in tokenize(question, language) if t.kind not in ("PUNCT",)]
    s = tokenize(sentence, language)
    g = [t.low for t in tokenize(gold, language)]
    s_low = [t.low for t in s]
    start = _find(s_low, g)
    if start is None or not g:
        return None
    ans = (start, start + len(g))
    ent = _entity(q, s, ans)
    if ent is None:
        return None
    qs, qe, ss, se = ent

    # ---- question frame
    q_verb = next((t for t in q[:qs] + q[qe:] if "VERB" in t.cls and not t.cls & {"AUX", "COP", "DET", "PREP"}
                   and t.low not in _STOP), None)
    q_lemmas = _verb_lemmas(q_verb, language) if q_verb else set()

    # ---- sentence pattern: entity before or after the answer
    if se <= ans[0]:
        between = s[se:ans[0]]
        order = "E-A"
    elif ans[1] <= ss:
        between = s[ans[1]:ss]
        order = "A-E"
    else:
        return None
    if len(between) > MAX_BETWEEN:
        return None
    answer_element = _answer_element(s, ans, gold, language)
    q_words = {t.low for t in q}
    # a question content word standing next to the answer in the sentence names the asked thing
    # ("how many SEASONS did E play"): abstract it so one spec covers every such noun
    q_noun = None
    for k_, t_ in enumerate(q):
        if (qs <= k_ < qe) or t_.low in _STOP or t_ is q_verb or "PREP" in t_.cls or "DET" in t_.cls \
                or "AUX" in t_.cls or "COP" in t_.cls or t_.kind != "WORD":
            continue
        for pos_ in (ans[1], ans[0] - 1):
            if 0 <= pos_ < len(s) and s[pos_].low == t_.low and not (ans[0] <= pos_ < ans[1]):
                q_noun = t_
    parts: list[str] = []
    bound_verb = ""
    gap = 0

    def flush() -> None:
        nonlocal gap
        if gap:
            parts.append(_gap(gap))
            gap = 0

    for k, t in enumerate(between):
        if "COP" in t.cls:
            flush(); parts.append("COP")
        elif "AUX" in t.cls:
            flush(); parts.append("AUX")
        elif "DET" in t.cls:
            flush(); parts.append("DET")
        elif "PREP" in t.cls:
            flush(); parts.append(f"P[{t.low}]")
        elif t.text == ",":
            flush(); parts.append(",")
        elif "VERB" in t.cls and q_lemmas & _verb_lemmas(t, language):
            flush()
            lemma = sorted(q_lemmas & _verb_lemmas(t, language))[0]
            passive = k > 0 and ("COP" in between[k - 1].cls or "AUX" in between[k - 1].cls)
            kind = ("part" if passive else
                    "ing" if language.verb_ok(t, lemma, "ing") else "fin")
            parts.append(f"V.{kind}[@v]")
            bound_verb = lemma
        elif t.low in q_words and t.low not in _STOP:
            flush(); parts.append(f"W[{t.low}]")
        else:
            gap += 1
    flush()
    entity_text = " ".join(t.text for t in q[qs:qe])
    noun_after = q_noun is not None and ans[1] < len(s) and s[ans[1]].low == q_noun.low
    noun_before = q_noun is not None and ans[0] > 0 and s[ans[0] - 1].low == q_noun.low
    a_el = answer_element
    if noun_after:
        a_el = answer_element + " QPHRASE"
    elif noun_before:
        a_el = "QPHRASE " + answer_element
    pattern = (" ".join(["E"] + parts + [a_el]) if order == "E-A"
               else " ".join([a_el] + parts + ["E~"]))
    if noun_before and order == "E-A":
        # the noun sits between the relation words and the answer: keep it in the right slot
        pattern = " ".join(["E"] + parts + ["QPHRASE", answer_element])

    # ---- question frame
    pre, post = q[:qs], q[qe:]
    frame_parts: list[str] = []
    verb_done = False
    for t in pre:
        if t is q_verb and bound_verb:
            frame_parts.append("V.any:v"); verb_done = True
        elif t.low in _STOP or "PREP" in t.cls or "DET" in t.cls:
            frame_parts.append(f"X[{t.low}]")
        elif t is q_noun:
            frame_parts.append("...{1,1}:q")
        else:
            frame_parts.append(f"W[{t.low}]")
    n = qe - qs
    last = not post
    entity_el = "TAIL:E" if last else "...{1,9}:E"
    frame_parts.append(entity_el)
    for t in post:
        if t is q_verb and bound_verb and not verb_done:
            frame_parts.append("V.any:v"); verb_done = True
        elif t.low in _STOP or "PREP" in t.cls or "DET" in t.cls:
            frame_parts.append(f"X[{t.low}]")
        elif t is q_noun:
            frame_parts.append("...{1,1}:q")
        else:
            frame_parts.append(f"W[{t.low}]")
    return Induced(frame=" ".join(frame_parts), pattern=pattern, entity=entity_text,
                   answer=gold, verb=bound_verb)


def generalise(frame: str, pattern: str, level: int) -> tuple[str, str]:
    """Progressively coarser forms of one induced (frame, pattern) pair.

    0 exact; 1 literal content words in the sentence become short gaps; 2 prepositions in the
    sentence match any preposition; 3 content words in the question frame become short gaps (the
    wh-word, auxiliary, bound verb, and noun slot remain)."""
    def literal(element: str, kind: str) -> bool:
        return element.startswith(kind + "[") and element.endswith("]")

    sent = pattern.split(" ")
    ques = frame.split(" ")
    if level >= 1:
        sent = ["...{0,2}" if literal(e, "W") else e for e in sent]
    if level >= 2:
        sent = ["P" if literal(e, "P") else e for e in sent]
    if level >= 3:
        ques = ["...{0,3}" if literal(e, "W") else e for e in ques]
    return " ".join(ques), " ".join(sent)


def propose(triples: Sequence[Mapping[str, Any]], language: PatternLanguage, *,
            min_group: int = 4, max_specs: int = 120) -> list[dict[str, Any]]:
    """Candidate specs (verifier format) for shapes that at least `min_group` triples agree on.

    Each triple joins the most specific level (0 to 3) at which enough other triples share its
    shape, so a rare shape stays precise and a common one is generalised."""
    induced = []
    for triple in triples:
        got = induce(triple["question"], triple["support"], triple["gold"], language)
        if got:
            induced.append((triple, got))
    assigned: set[int] = set()
    groups: list[tuple[int, tuple[str, str], list[tuple[Mapping[str, Any], Induced]]]] = []
    for level in range(4):
        buckets: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
        for index, (_t, got) in enumerate(induced):
            if index not in assigned:
                buckets[generalise(got.frame, got.pattern, level)].append(index)
        for key, members in buckets.items():
            if len(members) >= min_group:
                assigned.update(members)
                groups.append((level, key, [induced[m] for m in members]))
    by_title: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for triple in triples:
        by_title[triple.get("title", "")].append(triple)
    out = []
    for level, (frame, pattern), rows in sorted(groups, key=lambda g: -len(g[2])):
        rows = sorted(rows, key=lambda r: r[0]["id"])
        support, heldout = rows[:-1][:4], rows[-1:]

        def items(part):
            return [{"q": t["question"], "S": t["support"], "A": i.answer, "E": i.entity} for t, i in part]

        contrast = []
        for t, _i in rows[:3]:
            others = [o for o in by_title.get(t.get("title", ""), []) if o["support"] != t["support"]]
            if others:
                contrast.append({"q": t["question"], "S": others[0]["support"]})
        digest = hashlib.sha1((frame + "|" + pattern).encode()).hexdigest()[:8]
        verb = rows[0][1].verb
        out.append({
            "name": f"ind{level}_{digest}", "priority": 60 + level, "question_patterns": [frame],
            "sentence_patterns": [pattern], "template": "{A}.", "verb_class": "",
            "support": items(support), "heldout": items(heldout), "contrast": contrast,
            "rationale": f"induced from {len(rows)} labelled examples at generalisation level {level}"
                         + (f" (verb {verb})" if verb else ""),
            "group_size": len(rows), "level": level})
        if len(out) >= max_specs:
            break
    return out
