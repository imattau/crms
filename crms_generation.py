"""Rule-only generation for the Phase 10 vertical slice.

This module implements the first four layers of the Phase 10 stack:

    request -> content plan -> discourse plan -> sentence plan -> realizer
            -> clarity pass -> critic/search

It is deliberately deterministic and contains no model weights, no LLM call,
and no network dependency. Facts are structured propositions with source
spans. The realizer composes clauses from those propositions; it does not emit
stored whole-source sentences.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from crms_generation_rules import (
    GenerationRuleError, GenerationRules, MoveRule, load_rules,
)

PROJECT_RULES = None
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]*")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_STOP = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "it", "this", "that",
    "these", "those", "as", "at", "by", "from", "into", "than", "then",
    "that", "which", "who", "whom", "whose", "what", "why", "how", "when",
    "where", "can", "could", "may", "might", "must", "should", "would",
    "will", "do", "does", "did", "not", "no", "but", "if", "so", "because",
}


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _WORD.findall(text)]


def _content_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) if token not in _STOP}


def _normalize_space(text: str) -> str:
    return " ".join(str(text).split())


def _clean_sentence(text: str) -> str:
    text = _normalize_space(text).strip()
    text = text.rstrip(" ,;:")
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return _upper_first(text)


def _lower_first(text: str) -> str:
    if not text:
        return text
    return text[0].lower() + text[1:]


def _upper_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


@dataclass(frozen=True)
class Fact:
    """A source-grounded proposition, not a sentence to quote."""

    fact_id: str
    subject: str
    verb: str
    object: str = ""
    complement: str = ""
    role: str = "claim"
    source: str = ""
    span: str = ""
    order: int = 0
    source_text: str = ""
    tags: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.fact_id.strip():
            raise ValueError("fact_id is required")
        if not self.subject.strip() and not self.verb.strip():
            raise ValueError(f"fact {self.fact_id!r} has no proposition")
        if not self.role.strip():
            raise ValueError(f"fact {self.fact_id!r} has no role")
        if not self.source.strip() and not self.source_text.strip():
            raise ValueError(
                f"fact {self.fact_id!r} has no source or source_text")

    def clause(self) -> "Clause":
        return Clause(
            subject=self.subject,
            verb=self.verb,
            object=self.object,
            complement=self.complement,
            fact_id=self.fact_id,
            source=self.source,
            span=self.span,
        )


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    genre: str
    facts: tuple[Fact, ...]
    audience: str = "general"
    style: str = "plain"
    max_sentences: int = 10
    source_documents: tuple[tuple[str, str], ...] = ()

    def validate(self) -> None:
        if not self.prompt.strip():
            raise ValueError("generation prompt is empty")
        if not self.genre.strip():
            raise ValueError("generation genre is empty")
        if self.max_sentences < 1:
            raise ValueError("max_sentences must be positive")
        for fact in self.facts:
            fact.validate()

    def source_text(self) -> str:
        if self.source_documents:
            return "\n\n".join(text for _name, text in self.source_documents)
        return "\n".join(fact.source_text for fact in self.facts
                         if fact.source_text)


@dataclass(frozen=True)
class Clause:
    subject: str
    verb: str
    object: str = ""
    complement: str = ""
    fact_id: str = ""
    source: str = ""
    span: str = ""

    def tokens(self) -> tuple[str, ...]:
        return tuple(_tokens(" ".join(
            part for part in (self.subject, self.verb, self.object,
                              self.complement) if part)))


@dataclass(frozen=True)
class SectionPlan:
    move: str
    facts: tuple[Fact, ...]
    required: bool = False
    transition: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "move": self.move,
            "required": self.required,
            "transition": self.transition,
            "facts": [fact.fact_id for fact in self.facts],
        }


@dataclass(frozen=True)
class ContentPlan:
    genre: str
    sections: tuple[SectionPlan, ...]
    missing: tuple[str, ...] = ()
    status: str = "ok"
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "status": self.status,
            "missing": list(self.missing),
            "notes": list(self.notes),
            "sections": [section.as_dict() for section in self.sections],
        }


@dataclass(frozen=True)
class DiscoursePlan:
    paragraphs: tuple[tuple[SectionPlan, ...], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "paragraphs": [
                [section.as_dict() for section in paragraph]
                for paragraph in self.paragraphs
            ]
        }


@dataclass(frozen=True)
class SentencePlan:
    relation: str
    main: Clause | None
    subordinate: Clause | None = None
    transition: str | None = None
    fact_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "transition": self.transition,
            "fact_ids": list(self.fact_ids),
            "main": _clause_dict(self.main),
            "subordinate": _clause_dict(self.subordinate),
        }


def _clause_dict(clause: Clause | None) -> dict[str, Any] | None:
    if clause is None:
        return None
    return {
        "subject": clause.subject,
        "verb": clause.verb,
        "object": clause.object,
        "complement": clause.complement,
        "fact_id": clause.fact_id,
        "source": clause.source,
        "span": clause.span,
    }


@dataclass(frozen=True)
class Critique:
    passed: bool
    score: float
    coverage: float
    evidence_valid: bool
    copy_ratio: float
    sentence_count: int
    paragraph_count: int
    multi_fact_sentences: int
    avg_sentence_words: float
    max_sentence_words: int
    issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 4),
            "coverage": round(self.coverage, 4),
            "evidence_valid": self.evidence_valid,
            "copy_ratio": round(self.copy_ratio, 4),
            "sentence_count": self.sentence_count,
            "paragraph_count": self.paragraph_count,
            "multi_fact_sentences": self.multi_fact_sentences,
            "avg_sentence_words": round(self.avg_sentence_words, 2),
            "max_sentence_words": self.max_sentence_words,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class GenerationResult:
    status: str
    text: str
    genre: str
    style: str
    content_plan: ContentPlan
    discourse_plan: DiscoursePlan | None
    sentence_plans: tuple[SentencePlan, ...]
    evidence: tuple[dict[str, Any], ...]
    critique: Critique | None
    candidate_scores: tuple[dict[str, Any], ...]
    rule_digest: str
    warnings: tuple[str, ...] = ()
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "text": self.text,
            "genre": self.genre,
            "style": self.style,
            "rule_digest": self.rule_digest,
            "content_plan": self.content_plan.as_dict(),
            "discourse_plan": (self.discourse_plan.as_dict()
                               if self.discourse_plan else None),
            "sentence_plans": [plan.as_dict()
                               for plan in self.sentence_plans],
            "evidence": list(self.evidence),
            "critique": (self.critique.as_dict()
                         if self.critique else None),
            "candidate_scores": list(self.candidate_scores),
            "warnings": list(self.warnings),
        }


def _fact_rank(fact: Fact, prompt_tokens: set[str]) -> tuple[int, int, str]:
    overlap = len(_content_tokens(
        " ".join((fact.subject, fact.verb, fact.object, fact.complement,
                  fact.role, " ".join(fact.tags)))) & prompt_tokens)
    role_bonus = 1 if fact.role in {"answer", "claim", "summary"} else 0
    return (-overlap, -role_bonus, fact.fact_id)


class ContentPlanner:
    """Select propositions for each rhetorical move."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules

    def plan(self, request: GenerationRequest) -> ContentPlan:
        genre = self.rules.genre(request.genre)
        prompt_tokens = _content_tokens(request.prompt)
        available = list(request.facts)
        used: set[str] = set()
        sections: list[SectionPlan] = []
        missing: list[str] = []

        for move in genre.moves:
            candidates = [fact for fact in available
                          if fact.fact_id not in used
                          and fact.role in move.roles]
            if move.name == "steps":
                candidates.sort(key=lambda fact: (
                    fact.order, fact.fact_id))
            else:
                candidates.sort(key=lambda fact: (
                    fact.order, _fact_rank(fact, prompt_tokens)))

            selected: list[Fact] = []
            for role in move.roles:
                if len(selected) >= move.max_facts:
                    break
                pool = [fact for fact in candidates
                        if fact.role == role
                        and fact.fact_id not in {item.fact_id
                                                for item in selected}]
                if pool:
                    selected.append(pool[0])
            for fact in candidates:
                if len(selected) >= move.max_facts:
                    break
                if fact.fact_id not in {item.fact_id for item in selected}:
                    selected.append(fact)

            if selected:
                for fact in selected:
                    used.add(fact.fact_id)
                sections.append(SectionPlan(
                    move=move.name,
                    facts=tuple(selected),
                    required=move.required,
                    transition=move.transition,
                ))
            elif move.required:
                missing.append(move.name)

        if not request.facts:
            return ContentPlan(
                genre=request.genre, sections=(), missing=("facts",),
                status="abstain",
                notes=("No source propositions were supplied.",))
        if missing:
            return ContentPlan(
                genre=request.genre, sections=tuple(sections),
                missing=tuple(missing), status="clarify",
                notes=(f"Missing required move(s): {', '.join(missing)}.",))
        return ContentPlan(
            genre=request.genre, sections=tuple(sections), status="ok",
            notes=("Every required move has at least one proposition.",))


class DiscoursePlanner:
    """Group sections into paragraphs and attach schema transitions."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules

    def plan(self, request: GenerationRequest,
             content: ContentPlan) -> DiscoursePlan:
        genre = self.rules.genre(request.genre)
        breaks = set(genre.paragraph_breaks_after)
        style = self.rules.style(request.style)
        include_transitions = bool(style.get("include_transitions", True))
        paragraphs: list[list[SectionPlan]] = []
        current: list[SectionPlan] = []

        for section in content.sections:
            transition = section.transition if include_transitions else None
            if transition and section.move == "pitfall":
                transition = self.rules.transition("remember")
            elif transition and section.move in {"caveat", "counterpoint",
                                                  "qualification"}:
                transition = self.rules.transition("caveat")
            elif transition and section.move == "summary":
                transition = self.rules.transition("summary")
            elif transition and section.move == "recommendation":
                transition = self.rules.transition("recommendation")
            item = SectionPlan(
                move=section.move, facts=section.facts,
                required=section.required, transition=transition)
            current.append(item)
            if section.move in breaks:
                paragraphs.append(current)
                current = []
        if current:
            paragraphs.append(current)
        return DiscoursePlan(paragraphs=tuple(tuple(row) for row in paragraphs))


_IRREGULAR = {
    "be": ("is", "are"),
    "have": ("has", "have"),
    "do": ("does", "do"),
    "go": ("goes", "go"),
}


def _plural_subject(subject: str) -> bool:
    lowered = subject.casefold().strip()
    if not lowered:
        return False
    if lowered in {"they", "we", "you", "these", "those", "people",
                   "children", "data"}:
        return True
    if " and " in f" {lowered} ":
        return True
    if lowered.endswith("s") and not lowered.endswith(("ss", "us", "is")):
        return True
    return False


def _conjugate(verb: str, subject: str) -> str:
    verb = _normalize_space(verb)
    if not verb:
        return verb
    if not subject.strip():
        return verb
    if verb.startswith("do not "):
        return verb
    first = verb.split()[0].casefold()
    if first in {"can", "could", "may", "might", "must", "should", "shall",
                 "will", "would"}:
        return verb
    if first.endswith("ed") or first in {
            "was", "were", "had", "did", "found", "began", "went", "said",
            "made", "took", "saw", "came", "gave", "told", "thought", "knew",
            "got", "became", "left", "felt", "put", "brought", "kept", "held",
            "wrote", "stood", "heard", "let", "meant", "set", "met", "ran",
            "paid", "sat", "spoke", "lay", "led", "read", "grew", "lost",
            "fell", "sent", "built", "understood", "drew", "broke", "spent",
            "cut", "rose", "drove", "bought", "wore", "chose", "ate",
            "drank", "sang", "swam", "flew"}:
        return verb
    rest = verb[len(verb.split()[0]):]
    irregular = _IRREGULAR.get(first)
    if irregular is not None:
        return (irregular[1] if _plural_subject(subject) else irregular[0]) + rest
    if _plural_subject(subject):
        return verb
    if first.endswith("s") and not first.endswith("ss"):
        return verb
    if first.endswith(("ch", "sh", "x", "z", "o")):
        return first + "es" + rest
    if first.endswith("y") and len(first) > 1 and first[-2] not in "aeiou":
        return first[:-1] + "ies" + rest
    return first + "s" + rest


class Realizer:
    """Realize clauses and sentence plans with visible constructions."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules

    def clause_text(self, clause: Clause) -> str:
        subject = _normalize_space(clause.subject)
        verb = _normalize_space(clause.verb)
        obj = _normalize_space(clause.object)
        complement = _normalize_space(clause.complement)
        if not subject:
            parts = [verb, obj, complement]
            return _clean_sentence(" ".join(part for part in parts if part))
        verb_text = _conjugate(verb, subject)
        parts = [subject, verb_text, obj, complement]
        return _clean_sentence(" ".join(part for part in parts if part))

    def sentence_text(self, plan: SentencePlan) -> str:
        if plan.main is None:
            return ""
        main = self.clause_text(plan.main)
        subordinate = (self.clause_text(plan.subordinate)
                       if plan.subordinate else "")
        relation = plan.relation
        if relation == "definition":
            sentence = main
        elif relation == "cause" and subordinate:
            sentence = self.rules.construction("cause").format(
                subordinate=_lower_first(subordinate.rstrip(".")),
                main=_lower_first(main.rstrip(".")),
            )
        elif relation == "result" and subordinate:
            sentence = self.rules.construction("result").format(
                main=main.rstrip("."),
                subordinate=_lower_first(subordinate.rstrip(".")),
            )
        elif relation == "contrast" and subordinate:
            sentence = self.rules.construction("contrast").format(
                main=main.rstrip("."),
                subordinate=_lower_first(subordinate.rstrip(".")),
            )
        elif relation == "example" and subordinate:
            sentence = self.rules.construction("example").format(
                main=main.rstrip("."),
                subordinate=_lower_first(subordinate.rstrip(".")),
            )
        elif relation == "sequence" and plan.transition:
            sentence = self.rules.construction("sequence").format(
                transition=plan.transition,
                main=_lower_first(main.rstrip(".")),
            )
        elif relation == "qualification":
            sentence = self.rules.construction("qualification").format(
                main=_lower_first(main.rstrip(".")),
            )
        else:
            sentence = self.rules.construction("elaboration").format(
                main=main.rstrip("."),
            )
        if plan.transition and relation not in {"sequence", "qualification"}:
            sentence = f"{plan.transition}, {_lower_first(sentence)}"
        return _clean_sentence(sentence)

    def render(self, plans: Sequence[SentencePlan],
               discourse: DiscoursePlan) -> str:
        plan_rows = list(plans)
        used: set[int] = set()
        paragraphs: list[str] = []
        for paragraph in discourse.paragraphs:
            sentences: list[str] = []
            for section in paragraph:
                fact_ids = {fact.fact_id for fact in section.facts}
                for index, plan in enumerate(plan_rows):
                    if index in used:
                        continue
                    if fact_ids.intersection(plan.fact_ids):
                        sentence = self.sentence_text(plan)
                        if sentence:
                            sentences.append(sentence)
                        used.add(index)
            if sentences:
                paragraphs.append(" ".join(sentences))
        return "\n\n".join(paragraphs)


class SentencePlanner:
    """Turn sections into sentence plans; fuse paired propositions."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules

    def plan(self, request: GenerationRequest,
             discourse: DiscoursePlan) -> tuple[SentencePlan, ...]:
        style = self.rules.style(request.style)
        fuse = bool(style.get("fuse", True))
        plans: list[SentencePlan] = []
        for paragraph in discourse.paragraphs:
            for section in paragraph:
                if section.move == "cause_effect" and fuse:
                    cause = next((fact for fact in section.facts
                                  if fact.role == "cause"), None)
                    consequence = next(
                        (fact for fact in section.facts
                         if fact.role == "consequence"), None)
                    if cause is not None and consequence is not None:
                        plans.append(SentencePlan(
                            relation="cause",
                            main=consequence.clause(),
                            subordinate=cause.clause(),
                            transition=section.transition,
                            fact_ids=(cause.fact_id, consequence.fact_id),
                        ))
                        continue
                if section.move == "contrast" and fuse:
                    left = next((fact for fact in section.facts
                                 if fact.role == "limitation_a"), None)
                    right = next((fact for fact in section.facts
                                  if fact.role == "limitation_b"), None)
                    if left is not None and right is not None:
                        plans.append(SentencePlan(
                            relation="contrast",
                            main=left.clause(),
                            subordinate=right.clause(),
                            transition=section.transition,
                            fact_ids=(left.fact_id, right.fact_id),
                        ))
                        continue
                steps = [fact for fact in section.facts
                         if fact.role in {"step", "procedure"}]
                if steps and section.move in {"steps", "procedure"}:
                    for index, fact in enumerate(steps):
                        if len(steps) == 1:
                            transition = None
                        elif index == 0:
                            transition = self.rules.transition("first")
                        elif index == len(steps) - 1:
                            transition = self.rules.transition("finally")
                        else:
                            transition = self.rules.transition("then")
                        plans.append(SentencePlan(
                            relation="sequence",
                            main=fact.clause(),
                            transition=transition,
                            fact_ids=(fact.fact_id,),
                        ))
                    continue
                for index, fact in enumerate(section.facts):
                    relation = "definition" if fact.role == "definition" else "elaboration"
                    transition = section.transition if index == 0 else None
                    if fact.role == "example" and not transition:
                        transition = self.rules.transition("example")
                    plans.append(SentencePlan(
                        relation=relation,
                        main=fact.clause(),
                        transition=transition,
                        fact_ids=(fact.fact_id,),
                    ))
        return tuple(plans)


class ClarityRewriter:
    """Apply visible clarity substitutions and sentence-length checks."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules
        self.replacements = {
            str(source): str(target)
            for source, target in rules.clarity.get("replacements", {}).items()
        }
        self.jargon = tuple(str(item) for item in
                            rules.clarity.get("jargon_terms", ()))
        self.max_words = int(rules.clarity.get("max_sentence_words", 32))
        # Phase 11: matching runs over tokens (whole words, every verb inflection,
        # capitalisation kept) instead of regex substitution.
        from crms_pattern_defaults import seeded_resources
        from crms_pattern_rewrite import PatternRewriter, Rewrite
        language, _specs, _params, seeded = seeded_resources()
        listed = {("phrase", source.casefold()) for source in self.replacements}
        extra = [r for r in seeded if (r.kind, r.source.casefold()) not in listed]
        self.pattern_rewriter = PatternRewriter(
            language,
            [Rewrite("phrase", source, target)
             for source, target in self.replacements.items()] + extra)

    def rewrite(self, text: str, request: GenerationRequest
                ) -> tuple[str, tuple[str, ...]]:
        issues: list[str] = []
        style_max = int(self.rules.style(request.style).get(
            "max_sentence_words", self.max_words))
        paragraphs: list[str] = []
        for paragraph in text.split("\n\n"):
            rewritten = _normalize_space(paragraph)
            rewritten = self.pattern_rewriter.rewrite(rewritten)
            sentences = [item for item in _SENTENCE.split(rewritten) if item]
            output: list[str] = []
            for sentence in sentences:
                words = _tokens(sentence)
                if len(words) > style_max and ", and " in sentence:
                    left, right = sentence.split(", and ", 1)
                    output.append(_clean_sentence(_upper_first(left)))
                    output.append(_clean_sentence(_upper_first(right)))
                else:
                    output.append(_clean_sentence(sentence))
            for sentence in output:
                if len(_tokens(sentence)) > style_max:
                    issues.append(
                        f"long sentence ({len(_tokens(sentence))} words): "
                        f"{sentence[:80]}")
            if output:
                paragraphs.append(" ".join(output))
        rewritten_all = " ".join(paragraphs)
        for term in self.jargon:
            if self.pattern_rewriter.contains(rewritten_all, term):
                issues.append(f"uncleared jargon: {term}")
        return "\n\n".join(paragraphs), tuple(issues)


def _ngrams(tokens: Sequence[str], size: int) -> list[tuple[str, ...]]:
    if len(tokens) < size:
        return [tuple(tokens)] if tokens else []
    return [tuple(tokens[index:index + size])
            for index in range(0, len(tokens) - size + 1)]


def copy_ratio(text: str, sources: Iterable[str], *, size: int = 5) -> float:
    """Share of answer n-grams found in one verbatim source run."""
    answer = _tokens(text)
    if not answer:
        return 0.0
    source_ngrams: set[tuple[str, ...]] = set()
    for source in sources:
        source_ngrams.update(_ngrams(_tokens(source), size))
    answer_ngrams = _ngrams(answer, size)
    if not answer_ngrams:
        return 0.0
    matched = sum(1 for gram in answer_ngrams if gram in source_ngrams)
    return matched / len(answer_ngrams)


class Critic:
    """Deterministic quality checks for the first generation slice."""

    def __init__(self, rules: GenerationRules) -> None:
        self.rules = rules

    def critique(self, text: str, request: GenerationRequest,
                 content: ContentPlan, plans: Sequence[SentencePlan]) -> Critique:
        required = [section for section in content.sections
                    if section.required]
        missing = [move for move in content.missing]
        coverage = 1.0 if not required else (
            sum(1 for section in required if section.facts) / len(required))
        evidence_valid = all(plan.fact_ids for plan in plans)
        sources = [doc_text for _name, doc_text in request.source_documents]
        if not sources:
            sources = [fact.source_text for fact in request.facts
                       if fact.source_text]
        copy = copy_ratio(text, sources)
        sentences = [item for item in _SENTENCE.split(text) if item.strip()]
        counts = [len(_tokens(sentence)) for sentence in sentences]
        paragraphs = [part for part in text.split("\n\n") if part.strip()]
        multi_fact = sum(1 for plan in plans if len(plan.fact_ids) >= 2)
        max_words = max(counts) if counts else 0
        avg_words = (sum(counts) / len(counts)) if counts else 0.0
        issues: list[str] = []
        if missing:
            issues.append(f"missing required moves: {', '.join(missing)}")
        if not evidence_valid:
            issues.append("one or more sentences have no evidence id")
        if len(sentences) < 3:
            issues.append("fewer than three sentences")
        if max_words > int(self.rules.clarity.get("max_sentence_words", 32)):
            issues.append(f"max sentence words {max_words} exceeds limit")
        if avg_words > float(self.rules.clarity.get(
                "max_average_sentence_words", 24)):
            issues.append(f"average sentence words {avg_words:.1f} exceeds limit")
        if copy > 0.75:
            issues.append(f"copy ratio {copy:.2f} exceeds first-slice limit")
        from crms_generation_checks import check_generated
        from crms_pattern_defaults import seeded_resources
        issues.extend(check_generated(text, request.facts, seeded_resources()[0],
                                      sources))
        passed = not issues
        score = (
            coverage * 0.45
            + (1.0 if evidence_valid else 0.0) * 0.2
            + max(0.0, 1.0 - copy) * 0.15
            + (1.0 if len(sentences) >= 3 else 0.0) * 0.1
            + (1.0 if multi_fact else 0.0) * 0.1
        )
        return Critique(
            passed=passed,
            score=score,
            coverage=coverage,
            evidence_valid=evidence_valid,
            copy_ratio=copy,
            sentence_count=len(sentences),
            paragraph_count=len(paragraphs),
            multi_fact_sentences=multi_fact,
            avg_sentence_words=avg_words,
            max_sentence_words=max_words,
            issues=tuple(issues),
        )


class GenerationEngine:
    """Compose the rule-only generation stack."""

    def __init__(self, rules: GenerationRules | None = None) -> None:
        self.rules = rules or load_rules()
        self.content = ContentPlanner(self.rules)
        self.discourse = DiscoursePlanner(self.rules)
        self.sentences = SentencePlanner(self.rules)
        self.realizer = Realizer(self.rules)
        self.clarity = ClarityRewriter(self.rules)
        self.critic = Critic(self.rules)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        request.validate()
        content = self.content.plan(request)
        if content.status != "ok":
            return GenerationResult(
                status=content.status,
                text="",
                genre=request.genre,
                style=request.style,
                content_plan=content,
                discourse_plan=None,
                sentence_plans=(),
                evidence=(),
                critique=None,
                candidate_scores=(),
                rule_digest=self.rules.digest,
                warnings=content.notes,
                message=content.notes[0] if content.notes else "",
            )

        styles = [request.style, "plain", "explanatory", "concise"]
        seen_styles: list[str] = []
        for style in styles:
            if style not in seen_styles and style in self.rules.styles:
                seen_styles.append(style)
        candidates: list[tuple[float, int, GenerationResult]] = []
        for index, style in enumerate(seen_styles):
            style_request = GenerationRequest(
                prompt=request.prompt, genre=request.genre,
                facts=request.facts, audience=request.audience,
                style=style, max_sentences=request.max_sentences,
                source_documents=request.source_documents,
            )
            discourse = self.discourse.plan(style_request, content)
            sentence_plans = self.sentences.plan(style_request, discourse)
            text = self.realizer.render(sentence_plans, discourse)
            text, clarity_issues = self.clarity.rewrite(text, style_request)
            if sentence_plans:
                critique = self.critic.critique(
                    text, style_request, content, sentence_plans)
                if clarity_issues:
                    critique = Critique(
                        passed=False,
                        score=max(0.0, critique.score - 0.1),
                        coverage=critique.coverage,
                        evidence_valid=critique.evidence_valid,
                        copy_ratio=critique.copy_ratio,
                        sentence_count=critique.sentence_count,
                        paragraph_count=critique.paragraph_count,
                        multi_fact_sentences=critique.multi_fact_sentences,
                        avg_sentence_words=critique.avg_sentence_words,
                        max_sentence_words=critique.max_sentence_words,
                        issues=critique.issues + clarity_issues,
                    )
            else:
                critique = None
            evidence = tuple({
                "fact_id": fact.fact_id,
                "source": fact.source,
                "span": fact.span,
                "role": fact.role,
            } for fact in request.facts if fact.fact_id in {
                plan_id for plan in sentence_plans
                for plan_id in plan.fact_ids})
            result = GenerationResult(
                status="ok" if critique and critique.passed else "needs_revision",
                text=text,
                genre=style_request.genre,
                style=style,
                content_plan=content,
                discourse_plan=discourse,
                sentence_plans=sentence_plans,
                evidence=evidence,
                critique=critique,
                candidate_scores=(),
                rule_digest=self.rules.digest,
                warnings=clarity_issues,
            )
            candidates.append((critique.score if critique else 0.0,
                               -index, result))

        if not candidates:
            return GenerationResult(
                status="abstain", text="", genre=request.genre,
                style=request.style, content_plan=content,
                discourse_plan=None, sentence_plans=(), evidence=(),
                critique=None, candidate_scores=(),
                rule_digest=self.rules.digest,
                message="No generation candidate could be realized.",
            )
        candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        best = candidates[0][2]
        candidate_scores = tuple({
            "style": row[2].style,
            "score": round(row[0], 4),
            "passed": bool(row[2].critique and row[2].critique.passed),
        } for row in candidates)
        return GenerationResult(
            status=best.status,
            text=best.text,
            genre=best.genre,
            style=best.style,
            content_plan=best.content_plan,
            discourse_plan=best.discourse_plan,
            sentence_plans=best.sentence_plans,
            evidence=best.evidence,
            critique=best.critique,
            candidate_scores=candidate_scores,
            rule_digest=best.rule_digest,
            warnings=best.warnings,
        )


def rules_summary(rules: GenerationRules | None = None) -> dict[str, Any]:
    loaded = rules or load_rules()
    return loaded.as_dict()
