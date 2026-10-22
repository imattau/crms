"""Relation specs executed with the pattern matcher (Phase 11).

A spec says: which question shapes it answers, which sentence shapes carry the
answer, and how to word the result. Answers are only returned when a sentence
pattern matches, so every answer carries a source sentence and a trace.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping, Protocol, Sequence

from crms_pattern_ranker import DEFAULT_PARAMS, compatible, cost, features
from crms_patterns import (
    DET, MatchContext, PatternLanguage, chunk, match_patterns, parse_pattern,
    span_text, tokenize)


@dataclass(frozen=True)
class RelationSpec:
    name: str
    priority: int
    question_patterns: tuple[str, ...]
    sentence_patterns: tuple[str, ...]
    template: str
    verb_class: str = ""
    rationale: str = ""
    origin: str = "teacher"
    status: str = "accepted"
    # How a match becomes a proposition for the generation planner: templates
    # for subject, verb, object, complement using the same placeholders as `template`.
    proposition: Mapping[str, str] = field(default_factory=dict)

    def as_tuple(self) -> tuple:
        return (self.name, self.question_patterns, self.sentence_patterns,
                self.template, self.verb_class)


@dataclass(frozen=True)
class SpecAnswer:
    answer: str
    source: str
    title: str
    spec: str
    pattern: str
    trace: tuple
    cost: float
    entity: str
    value: str
    parts: Mapping[str, str] = field(default_factory=dict)

    def proposition(self) -> dict[str, str]:
        """A source-grounded proposition for the generation planner."""
        out = {"subject": self.entity, "verb": "", "object": "",
               "complement": "", "relation": self.spec, "source": self.title,
               "span": self.value, "value": self.value, "source_text": self.source}
        out.update({k: v for k, v in self.parts.items() if v})
        return out


class SentenceSource(Protocol):
    synthetic: set[str]

    def sentences(self, entity: str, question: str) -> Iterable[tuple[str, str]]:
        """Candidate (title, sentence) pairs for an entity."""


class ListSentenceSource:
    """A fixed pool of (title, sentence) pairs; used by intake, tests, and the verifier."""

    def __init__(self, pairs: Sequence[tuple[str, str]]) -> None:
        self.pairs = list(pairs)
        self.synthetic: set[str] = set()

    def sentences(self, entity: str, question: str) -> Iterable[tuple[str, str]]:
        return list(self.pairs)


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def _extended_title(candidate: dict) -> bool:
    """True when the source page's title extends the entity ("Citibank Nigeria"
    for "Citibank"): the sentence may be about the more specific thing."""
    title = _norm(re.sub(r"\s*\([^)]*\)\s*$", "", candidate["title"]))
    entity = _norm(candidate["etxt"])
    return bool(entity) and title != entity and entity in title


class RelationEngine:
    def __init__(self, language: PatternLanguage,
                 specs: Sequence[RelationSpec],
                 source: SentenceSource | None = None,
                 params: Mapping[str, float] | None = None) -> None:
        self.language = language
        self.specs = sorted((s for s in specs if s.status == "accepted"),
                            key=lambda s: (s.priority, s.name))
        self.source = source
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self._parsed: dict[str, list] = {}
        self.allowed: set[str] | None = None   # active spec names from the registry; None = all
        self._propositions = {s.name: dict(s.proposition) for s in specs if s.proposition}
        self._pool: list[tuple[str, str]] | None = None
        self._alts: list[dict] = []
        self._tie: list[dict] = []          # incompatible best candidates of the last choice
        self._conflicts: list[SpecAnswer] = []

    def _parse(self, pattern: str) -> list:
        if pattern not in self._parsed:
            self._parsed[pattern] = parse_pattern(pattern)
        return self._parsed[pattern]

    # ------------------------------------------------------------ public API
    def ask(self, question: str, *, pool: Sequence[tuple[str, str]] | None = None,
            extra: Sequence[tuple] = (), exclude: Iterable[str] = (),
            conflicts: list | None = None) -> SpecAnswer | None:
        """Answer from the first matching spec, or None. `pool` replaces
        retrieval (used by the verifier); `extra` are candidate specs tried first.
        When `conflicts` is a list and sources disagree, one answer per side is
        appended, each with its own source. The engine's own result is unchanged:
        an equal-cost tie still abstains, and otherwise the best answer is
        returned, so the report never alters the accuracy the oracle measures."""
        self._conflicts = []
        text = re.sub(r"\s+", " ", question.strip().rstrip("?!. "))
        language = self.language
        tokens = tokenize(text, language)
        starts = chunk(tokens, language)
        self._pool = list(pool) if pool is not None else None
        skip = set(exclude)
        try:
            specs = list(extra) + [s.as_tuple() for s in self.specs
                                   if s.name not in skip
                                   and (self.allowed is None or s.name in self.allowed)]
            for name, qpats, spats, template, verb_class in specs:
                for qp in qpats:
                    for m in match_patterns(self._parse(qp),
                                            MatchContext(language, tokens, starts),
                                            start_positions=[0]):
                        if m["end"] != len(tokens):
                            continue
                        result = self._apply(name, spats, template, verb_class,
                                             text, tokens, m["binds"], question)
                        if result is not None:
                            return result
        finally:
            self._pool = None
            if conflicts is not None:
                conflicts.extend(self._conflicts)
        return None

    def instances(self, question: str) -> tuple[str, list[dict]] | None:
        """Candidate instances (with features) of the first spec that has any;
        used by oracle evaluation and ranking studies."""
        text = re.sub(r"\s+", " ", question.strip().rstrip("?!. "))
        tokens = tokenize(text, self.language)
        starts = chunk(tokens, self.language)
        for s in self.specs:
            for qp in s.question_patterns:
                for m in match_patterns(self._parse(qp),
                                        MatchContext(self.language, tokens, starts),
                                        start_positions=[0]):
                    if m["end"] != len(tokens):
                        continue
                    prepared = self._prepare(s.verb_class, text, tokens, m["binds"])
                    if prepared is None:
                        continue
                    entity, etoks, variables = prepared
                    inst = self._gather(s.sentence_patterns, entity, etoks, variables, question)
                    if inst:
                        return s.name, inst
        return None

    def pool_for(self, question: str) -> tuple[str, list[tuple[str, str]]] | None:
        """(entity, retrieved sentences) for the first spec whose question pattern
        matches, or None when no question pattern matches. Used to explain a miss."""
        text = " ".join(question.strip().rstrip("?!. ").split())
        tokens = tokenize(text, self.language)
        starts = chunk(tokens, self.language)
        for s in self.specs:
            for qp in s.question_patterns:
                for m in match_patterns(self._parse(qp),
                                        MatchContext(self.language, tokens, starts),
                                        start_positions=[0]):
                    if m["end"] != len(tokens):
                        continue
                    prepared = self._prepare(s.verb_class, text, tokens, m["binds"])
                    if prepared is None:
                        continue
                    words = prepared[0].split()
                    if len(words) > 1 and words[0].lower() in ("the", "a", "an"):
                        words = words[1:]
                    entity = " ".join(words)
                    pool = list(self.source.sentences(entity, question)) if self.source else []
                    return entity, pool
        return None

    # ------------------------------------------------------------- internals
    def _prepare(self, verb_class: str, text: str, tokens, binds):
        language = self.language
        if "E" in binds:
            entity = span_text(text, tokens, binds, "E")
        elif "q" in binds:
            entity = span_text(text, tokens, binds, "q")
        else:
            return None
        if not entity:
            return None
        etoks = ([t.low for t in tokenize(entity, language)] if "E" in binds else [])
        while etoks and etoks[0] in ("the", "a", "an"):
            etoks = etoks[1:]
        variables: dict[str, Any] = {}
        for key, value in binds.items():
            if key.startswith("_lem_"):
                variables[key[5:]] = value
        if "q" in binds:
            variables["q"] = [t.low for t in tokens[binds["q"][0]:binds["q"][1]]
                              if t.low not in DET]
        if verb_class and variables.get("v") not in language.classes.get(verb_class, {}):
            return None
        return entity, etoks, variables

    def _apply(self, name, spats, template, verb_class, text, tokens, binds, question):
        prepared = self._prepare(verb_class, text, tokens, binds)
        if prepared is None:
            return None
        entity, etoks, variables = prepared
        inst = self._gather(spats, entity, etoks, variables, question)
        if not inst:
            return None
        self._tie = []
        self._alts = []
        chosen = self._choose(inst)
        if chosen is None:
            if self._tie and not self._conflicts:
                self._conflicts = [self._render(name, template, c, entity, variables,
                                                text, tokens, binds) for c in self._tie]
            return None
        answer = self._render(name, template, chosen, entity, variables, text, tokens, binds)
        if self._alts and not self._conflicts:
            self._conflicts = [answer] + [
                self._render(name, template, c, entity, variables, text, tokens, binds)
                for c in self._alts]
        return answer

    def _gather(self, spats, entity, etoks, variables, question) -> list[dict]:
        language = self.language
        etxt = re.sub(r"^(?:the|a|an)\s+", "", " ".join(entity.split()), flags=re.I)
        if self._pool is not None:
            source = self._pool
        elif self.source is not None:
            source = list(self.source.sentences(etxt, question))
        else:
            source = []
        synthetic = getattr(self.source, "synthetic", set()) if self.source else set()
        seen: set[str] = set()
        pool: list[tuple[str, str]] = []
        for title, sentence in source:
            if sentence not in seen:
                seen.add(sentence)
                pool.append((title, sentence))
        inst: list[dict] = []
        for index, (title, sentence) in enumerate(pool[:400]):
            toks = tokenize(sentence, language)
            starts = chunk(toks, language)
            ctx = MatchContext(language, toks, starts, etoks, variables)
            for si, pattern in enumerate(spats):
                for m in match_patterns(self._parse(pattern), ctx):
                    b = m["binds"]
                    if "A" not in b:
                        continue
                    a = span_text(sentence, toks, b, "A")
                    na, ne = _norm(a), _norm(etxt)
                    if na and ne and (na == ne or ne in na):
                        continue   # the "answer" is the entity itself (a part of the entity is fine: Dacia / Dacia Spring)
                    inst.append({"title": title, "S": sentence, "st": toks, "m": m,
                                 "sp": pattern, "si": si, "pi": index, "A": a,
                                 "etxt": etxt, "nA": _norm(a),
                                 "synth": sentence in synthetic})
        for c in inst:
            consensus = len({d["S"] for d in inst if d["nA"] == c["nA"]})
            ai, aj = c["m"]["binds"]["A"]
            c["f"] = features(
                gap=c["m"]["cost"], alt=c["si"], pattern=c["sp"],
                start=c["m"]["start"], title=c["title"], entity=etxt,
                pool_index=c["pi"], answer=c["A"], sentence=c["S"],
                synthetic=c["synth"],
                at_start=c["m"]["start"] <= 1 and c["sp"].startswith("E "),
                consensus=consensus, answer_tokens=c["st"][ai:aj],
                next_token=c["st"][aj] if aj < len(c["st"]) else None)
        return inst

    def _choose(self, inst: list[dict]) -> dict | None:
        p = self.params
        for c in inst:
            c["cost"] = cost(c["f"], p)
        ranked = sorted(inst, key=lambda c: c["cost"])
        top = ranked[0]["nA"]
        window = p["rk_window"]
        compat = [c for c in ranked
                  if c["cost"] <= ranked[0]["cost"] + window
                  and (c["nA"] in top or top in c["nA"])]
        if len(compat) > 1:   # prefer the most specific compatible answer
            ranked.insert(0, max(compat, key=lambda c: len(c["nA"])))
        best = [c for c in ranked if c["cost"] == ranked[0]["cost"]]
        answers = {c["nA"] for c in best}
        if len(answers) > 1 and not any(
                a in o for a in answers for o in answers if a != o):
            seen_answers: set[str] = set()
            for c in best:                       # one candidate per distinct answer
                if c["nA"] not in seen_answers:
                    seen_answers.add(c["nA"])
                    self._tie.append(c)
            return None   # equally good, incompatible answers: abstain
        chosen = best[0]
        self._alts = []
        window2 = p.get("conflict_window", 2.0)
        for c in ranked[1:]:
            if (c["cost"] <= chosen["cost"] + window2 and c["S"] != chosen["S"]
                    and not (c["nA"] in chosen["nA"] or chosen["nA"] in c["nA"])
                    and all(not (c["nA"] in a["nA"] or a["nA"] in c["nA"])
                            for a in self._alts)):
                self._alts.append(c)
        if p.get("veto_next_cap", 0) >= 1 and chosen["f"]["a_next_cap"] == 1:
            return None   # likely a truncated name
        if p.get("veto_extended_title", 0) >= 1 and _extended_title(chosen):
            return None   # the sentence is from a page about a more specific entity
        return chosen

    def _render(self, name, template, c, entity, variables, text, tokens, qb) -> SpecAnswer:
        proposition = self._propositions.get(name, {})
        language = self.language
        sentence, st, m = c["S"], c["st"], c["m"]
        b = m["binds"]

        def cap(n: str) -> str:
            return span_text(sentence, st, b, n)

        lemma = variables.get("v")
        forms = language.forms(lemma) if lemma in language.verbs else None
        particle = (" " + span_text(text, tokens, qb, "prt")) if "prt" in qb else ""
        shown = " ".join(entity.split())
        a_b = cap("A")
        if "B" in b and b["B"][1] > b["B"][0] and b["A"][1] <= b["B"][0]:
            a_b += " " + sentence[st[b["A"][1]].start:st[b["B"][1] - 1].end]
        verb_q = span_text(text, tokens, qb, "v") if "v" in qb else ""
        copula = span_text(text, tokens, qb, "cop") if "cop" in qb else "is"
        if forms and verb_q.lower() == forms["s3"] and re.search(r"\band\b", cap("A")):
            verb_q = forms["base"]   # plural subject: owns -> own
        extra = span_text(text, tokens, qb, "X") if "X" in qb else ""
        def fill(pattern: str) -> str:
            text_ = (pattern.replace("{X}", (" " + extra) if extra else "")
                     .replace("{p}", cap("p") if "p" in b else "")
                     .replace("{v.q}", verb_q).replace("{cop}", copula)
                     .replace("{A_B}", a_b).replace("{A}", cap("A"))
                     .replace("{E}", shown).replace("{prt}", particle))
            for key in ("W", "q"):
                if "{" + key + "}" in text_:
                    text_ = text_.replace("{" + key + "}", cap(key) if key in b
                                          else " ".join(variables.get("q", [])))
            if forms:
                text_ = (text_.replace("{v.past}", forms["past"])
                         .replace("{v.part}", forms["part"])
                         .replace("{v.base}", forms["base"]))
            return " ".join(text_.split())

        out = fill(template)
        out = out[:1].upper() + out[1:]
        parts = {k: fill(v) for k, v in proposition.items()}
        trace = tuple((n, tuple(t.text for t in st[s:e]))
                      for n, s, e in m["trace"] if n != "...")
        return SpecAnswer(answer=out, source=sentence, title=c["title"], spec=name,
                          pattern=c["sp"], trace=trace, cost=c["f"]["gap"],
                          entity=shown, value=cap("A"), parts=parts)
