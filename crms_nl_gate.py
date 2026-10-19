"""Deterministic safety checks for quoted source evidence in natural questions."""
from __future__ import annotations

import re
from typing import Any

from crms_knowledge import _IRREGULAR_VERB_PARADIGMS


_STOP = frozenset("""
a an the of in on at to for by is are was were be been being do does did
has have had it its this that and or not as with from into than then there
their his her he she i me you my please tell know like would could can name
define whom who what which when where how why whose about much many people
person city country river mountain range year time first one
""".split())
_QUESTION_STARTERS = frozenset({
    "who", "what", "when", "where", "why", "which", "how", "is", "are",
    "was", "were", "did", "does", "do", "can", "could", "would", "will",
    "has", "have", "please", "tell", "i", "name", "define",
    # Initial prepositions introduce answer slots, not named entities.
    "at", "in", "on", "from", "to", "by",
})
_NUMBER_WORDS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve
thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty
forty fifty sixty seventy eighty ninety hundred thousand million
""".split())
_MEASURE_UNITS = frozenset("""
metre metres meter meters m km kilometre kilometres kilometer kilometers
mile miles foot feet ft inch inches cm mm kg kilogram kilograms tonne tonnes
degree degrees celsius fahrenheit years year seconds minutes hours
""".split())
_SUPERLATIVES = frozenset("""
longest largest biggest smallest tallest highest oldest youngest deepest
fastest nearest farthest first last
""".split())


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w’'-]+", text)


def _stem(token: str) -> str:
    value = token.casefold().replace("’", "'")
    value = re.sub(r"'s$", "", value)
    irregular_base = next((lemma for lemma, forms in
                           _IRREGULAR_VERB_PARADIGMS.items()
                           if value in forms), None)
    if irregular_base is not None:
        value = irregular_base
    elif value.endswith("ies") and len(value) > 4:
        value = value[:-3] + "y"
    elif value.endswith("s") and not value.endswith("ss") and len(value) > 3:
        value = value[:-1]
    else:
        for suffix in ("ing", "ed", "s"):
            if len(value) > len(suffix) + 2 and value.endswith(suffix):
                value = value[:-len(suffix)]
                break
    return value[:6]


def _question_mentions(question: str) -> list[list[str]]:
    words = _tokens(question)
    mentions: list[list[str]] = []
    current: list[str] = []
    for index, word in enumerate(words):
        if index == 0 and word.casefold() in _QUESTION_STARTERS:
            continue
        if word[:1].isupper():
            current.append(word)
        elif current and word.casefold() in {"van", "von", "de", "da", "del"}:
            current.append(word)
        elif current and word.isdigit():
            # Numeric suffixes are part of names such as "Person 0" and
            # "Apollo 13". Keep them in the entity check so generic title
            # words cannot make every similarly named source tie.
            current.append(word)
        elif current:
            mentions.append(current)
            current = []
    if current:
        mentions.append(current)
    return mentions


def _answer_type(question: str) -> str | None:
    q = question.casefold().strip()
    if re.match(r"^(is|are|was|were|did|does|do|has|have)\b", q):
        return "POLAR"
    if re.search(r"\b(who|whom)\b", q):
        return "WHO"
    if re.search(r"\b(when|what year|in what year)\b", q):
        return "WHEN"
    if re.search(r"\bwhere\b", q):
        return "WHERE"
    if re.search(
            r"\b(?:which\s+(?:country|city|continent|range|mountain range|"
            r"river|region|state|institute|university|laboratory|"
            r"research\s+center|observatory)|"
            r"(?:at|in)\s+which\s+(?:institute|university|laboratory|"
            r"research\s+center|observatory))\b", q):
        return "WHERE"
    if re.search(r"\b(birthplace|place of birth|workplace|location of)\b", q):
        return "WHERE"
    if (re.search(r"\bhow\s+(tall|high|long|big|old)\b|\b(height|temperature|boiling point|melting point)\b", q)):
        return "MEASURE"
    if re.search(r"\bhow\s+(many|much)\b", q):
        return "COUNT"
    if re.match(r"^(what|define)\s+(is|are)\b", q) or re.match(
            r"^what\s+(does|do)\b", q):
        return "DEF"
    if re.search(r"\b(what|which)\b", q):
        return "NAME"
    return None


def supports_question_type(question: str) -> bool:
    """Whether the deterministic evidence gate has a bounded parser for Q."""
    return _answer_type(question) not in {None, "POLAR"}


def _role_order_mismatch(question: str, sentence: str,
                        mentions: list[list[str]]) -> bool:
    """Reject reversed active-agent or `relation of X` evidence roles."""
    q = question.casefold().strip().rstrip("?.! ")
    relation: list[str] = []
    anchor: list[str] = []
    active = False
    nominal = re.fullmatch(
        r"who\s+(?:is|was|are|were)\s+(?:the\s+|a\s+|an\s+)?"
        r"(?P<relation>.+?)\s+of\s+(?P<anchor>.+)", q)
    direct = re.fullmatch(
        r"who\s+(?P<relation>[a-z][\w'-]*)\s+(?P<anchor>.+)", q)
    if nominal:
        relation = [word.casefold() for word in _tokens(nominal.group("relation"))
                    if word.casefold() not in _STOP]
        anchor = [word.casefold() for word in _tokens(nominal.group("anchor"))
                  if word.casefold() not in _STOP]
    elif direct:
        relation = [direct.group("relation").casefold()]
        anchor = [word.casefold() for word in _tokens(direct.group("anchor"))
                  if word.casefold() not in _STOP]
        active = True
    if not relation or not anchor:
        return False

    sentence_words = _tokens(sentence)
    sentence_stems = [_stem(word) for word in sentence_words]
    relation_stems = {_stem(word) for word in relation}
    relation_positions = [i for i, word in enumerate(sentence_stems)
                          if word in relation_stems]
    anchor_stems = [_stem(word) for word in anchor]
    anchor_positions = [i for i in range(len(sentence_stems) - len(anchor_stems) + 1)
                        if sentence_stems[i:i + len(anchor_stems)] == anchor_stems]
    if not relation_positions or not anchor_positions:
        return False
    relation_position = min(relation_positions)
    anchor_position = min(anchor_positions)
    if anchor_position <= relation_position:
        lower = [word.casefold() for word in sentence_words]
        by_positions = [i for i, word in enumerate(lower)
                       if word == "by" and i > relation_position]
        if active and by_positions:
            mention_terms = {word.casefold() for group in mentions for word in group}
            answer_after_by = [i for i, word in enumerate(sentence_words)
                               if word[:1].isupper()
                               and word.casefold() not in mention_terms
                               and word.casefold() not in {"the", "a", "an"}
                               and i > by_positions[0]]
            if answer_after_by:
                return False
        return True
    if active:
        mention_terms = {word.casefold() for group in mentions for word in group}
        answer_positions = [i for i, word in enumerate(sentence_words)
                            if word[:1].isupper()
                            and word.casefold() not in mention_terms
                            and word.casefold() not in {"the", "a", "an"}]
        return not answer_positions or min(answer_positions) >= relation_position
    return False


def _check_candidate(question: str, sentence: str,
                     licensed_predicates: list[dict[str, Any]]
                     ) -> tuple[bool, list[str], int]:
    kind = _answer_type(question)
    if kind in {None, "POLAR"}:
        return True, [], 0

    q_tokens = _tokens(question)
    sentence_tokens = _tokens(sentence)
    q_words = {word.casefold() for word in q_tokens}
    s_words = {word.casefold() for word in sentence_tokens}
    reasons: list[str] = []
    # Numbered entities are common in large or synthetic corpora. Treat an
    # explicit numeric identifier in the question as an identity constraint;
    # without this, high-frequency topical terms can tie records 0000–0009
    # against a request for record 0266.
    required_numbers = {word for word in q_tokens if word.isdigit()}
    missing_numbers = required_numbers - set(sentence_tokens)
    if missing_numbers:
        reasons.append("numbered identifier missing: "
                       + ", ".join(sorted(missing_numbers)))
    mentions = _question_mentions(question)
    mention_terms = {word.casefold() for group in mentions for word in group
                     if word.casefold() not in _STOP}
    for group in mentions:
        absent = [word for word in group
                  if word.casefold() not in _STOP
                  and _stem(word) not in {_stem(token) for token in s_words}]
        if absent:
            reasons.append("named entity missing: " + " ".join(group))

    if kind == "WHEN" and not re.search(r"\b(?:1[0-9]{3}|20[0-9]{2})\b", sentence):
        reasons.append("no year stated")
    elif kind == "MEASURE":
        unit_pattern = r"\b(?:" + "|".join(sorted(_MEASURE_UNITS, key=len, reverse=True)) + r")\b"
        if not re.search(r"\d[\d,.]*\s*" + unit_pattern, sentence, re.IGNORECASE):
            reasons.append("no number with a recognized unit")
    elif kind == "COUNT":
        if not re.search(r"\d", sentence) and not (_NUMBER_WORDS & s_words):
            reasons.append("no explicit count")
    elif kind in {"WHO", "WHERE"}:
        capitalized = [word for word in sentence_tokens
                       if word[:1].isupper()
                       and word.casefold() not in {"the", "a", "an"}
                       and word.casefold() not in mention_terms]
        if not capitalized:
            reasons.append("no named answer span")
        if kind == "WHERE" and not re.search(
                r"\b(?:in|at|near|located|based|lies|situated|through|"
                r"across|along|within|born|work(?:s|ed|ing)?|live(?:s|d|ing)?|from)\b",
                sentence, flags=re.IGNORECASE):
            reasons.append("no locative relation in sentence")
        requested_place_type = re.search(
            r"\bwhich\s+(?P<type>institute|university|laboratory|"
            r"research\s+center|observatory)\b",
            question, flags=re.IGNORECASE)
        if requested_place_type is not None:
            type_tokens = [word.casefold() for word in
                           _tokens(requested_place_type.group("type"))]
            if any(word not in s_words for word in type_tokens):
                reasons.append("requested location type missing")
    elif kind == "DEF":
        subject = re.search(r"^(?:what\s+(?:is|are|does|do)|define)\s+(.+?)[?.!]?$",
                            question.strip(), re.IGNORECASE)
        if subject is not None:
            subject_tokens = [_stem(word) for word in _tokens(subject.group(1))
                              if word.casefold() not in _STOP]
            first_tokens = {_stem(word) for word in sentence_tokens[:6]}
            if subject_tokens and not all(word in first_tokens
                                          for word in subject_tokens):
                reasons.append("definition subject is not in sentence subject position")

    q_modifiers = {word.casefold() for word in q_tokens
                   if word.casefold() in _SUPERLATIVES}
    if not q_modifiers <= s_words:
        reasons.append("required modifier missing: "
                       + ", ".join(sorted(q_modifiers - s_words)))

    content = {_stem(word) for word in q_tokens
               if word.casefold() not in _STOP | _SUPERLATIVES
               and word.casefold() not in mention_terms
               and not word.isdigit()}
    sentence_stems = {_stem(word) for word in sentence_tokens}
    relation_terms = set(content)
    licensed_groups: dict[str, set[str]] = {}
    for record in licensed_predicates:
        if record.get("kind") != "licensed_predicate":
            continue
        evidence = str(record.get("evidence", "")).strip().casefold()
        phrase = str(record.get("text", "")).strip()
        if evidence and phrase:
            licensed_groups.setdefault(evidence, set()).update(
                _stem(word) for word in _tokens(phrase))
    for terms in licensed_groups.values():
        if content & terms:
            relation_terms.update(terms)
    overlap = relation_terms & sentence_stems
    # For definitions the subject itself is the grounding signal; for other
    # question types require some lexical evidence for the requested relation.
    if kind != "DEF" and content and not overlap:
        reasons.append("no question-relation term in sentence")
    if kind == "WHO" and _role_order_mismatch(question, sentence, mentions):
        reasons.append("agent, relation, or object appears in the wrong order")
    return not reasons, reasons, len(overlap)


def gate_quoted_evidence(question: str, candidates: list[dict[str, Any]], *,
                         licensed_predicates: list[dict[str, Any]] | None = None
                         ) -> dict[str, Any]:
    """Choose a unique, type- and mention-compatible quoted sentence or abstain."""
    if not supports_question_type(question):
        return {"status": "unsupported", "evidence": None, "reasons": []}
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        sentence = str(row.get("text", "")).strip()
        if sentence:
            unique.setdefault(sentence.casefold(), row)
    if not unique:
        return {"status": "no_candidates", "evidence": None, "reasons": []}

    licensed_predicates = licensed_predicates or []
    checked = []
    for row in unique.values():
        sentence = str(row.get("text", ""))
        accepted, reasons, score = _check_candidate(
            question, sentence, licensed_predicates)
        if accepted:
            checked.append((score, row))
    if not checked:
        first = next(iter(unique.values()))
        _accepted, reasons, _score = _check_candidate(
            question, str(first.get("text", "")), licensed_predicates)
        return {"status": "rejected", "evidence": first, "reasons": reasons}
    checked.sort(key=lambda item: item[0], reverse=True)
    if len(checked) > 1 and checked[0][0] == checked[1][0]:
        return {"status": "ambiguous", "evidence": None,
                "reasons": ["multiple equally supported source sentences"]}
    return {"status": "accepted", "evidence": checked[0][1], "reasons": []}
