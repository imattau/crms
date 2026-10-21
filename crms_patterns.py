"""Structure-aware pattern matching for CRMS (Phase 11).

This is deliberately not a regex wrapper. Text becomes tokens with features,
tokens become shallow chunks (noun phrases, prepositional phrases, verb groups,
parentheticals), and patterns written in a small language are matched against
that structure by a backtracking matcher that returns captures and a trace.

Pattern language (elements are separated by spaces):

    E  E~            the question entity (E~ = a noun phrase ending with it)
    NP:a  NP[cap]:a  NP[name]:a  NP[cls=name]:a   a noun phrase (any / containing a capital / ending in a name / ending in a class member)
    PP[in|on]:p      a prepositional phrase
    P[by]  P[in|on]:p  a preposition token, optionally one of several, optionally captured
    COP  AUX  DET    copula / auxiliary-or-copula / determiner token
    V.part[@v]  V.fin[@v]  V.ing[@v]  V.any[@v]   a form of the question's verb
    V.any:v          any known verb; binds its lemma
    N.agent[@v]      an agentive noun of the question's verb (writer, director)
    CLS[name]        a member of an induced word class
    W[word|word]     a word matched by stem
    ...{0,8}:g       a bounded gap that never crosses ; or :
    TAIL:a           everything to the end of the sentence
    NUM  NUMRANGE  DATE   typed values
    QPHRASE          the question phrase, matched by stem
    ,  ,?            a comma, optionally
    ( a | b )  (...)?   alternation and optional groups

Matching is deterministic and bounded: a step budget stops runaway
backtracking and the caller is told when results were truncated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence

DET = frozenset({"the", "a", "an", "this", "that", "these", "those", "his",
                 "her", "its", "their", "our", "my", "your", "some", "any",
                 "each", "every", "no"})
PREP = frozenset({"in", "on", "at", "by", "for", "from", "to", "with", "of",
                  "near", "within", "under", "over", "into", "onto", "after",
                  "before", "during", "since", "until", "through", "across",
                  "along", "about", "around", "between", "as", "than",
                  "against", "among", "per", "via", "off", "up", "down"})
CONJ = frozenset({"and", "or", "but", "nor", "yet", "so", "because",
                  "although", "while", "whereas", "though", "if", "when",
                  "which", "who", "that", "whom", "whose", "where"})
COPS = frozenset({"is", "are", "was", "were", "be", "been", "being", "am"})
AUX = frozenset({"has", "have", "had", "do", "does", "did", "will", "would",
                 "can", "could", "may", "might", "shall", "should", "must"})
PRON = frozenset({"he", "she", "it", "they", "we", "i", "you", "him", "them",
                  "us", "me", "who", "whom"})
BARRIERS = frozenset({";", ":"})
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
DEFAULT_BUDGET = 200_000

_TOKEN = re.compile(r"\d[\d,]*\d|\d|[^\W\d_][\w'’\-]*|[–—\-]|[,;:()\"“”]")
_ELEMENT = re.compile(
    r"([A-Za-z~,\.]+(?:\.[a-z]+)?|\.\.\.)(\{\d+,\d+\})?(\[[^\]]*\])?"
    r"(:[A-Za-z_]+)?(\?)?")


class PatternError(ValueError):
    """A pattern is malformed or names an unknown element."""


class Token:
    __slots__ = ("text", "low", "start", "end", "kind", "cls")

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.low = text.lower()
        self.start = start
        self.end = end
        self.cls: set[str] = set()
        if re.fullmatch(r"\d[\d,]*", text):
            self.kind = "NUM"
        elif re.fullmatch(r"[,;:()\"“”]", text):
            self.kind = "PUNCT"
        elif text in "–—-":
            self.kind = "DASH"
        elif text[:1].isupper():
            self.kind = "CAP"
        else:
            self.kind = "WORD"
        for name, words in (("DET", DET), ("PREP", PREP), ("CONJ", CONJ),
                            ("COP", COPS), ("AUX", AUX), ("PRON", PRON)):
            if self.low in words:
                self.cls.add(name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.text!r},{self.kind})"


class Chunk:
    __slots__ = ("type", "i", "j")

    def __init__(self, kind: str, i: int, j: int) -> None:
        self.type = kind
        self.i = i
        self.j = j


@dataclass
class PatternLanguage:
    """Open-class resources the matcher needs.

    verbs maps a lemma to (base, third-person, past, participle); agent_nouns
    maps a lemma to its agentive nouns; classes maps a class name to members.
    All three are loaded from SQL by `crms_pattern_memory`.
    """

    verbs: Mapping[str, Sequence[str]] = field(default_factory=dict)
    agent_nouns: Mapping[str, Iterable[str]] = field(default_factory=dict)
    classes: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._inverse: dict[str, set[str]] = {}
        for lemma in self.verbs:
            for value in self.forms(lemma).values():
                for form in (value if isinstance(value, set) else {value}):
                    self._inverse.setdefault(form, set()).add(lemma)

    def forms(self, lemma: str) -> dict[str, Any]:
        base, s3, past, part = self.verbs[lemma]
        ing = {base + "ing",
               (base[:-1] + "ing") if base.endswith("e") else base + "ing",
               base + base[-1] + "ing"}
        return {"base": base, "s3": s3, "past": past, "part": part,
                "ing": ing, "fin": {s3, past, base},
                "any": {base, s3, past, part} | ing}

    def verb_ok(self, token: Token, lemma: str, kind: str) -> bool:
        value = self.forms(lemma)[kind]
        return token.low in (value if isinstance(value, set) else {value})

    def lemmas(self, token: Token) -> set[str]:
        return self._inverse.get(token.low, set())


def tokenize(text: str, language: PatternLanguage) -> list[Token]:
    tokens = [Token(m.group(), m.start(), m.end())
              for m in _TOKEN.finditer(text.rstrip().rstrip("."))]
    for token in tokens:
        if language.lemmas(token):
            token.cls.add("VERB")
    return tokens


def chunk(tokens: Sequence[Token], language: PatternLanguage
          ) -> dict[int, list[Chunk]]:
    """Rule-based shallow parse. starts[i] lists chunks beginning at token i,
    longest noun phrase first."""
    n = len(tokens)
    starts: dict[int, list[Chunk]] = {i: [] for i in range(n + 1)}
    closed = {"DET", "PREP", "CONJ", "COP", "AUX", "PRON"}

    def content(k: int, prev: bool, det: bool) -> bool:
        t = tokens[k]
        if t.kind in ("PUNCT", "DASH") or t.cls & closed:
            return False
        if "VERB" in t.cls:
            # A verb form may modify a noun only after a determiner and a
            # lowercase word, and only before another content word
            # ("the managing director"), never after a name ("Jane built X").
            return bool(det and prev and tokens[k - 1].kind == "WORD"
                        and k + 1 < n
                        and tokens[k + 1].kind in ("WORD", "CAP", "NUM")
                        and not tokens[k + 1].cls & {"DET", "PREP", "CONJ",
                                                     "COP", "AUX"})
        return True

    def np_end(i: int) -> int | None:
        j = i
        det = False
        if j < n and "DET" in tokens[j].cls:
            j += 1
            det = True
        k = j
        while k < n and content(k, k > i, det):
            k += 1
        return None if k == j else k

    def np_levels(i: int) -> list[int]:
        e = np_end(i)
        out: list[int] = []
        if e is None:
            return out
        out.append(e)
        while True:
            if e < n and tokens[e].low == "of":
                e2 = np_end(e + 1)
                if e2:
                    e = e2
                    out.append(e)
                    continue
            if (e < n and (tokens[e].low == "and" or tokens[e].text == ",")
                    and e + 1 < n and tokens[e - 1].kind == "CAP"
                    and tokens[e + 1].kind == "CAP"):
                e2 = np_end(e + 1)
                if e2:
                    e = e2
                    out.append(e)
                    continue
            break
        return out

    for i in range(n):
        t = tokens[i]
        if t.text == "(":
            k = i + 1
            while k < n and tokens[k].text != ")":
                k += 1
            starts[i].append(Chunk("PAREN", i, min(k + 1, n)))
        for e in np_levels(i):
            starts[i].append(Chunk("NP", i, e))
        if "PREP" in t.cls and i + 1 < n:
            levels = np_levels(i + 1)
            if levels:
                starts[i].append(Chunk("PP", i, levels[-1]))
        if t.cls & {"COP", "AUX", "VERB"}:
            k = i
            while k < n and tokens[k].cls & {"COP", "AUX", "VERB"}:
                k += 1
            starts[i].append(Chunk("VG", i, k))
    for i in starts:
        starts[i].sort(key=lambda c: -(c.j - c.i))
    return starts


def parse_pattern(source: str) -> list[list[tuple]]:
    """Parse the pattern language into alternatives of elements
    (name, (range, arg), capture, optional)."""
    s = source.strip()
    pos = [0]

    def group(closing: str | None) -> list[list[tuple]]:
        alts: list[list[tuple]] = [[]]
        while pos[0] < len(s):
            while pos[0] < len(s) and s[pos[0]] == " ":
                pos[0] += 1
            if pos[0] >= len(s):
                break
            c = s[pos[0]]
            if c == closing:
                pos[0] += 1
                return alts
            if c == "|":
                pos[0] += 1
                alts.append([])
                continue
            if c == "(":
                pos[0] += 1
                sub = group(")")
                optional = False
                if pos[0] < len(s) and s[pos[0]] == "?":
                    optional = True
                    pos[0] += 1
                alts[-1].append(("GROUP", (None, sub), None, optional))
                continue
            m = _ELEMENT.match(s, pos[0])
            if not m or m.end() == pos[0]:
                raise PatternError(
                    f"bad pattern at {pos[0]}: {s[pos[0]:pos[0] + 15]!r}")
            pos[0] = m.end()
            alts[-1].append((m.group(1), (m.group(2), m.group(3)),
                             m.group(4)[1:] if m.group(4) else None,
                             bool(m.group(5))))
        return alts

    return group(None)


@dataclass
class MatchContext:
    language: PatternLanguage
    tokens: Sequence[Token]
    starts: Mapping[int, list[Chunk]]
    entity_tokens: Sequence[str] = ()
    variables: Mapping[str, Any] = field(default_factory=dict)


class _BudgetExceeded(Exception):
    pass


class _LimitReached(Exception):
    pass


def stem(word: str) -> str:
    w = word.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def span_text(text: str, tokens: Sequence[Token],
              binds: Mapping[str, Any], name: str) -> str:
    i, j = binds[name]
    return text[tokens[i].start:tokens[j - 1].end] if j > i else ""


def match_patterns(alternatives: Sequence[list[tuple]], ctx: MatchContext, *,
                   limit: int = 30,
                   start_positions: Iterable[int] | None = None,
                   budget: int = DEFAULT_BUDGET
                   ) -> list[dict[str, Any]]:
    """Return matches sorted by (gap cost, start). Each match is a dict with
    binds, start, end, alt, trace, cost, truncated. `truncated` is True when the
    step budget or the match limit stopped the search."""
    tokens = ctx.tokens
    n = len(tokens)
    steps = [0]
    lang = ctx.language

    def run(seq, k, pos, b, trace, cont):
        if k == len(seq):
            yield from cont(pos, b, trace)
            return
        optional = seq[k][3]
        yield from step(seq, k, pos, b, trace, cont)
        if optional:
            yield from run(seq, k + 1, pos, b, trace, cont)

    def step(seq, k, pos, b, trace, cont):
        steps[0] += 1
        if steps[0] > budget:
            raise _BudgetExceeded()
        name, (rng, arg), cap, _opt = seq[k]
        T = tokens

        def nxt(npos, nb=None):
            return run(seq, k + 1, npos, nb if nb is not None else b,
                       trace + [(name, pos, npos)], cont)

        def bind(npos, extra=None):
            nb = dict(b)
            if cap:
                nb[cap] = (pos, npos)
            if extra:
                nb.update(extra)
            return nb

        argv = arg[1:-1] if isinstance(arg, str) else None
        if name == "GROUP":
            for alt in arg:
                yield from run(alt, 0, pos, b, trace,
                               lambda p, bb, tr: run(seq, k + 1, p, bb, tr, cont))
            return
        if name == "...":
            lo, hi = (int(x) for x in rng[1:-1].split(","))
            for length in range(lo, hi + 1):
                if pos + length > n:
                    break
                if any(T[q].text in BARRIERS for q in range(pos, pos + length)):
                    break
                yield from nxt(pos + length, bind(pos + length))
            return
        if pos >= n:
            return
        t = T[pos]
        if name in ("E", "E~"):
            et = list(ctx.entity_tokens)
            if not et:
                return
            if name == "E":
                if [x.low for x in T[pos:pos + len(et)]] == et:
                    yield from nxt(pos + len(et), bind(pos + len(et)))
            else:
                for c in ctx.starts.get(pos, []):
                    if c.type != "NP":
                        continue
                    seg = [x.low for x in T[c.i:c.j]]
                    if len(seg) >= len(et) and seg[-len(et):] == et:
                        yield from nxt(c.j, bind(c.j))
                        break
            return
        if name in ("NP", "PP"):
            for c in ctx.starts.get(pos, []):
                if c.type != name:
                    continue
                if name == "PP" and argv and T[c.i].low not in argv.split("|"):
                    continue
                if (name == "NP" and argv == "cap"
                        and not any(x.kind == "CAP" for x in T[c.i:c.j])):
                    continue
                if (name == "NP" and argv == "name"
                        and not (T[c.j - 1].kind in ("CAP", "NUM")
                                 and any(x.kind == "CAP" for x in T[c.i:c.j]))):
                    continue   # a name ends in a capitalised word or number
                if (name == "NP" and argv and argv.startswith("cls=")
                        and T[c.j - 1].low not in lang.classes.get(argv[4:], {})):
                    continue
                yield from nxt(c.j, bind(c.j))
            return
        if name == "TAIL":
            yield from nxt(n, bind(n))
            return
        if name == "DET":
            if "DET" in t.cls:
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "COP":
            if "COP" in t.cls:
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "AUX":
            if t.cls & {"AUX", "COP"}:
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "P":
            if "PREP" in t.cls and (argv is None or t.low in argv.split("|")):
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "W":
            if any(stem(t.low) == stem(w) for w in (argv or "").split("|")):
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == ",":
            if t.text == ",":
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "CLS":
            if t.low in lang.classes.get(argv or "", {}):
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name.startswith("V."):
            kind = name[2:]
            if argv == "@v":
                lemmas = [ctx.variables["v"]] if "v" in ctx.variables else []
            else:
                lemmas = [argv] if argv else list(lang.lemmas(t))
            if kind == "any" and argv is None:
                for lemma in lemmas:
                    if lemma in lang.lemmas(t):
                        yield from nxt(pos + 1, bind(
                            pos + 1, {"_lem_" + (cap or "v"): lemma}))
                return
            for lemma in lemmas:
                if lemma in lang.verbs and lang.verb_ok(t, lemma, kind):
                    yield from nxt(pos + 1, bind(pos + 1))
                    break
            return
        if name == "N.agent":
            lemma = ctx.variables.get("v") if argv == "@v" else argv
            if t.low in set(lang.agent_nouns.get(lemma, ())):
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "NUM":
            if t.kind == "NUM":
                yield from nxt(pos + 1, bind(pos + 1))
            return
        if name == "DATE":
            yield from date_ends(pos, nxt, bind)
            return
        if name == "NUMRANGE":
            j = pos
            if T[j].low in ("about", "around", "approximately", "roughly", "over"):
                j += 1
            if j < n and T[j].kind == "NUM":
                j += 1
                if (j + 1 < n and (T[j].kind == "DASH" or T[j].low == "to")
                        and T[j + 1].kind == "NUM"):
                    j += 2
                if j < n and T[j].low in ("million", "billion", "thousand",
                                          "hundred"):
                    j += 1
                yield from nxt(j, bind(j))
            return
        if name == "QPHRASE":
            q = ctx.variables.get("q", [])
            j = pos
            ok = bool(q)
            for w in q:
                if j < n and stem(T[j].low) == stem(w):
                    j += 1
                else:
                    ok = False
                    break
            if ok:
                yield from nxt(j, bind(j))
            return
        raise PatternError("unknown element " + name)

    def date_ends(pos, nxt, bind):
        T = tokens

        def isnum(x, lo, hi):
            return (x < n and T[x].kind == "NUM" and re.fullmatch(r"\d+", T[x].text)
                    and lo <= int(T[x].text) <= hi)

        ends: list[int] = []
        if isnum(pos, 1, 31) and pos + 1 < n and T[pos + 1].low in MONTHS \
                and isnum(pos + 2, 1000, 2999):
            ends.append(pos + 3)
        if pos < n and T[pos].low in MONTHS:
            x = pos + 1
            if isnum(x, 1, 31):
                x2 = x + 1
                if x2 < n and T[x2].text == ",":
                    x2 += 1
                if isnum(x2, 1000, 2999):
                    ends.append(x2 + 1)
            if isnum(x, 1000, 2999):
                ends.append(x + 1)
        if isnum(pos, 1000, 2999):
            ends.append(pos + 1)
        for e in sorted(set(ends), reverse=True):
            yield from nxt(e, bind(e))

    def top(pos, b, trace):
        yield pos, b, trace

    out: list[dict[str, Any]] = []
    truncated = False
    positions = list(start_positions) if start_positions is not None else list(range(n))
    try:
        for alt_index, alt in enumerate(alternatives):
            for p0 in positions:
                for end, b, trace in run(alt, 0, p0, {}, [], top):
                    out.append({"binds": b, "start": p0, "end": end,
                                "alt": alt_index, "trace": trace,
                                "cost": sum(e - s for name, s, e in trace
                                            if name == "..."),
                                "truncated": False})
                    if len(out) >= limit:
                        truncated = True
                        raise _LimitReached()
    except _LimitReached:
        pass
    except _BudgetExceeded:
        truncated = True
    out.sort(key=lambda m: (m["cost"], m["start"]))
    if truncated:
        for m in out:
            m["truncated"] = True
    return out
