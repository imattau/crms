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


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


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
        self._propositions = {s.name: dict(s.proposition) for s in specs if s.proposition}
        self._pool: list[tuple[str, str]] | None = None

    def _parse(self, pattern: str) -> list:
        if pattern not in self._parsed:
            self._parsed[pattern] = parse_pattern(pattern)
        return self._parsed[pattern]

    # ------------------------------------------------------------ public API
    def ask(self, question: str, *, pool: Sequence[tuple[str, str]] | None = None,
            extra: Sequence[tuple] = (), exclude: Iterable[str] = ()
            ) -> SpecAnswer | None:
        """Answer from the first matching spec, or None. `pool` replaces
        retrieval (used by the verifier); `extra` are candidate specs tried first."""
        text = re.sub(r"\s+", " ", question.strip().rstrip("?!. "))
        language = self.language
        tokens = tokenize(text, language)
        starts = chunk(tokens, language)
        self._pool = list(pool) if pool is not None else None
        skip = set(exclude)
        try:
            specs = list(extra) + [s.as_tuple() for s in self.specs
                                   if s.name not in skip]
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
        chosen = self._choose(inst)
        if chosen is None:
            return None
        return self._render(name, template, chosen, entity, variables, text, tokens, binds)

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
            return None   # equally good, incompatible answers: abstain
        chosen = best[0]
        if p.get("veto_next_cap", 0) >= 1 and chosen["f"]["a_next_cap"] == 1:
            return None   # likely a truncated name
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
