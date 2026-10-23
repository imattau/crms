"""Deterministic safety checks for quoted source evidence in natural questions."""
from __future__ import annotations

import json
import os
import re
from typing import Any, NamedTuple

from crms_intent_rules import classify as classify_intent
from crms_responsiveness import SMALL_INDEX
from crms_word_rarity import weight as word_weight
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
    "at", "in", "on", "from", "to", "by", "through", "across",
    "along",
    # "Whose X ...?" and "According to P, ..." open a question too.
    "whose", "according",
})
_NUMBER_WORDS = frozenset("""
zero one two three four five six seven eight nine ten eleven twelve
thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty
forty fifty sixty seventy eighty ninety hundred thousand million
""".split())
_QUALITATIVE_AMOUNT_WORDS = frozenset("""
all almost entirely largely little mostly nearly partly partially
primarily substantially some
""".split())
_MEASURE_UNITS = frozenset("""
metre metres meter meters m km kilometre kilometres kilometer kilometers
mile miles foot feet ft inch inches cm mm kg kilogram kilograms tonne tonnes
degree degrees celsius fahrenheit years year seconds minutes hours
""".split())
_WHEN_CUES = re.compile(
    r"\b(?:1[0-9]{3}|20[0-9]{2}|January|February|March|April|May|June|"
    r"July|August|September|October|November|December|Monday|Tuesday|"
    r"Wednesday|Thursday|Friday|Saturday|Sunday|if|unless|whenever|"
    r"provided\s+that|as\s+long\s+as|only\s+when|only\s+if|"
    r"before|after|until|once|while|at\s+(?:\d{1,2}(?::\d{2})?\s*"
    r"(?:a\.?m\.?|p\.?m\.?)|night|noon|midnight|dawn|dusk)|"
    r"in\s+the\s+(?:morning|afternoon|evening|night))\b",
    re.IGNORECASE)
_SUPERLATIVES = frozenset("""
longest largest biggest smallest tallest highest oldest youngest deepest
fastest nearest farthest first last
""".split())


def _tokens(text: str) -> list[str]:
    # A dash joining two word characters is a hyphen (Saffir–Simpson).
    chars = list(text)
    for index in range(1, len(chars) - 1):
        if (chars[index] in "–—" and chars[index - 1].isalnum()
                and chars[index + 1].isalnum()):
            chars[index] = "-"
    return re.findall(r"[\w’'-]+", "".join(chars))


def _stem(token: str) -> str:
    value = token.casefold().replace("’", "'")
    value = re.sub(r"'s$", "", value)
    irregular_base = next((lemma for lemma, forms in
                           _IRREGULAR_VERB_PARADIGMS.items()
                           if value in forms), None)
    if irregular_base is not None:
        value = irregular_base
    elif value in {"died", "lied", "tied"}:
        # These verbs retain the e when adding -d; they are not consonant-y
        # verbs written with -ied.
        value = value[:-1]
    elif value.endswith("ied") and len(value) > 4:
        value = value[:-3] + "y"
    elif value.endswith("ies") and len(value) > 4:
        value = value[:-3] + "y"
    elif (value.endswith(("sses", "xes", "zzes", "ches", "shes"))
          and len(value) > 4):
        # Preserve the base consonant in regular -es forms: crosses -> cross,
        # boxes -> box, and watches -> watch. Do not apply this to a generic
        # ``-zes`` or ``-oes`` ending: words such as ``sizes`` and ``shoes``
        # take the ordinary plural -s and retain their final e. A bare
        # trailing-s strip instead leaves a spurious e in crosses -> crosse.
        value = value[:-2]
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
        # Capitalized first-person "I" is a pronoun, not a named entity.
        if word.casefold() == "i":
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
    """Question type from the ``answer_type`` pattern-rule family (SQL)."""
    return classify_intent("answer_type", question)


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
        # For an active ``Who VERB ENTITY?`` question, the entity may precede
        # the predicate in a passive clause (``Python was created by Ada``).
        # Do not accept any later ``by`` phrase as sufficient: in
        # ``Monty Python ... is a movie made by Monty Python``, the queried
        # name is part of the agent/title, not the patient of ``made``.
        passive_pairs = []
        if active:
            auxiliaries = {"is", "are", "was", "were", "has", "have", "had",
                           "be", "been", "being"}
            lower = [word.casefold() for word in sentence_words]
            for anchor_start in anchor_positions:
                anchor_end = anchor_start + len(anchor_stems)
                for predicate_start in relation_positions:
                    if (predicate_start <= anchor_end
                            or predicate_start - anchor_end > 5):
                        continue
                    between = lower[anchor_end:predicate_start]
                    if not auxiliaries.intersection(between):
                        continue
                    if any(word == "by" for word in lower[predicate_start + 1:]):
                        passive_pairs.append((anchor_start, predicate_start))
        if active and passive_pairs:
            _passive_anchor, passive_predicate = min(passive_pairs)
            lower = [word.casefold() for word in sentence_words]
            by_positions = [i for i, word in enumerate(lower)
                            if word == "by" and i > passive_predicate]
            mention_terms = {word.casefold() for group in mentions for word in group}
            answer_after_by = [i for i, word in enumerate(sentence_words)
                               if word[:1].isupper()
                               and word.casefold() not in mention_terms
                               and word.casefold() not in {"the", "a", "an"}
                               and i > by_positions[0]] if by_positions else []
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


def _where_anchor_is_located_entity(sentence: str,
                                    mentions: list[list[str]]) -> bool:
    """Require a named WHERE anchor to occur before the locative relation.

    A target can appear only as the destination of an unrelated subject
    ("The Colosseum is in Rome, Italy"). That sentence supports where the
    Colosseum is, but does not answer where Italy is. This conservative role
    check handles direct subject-first clauses and abstains on other forms.
    """
    words = [word.casefold() for word in _tokens(sentence)]
    anchors: list[tuple[int, int]] = []
    for group in mentions:
        anchor = [word.casefold() for word in group if word.casefold() not in _STOP]
        if not anchor:
            continue
        for start in range(len(words) - len(anchor) + 1):
            if words[start:start + len(anchor)] == anchor:
                anchors.append((start, start + len(anchor)))
    if not anchors:
        return False

    # In a correlative clause, the entity after "where" is the located
    # subject: "Bletchley Park is where Alan Turing worked". An entity before
    # that clause ("Italy is where the Colosseum stands") is only being
    # identified as the destination, so it must not pass for a WHERE answer
    # about Italy itself.
    where_positions = [index for index, word in enumerate(words)
                       if word == "where"]
    if where_positions:
        where_position = where_positions[0]
        located_verbs = {
            "lie", "lies", "lay", "stand", "stands", "stood", "work",
            "works", "worked", "live", "lives", "lived", "sit", "sits",
            "sat", "reside", "resides", "resided",
        }
        return any(start > where_position
                   and any(word in located_verbs
                           for word in words[end:])
                   for start, end in anchors)

    relation_words = {
        "in", "at", "near", "located", "based", "lies", "situated",
        "through", "across", "along", "within", "born", "work", "worked",
        "works", "working", "live", "lived", "lives", "living", "from",
    }
    relation_positions = [index for index, word in enumerate(words)
                          if word in relation_words]
    if not relation_positions:
        return False
    first_relation = min(relation_positions)
    if any(start < first_relation for start, _end in anchors):
        return True

    # Permit the common locative inversion "In the Himalayas lies Mount
    # Everest". Require the sentence to open with a locative preposition and
    # a location verb before the named anchor, so destination-only mentions
    # later in an ordinary clause remain rejected.
    inversion_prepositions = {"in", "at", "near", "within", "across", "along"}
    location_verbs = {
        "lie", "lies", "lay", "stand", "stands", "stood", "sit", "sits",
        "sat", "run", "runs", "ran", "rise", "rises", "rose", "exist",
        "exists", "existed",
    }
    if words and words[0] in inversion_prepositions:
        return any(
            any(word in location_verbs for word in words[1:start])
            for start, _end in anchors)
    return False


def _has_locative_predicate(sentence: str) -> bool:
    """Require a bounded location-bearing predicate, not any ``in`` phrase.

    Decided by the ``locative`` pattern-rule family (SQL), over the sentence's
    word tokens."""
    flat = " ".join(_tokens(sentence))
    return classify_intent("locative", flat, normalise=False) == "LOCATIVE"


class Deviation(NamedTuple):
    """One named way a sentence departs from what a question requires."""
    dimension: str
    reason: str      # the witness: what in this sentence shows the deviation


def gate_policy() -> dict[str, dict[str, Any]]:
    """Gate policy rows (``pat_gate_policy``) from the seeded pattern memory.

    dimension -> {"answer_types": frozenset | None (all), "invariant": bool,
    "threshold": float | None, "typed_reason": str}."""
    from crms_pattern_defaults import seeded_policy
    return seeded_policy()


def _policy_applies(row: dict[str, Any], kind: str | None) -> bool:
    types = row["answer_types"]
    return types is None or (kind or "UNSUPPORTED") in types


def _is_generic(word: str) -> bool:
    return classify_intent("generic_word", word) == "GENERIC"


def _loose(word: str) -> str:
    """Stem that also folds a trailing e, so create/created and cite/cited
    agree (``_stem`` alone leaves create and creat apart)."""
    return _stem(word).rstrip("e")


def _fragment_witnesses(sentence: str) -> list[str]:
    """Why a sentence looks pasted, truncated, or like a title or table row."""
    out: list[str] = []
    text = sentence.strip()
    cue = classify_intent("fragment_cue", text, normalise=False)
    if cue == "leading section label":
        # "Abstract: <a whole sentence>": drop the label and judge what follows
        head, _, rest = text.partition(":")
        first = rest.split()[0].casefold() if rest.split() else ""
        if (len(rest.split()) >= 6 and rest.strip()[-1:] in ".!?"
                and first != "to"):         # "Objective: To reduce ..." is a purpose phrase, not a sentence
            text, cue = rest.strip(), None
    if cue:
        out.append(cue)
    if " ; " in text:
        out.append("table-style separator")
    if "$" not in text and (text.count("(") != text.count(")")
                            or text.count("[") != text.count("]")):
        out.append("unbalanced bracket")
    elif text.count(chr(34)) % 2:
        out.append("unbalanced quotation mark")
    if text and text[-1] not in ".!?\"”’')]":
        out.append("no sentence ending")
    return out


_COUNT_NEAR = 3


def _count_is_anchored(question_tokens: list[str],
                       sentence_tokens: list[str]) -> bool | None:
    """Whether some counted noun of ``how many N ...`` sits next to a number.

    None when the question has no ``how many`` noun to anchor."""
    lower = [word.casefold() for word in question_tokens]
    for index in range(len(lower) - 1):
        if lower[index] == "how" and lower[index + 1] == "many":
            nouns = [_loose(word) for word in question_tokens[index + 2:index + 4]
                     if word.casefold() not in _STOP]
            break
    else:
        return None
    if not nouns:
        return None
    stems = [_loose(word) for word in sentence_tokens]
    numeric = [any(ch.isdigit() for ch in word)
               or word.casefold() in _NUMBER_WORDS for word in sentence_tokens]
    for position, stem in enumerate(stems):
        if stem not in nouns:
            continue
        window = range(max(0, position - _COUNT_NEAR),
                       min(len(stems), position + _COUNT_NEAR + 1))
        if any(numeric[i] for i in window):
            return True
    return False


def _asks_for_year(question_tokens: list[str]) -> bool:
    lower = [word.casefold() for word in question_tokens]
    return any(lower[i] in {"what", "which"} and lower[i + 1] == "year"
               for i in range(len(lower) - 1))


def _has_year(sentence_tokens: list[str]) -> bool:
    return any(word.isdigit() and len(word) == 4 and 1000 <= int(word) <= 2099
               for word in sentence_tokens)


def _deviations(question: str, sentence: str,
                licensed_predicates: list[dict[str, Any]],
                kind: str | None, title: str = ""
                ) -> tuple[list[Deviation], int]:
    """Every named deviation of `sentence` from what `question` requires, with
    a witness reason each, plus the relation-overlap score.

    Which deviations are fatal is policy (``pat_gate_policy``), not code."""

    q_tokens = _tokens(question)
    sentence_tokens = _tokens(sentence)
    stripped_sentence = sentence.strip()
    q_words = {word.casefold() for word in q_tokens}
    s_words = {word.casefold() for word in sentence_tokens}
    found: list[Deviation] = []

    def add(dimension: str, reason: str) -> None:
        found.append(Deviation(dimension, reason))

    first_letter = next((char for char in stripped_sentence if char.isalpha()), "")
    if (first_letter and first_letter.islower()) or stripped_sentence.endswith((":", ";")):
        add("fragment", "source hit is an incomplete sentence")
    # Numbered entities are common in large or synthetic corpora. Treat an
    # explicit numeric identifier in the question as an identity constraint;
    # without this, high-frequency topical terms can tie records 0000–0009
    # against a request for record 0266.
    required_numbers = {word for word in q_tokens if word.isdigit()}
    missing_numbers = required_numbers - set(sentence_tokens)
    if missing_numbers:
        add("entity_absent", "numbered identifier missing: "
            + ", ".join(sorted(missing_numbers)))
    mentions = _question_mentions(question)
    mention_terms = {word.casefold() for group in mentions for word in group
                     if word.casefold() not in _STOP}
    for group in mentions:
        absent = [word for word in group
                  if word.casefold() not in _STOP
                  and _stem(word) not in {_stem(token) for token in s_words}]
        if absent:
            add("entity_absent", "named entity missing: " + " ".join(group))

    if kind == "WHEN" and not _WHEN_CUES.search(sentence):
        add("answer_type_mismatch", "no date, time, or condition stated")
    elif kind == "MEASURE":
        unit_pattern = r"\b(?:" + "|".join(sorted(_MEASURE_UNITS, key=len, reverse=True)) + r")\b"
        if not re.search(r"\d[\d,.]*\s*" + unit_pattern, sentence, re.IGNORECASE):
            add("answer_type_mismatch", "no number with a recognized unit")
    elif kind == "COUNT":
        qualitative_fraction = (
            re.search(r"\bhow\s+much\s+of\b", question, re.IGNORECASE)
            and bool(_QUALITATIVE_AMOUNT_WORDS & s_words))
        if (not qualitative_fraction and not re.search(r"\d", sentence)
                and not (_NUMBER_WORDS & s_words)):
            add("answer_type_mismatch", "no explicit count")
    elif kind == "HOW":
        procedure_terms = {
            "create", "copy", "include", "use", "run", "save", "install",
            "rebuild", "export", "import", "configure", "provide", "enable",
            "attach", "pass", "select", "open", "write", "set",
        }
        procedure_stems = {_stem(term) for term in procedure_terms}
        if not any(_stem(word) in procedure_stems for word in sentence_tokens):
            add("answer_type_mismatch", "no procedural action stated")
    elif kind in {"WHO", "WHERE"}:
        capitalized = [word for word in sentence_tokens
                       if word[:1].isupper()
                       and word.casefold() not in {"the", "a", "an"}
                       and word.casefold() not in mention_terms]
        if not capitalized:
            add("answer_type_mismatch", "no named answer span")
        requested_place_type = re.search(
            r"\bwhich\s+(?P<type>institute|university|laboratory|"
            r"research\s+center|observatory)\b",
            question, flags=re.IGNORECASE)
        has_locative = (kind == "WHERE"
                        and _has_locative_predicate(sentence))
        if kind == "WHERE" and not has_locative and requested_place_type:
            # Specialized "at which institute/university..." questions may
            # name the venue before the event predicate ("researchers at X
            # studied Y"). Retain the type and nearby preposition as the role
            # check; ordinary WHERE questions do not get this relaxation.
            requested_type = re.escape(
                " ".join(_tokens(requested_place_type.group("type"))))
            has_locative = bool(re.search(
                rf"\b(?:at|in|near)\b.{{0,60}}\b{requested_type}\b",
                sentence, re.IGNORECASE))
        if kind == "WHERE" and not has_locative:
            add("answer_type_mismatch", "no location-bearing predicate in sentence")
        if (kind == "WHERE" and mentions
                and not _where_anchor_is_located_entity(sentence, mentions)):
            add("role_order",
                "named entity appears as a location, not as the located subject")
        if requested_place_type is not None:
            type_tokens = [word.casefold() for word in
                           _tokens(requested_place_type.group("type"))]
            if any(word not in s_words for word in type_tokens):
                add("answer_type_mismatch", "requested location type missing")
    elif kind == "DEF":
        missing_definition = re.fullmatch(
            r"what\s+does\s+(?:(?:a|an|the)\s+)?missing\s+(.+?)\s+mean"
            r"(?:\s+in\s+.+)?",
            question.strip().rstrip("?.!"), re.IGNORECASE)
        if missing_definition is not None:
            concept = [word.casefold() for word in _tokens(
                missing_definition.group(1)) if word.casefold() not in _STOP]
            concept_pattern = r"\s+".join(re.escape(word) for word in concept)
            absence_definition = bool(
                concept_pattern
                and re.search(
                    rf"\babsence\s+of\s+(?:(?:a|an|the)\s+)?{concept_pattern}\b"
                    rf".{{0,80}}\b(?:is|means|was)\b",
                    sentence, re.IGNORECASE))
            if not absence_definition:
                add("answer_type_mismatch", "source does not define the missing concept")
        else:
            subject = re.search(
                r"^(?:what\s+(?:is|are|does|do)|define)\s+(.+?)[?.!]?$",
                question.strip(), re.IGNORECASE)
            if subject is not None:
                subject_tokens = [_stem(word) for word in _tokens(subject.group(1))
                                  if word.casefold() not in _STOP]
                first_tokens = {_stem(word) for word in sentence_tokens[:6]}
                if subject_tokens and not all(word in first_tokens
                                              for word in subject_tokens):
                    add("answer_type_mismatch", "definition subject is not in sentence subject position")

    q_modifiers = {word.casefold() for word in q_tokens
                   if word.casefold() in _SUPERLATIVES}
    if not q_modifiers <= s_words:
        add("relation_not_predicated", "required modifier missing: "
            + ", ".join(sorted(q_modifiers - s_words)))

    content = {_loose(word) for word in q_tokens
               if word.casefold() not in _STOP | _SUPERLATIVES
               and word.casefold() not in mention_terms
               and not word.isdigit()}
    sentence_stems = {_loose(word) for word in sentence_tokens}
    relation_terms = set(content)
    licensed_groups: dict[str, set[str]] = {}
    for record in licensed_predicates:
        if record.get("kind") != "licensed_predicate":
            continue
        evidence = str(record.get("evidence", "")).strip().casefold()
        phrase = str(record.get("text", "")).strip()
        if evidence and phrase:
            licensed_groups.setdefault(evidence, set()).update(
                _loose(word) for word in _tokens(phrase))
    for terms in licensed_groups.values():
        if content & terms:
            relation_terms.update(terms)
    overlap = relation_terms & sentence_stems
    # For definitions the subject itself is the grounding signal; for other
    # question types require some lexical evidence for the requested relation.
    if kind != "DEF" and content and not overlap:
        add("relation_not_predicated", "no question-relation term in sentence")
    if kind == "HOW" and len(overlap) < 2:
        add("relation_not_predicated", "too little question detail matches the procedure")
    if kind == "WHO" and _role_order_mismatch(question, sentence, mentions):
        add("role_order", "agent, relation, or object appears in the wrong order")

    for witness in _fragment_witnesses(sentence):
        add("fragment", "pasted fragment: " + witness)
    if kind == "COUNT" and _count_is_anchored(q_tokens, sentence_tokens) is False:
        add("answer_slot_unfilled", "no number next to the counted noun")
    if _asks_for_year(q_tokens) and not _has_year(sentence_tokens):
        add("answer_slot_unfilled", "no year stated")
    coverage = gate_policy().get("relation_coverage")
    if coverage and coverage["threshold"] is not None:
        # Words that name the cited document are topic, not relation: retrieval
        # already matched them, so they cannot show the sentence answers.
        topic = {_loose(word) for word in _tokens(title)}
        words = [word for word in q_tokens
                 if word.casefold() not in _STOP | _SUPERLATIVES
                 and word.casefold() not in mention_terms
                 and not word.isdigit() and not _is_generic(word)
                 and _loose(word) not in topic]
        loose_sentence = {_loose(word) for word in sentence_tokens}
        licensed_present = {
            term for terms in licensed_groups.values()
            if terms & sentence_stems for term in terms}
        missing = [word for word in words
                   if _loose(word) not in loose_sentence
                   and _loose(word) not in licensed_present]
        if words and len(missing) / len(words) >= coverage["threshold"]:
            add("relation_coverage",
                "question terms absent from the sentence: " + ", ".join(missing))
    rare = gate_policy().get("rare_term_absent")
    weighted = gate_policy().get("weighted_coverage")
    if rare or weighted:
        # Rarity replaces the hand-written generic-word list: a rare question term the sentence
        # lacks says it is about something else; the weighted share of absent terms says how much.
        topic = {_loose(word) for word in _tokens(title)}
        terms = [word for word in q_tokens
                 if word.casefold() not in _STOP | _SUPERLATIVES
                 and not word.isdigit() and _loose(word) not in topic]
        loose_sentence = {_loose(word) for word in sentence_tokens}
        present_licensed = {term for terms_ in licensed_groups.values()
                            if terms_ & sentence_stems for term in terms_}
        absent = [word for word in terms if _loose(word) not in loose_sentence
                  and _loose(word) not in present_licensed]
        if rare and rare["threshold"] is not None:
            rare_absent = [w for w in absent if word_weight(w) >= rare["threshold"]]
            if rare_absent:
                add("rare_term_absent", "rare question term absent from the sentence: "
                    + ", ".join(rare_absent))
        if weighted and weighted["threshold"] is not None and terms:
            total_weight = sum(word_weight(w) for w in terms)
            if total_weight and sum(word_weight(w) for w in absent) / total_weight >= weighted["threshold"]:
                add("weighted_coverage", "question terms, weighted by rarity, absent from the sentence: "
                    + ", ".join(absent))
    return found, len(overlap)


def _row_title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("source_title") or "")


def _check_candidate(question: str, sentence: str,
                     licensed_predicates: list[dict[str, Any]],
                     title: str = ""
                     ) -> tuple[bool, list[str], int]:
    accepted, found, score = _judge(question, sentence, licensed_predicates,
                                    title)
    return accepted, [d.reason for d in found], score


def _judge(question: str, sentence: str,
           licensed_predicates: list[dict[str, Any]], title: str = ""
           ) -> tuple[bool, list[Deviation], int]:
    """Deviations that policy makes invariant for this question's type."""
    kind = _answer_type(question)
    policy = gate_policy()
    found, score = _deviations(question, sentence, licensed_predicates, kind,
                               title)
    fatal = [d for d in found
             if d.dimension in policy and policy[d.dimension]["invariant"]
             and _policy_applies(policy[d.dimension], kind)]
    return not fatal, fatal, score


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
    checked = gate_passing_candidates(
        question, list(unique.values()),
        licensed_predicates=licensed_predicates)
    if not checked:
        first = next(iter(unique.values()))
        _accepted, found, _score = _judge(
            question, str(first.get("text", "")), licensed_predicates,
            _row_title(first))
        return {"status": "rejected", "evidence": first,
                "reasons": [d.reason for d in found],
                "dimensions": sorted({d.dimension for d in found})}
    if len(checked) > 1 and checked[0]["gate_score"] == checked[1]["gate_score"]:
        return {"status": "ambiguous", "evidence": None,
                "reasons": ["multiple equally supported source sentences"]}
    selected = {key: value for key, value in checked[0].items()
                if key != "gate_score"}
    return {"status": "accepted", "evidence": selected, "reasons": []}


def is_plain_question(question: str) -> bool:
    """A question sentence (opens with a question word, ends with ``?``), as
    opposed to an imperative or a selection such as ``the first one``."""
    words = _tokens(question)
    return (question.rstrip().endswith("?") and bool(words)
            and words[0].casefold() in _QUESTION_STARTERS)


def gate_displayed_quote(question: str, row: dict[str, Any], *,
                         licensed_predicates: list[dict[str, Any]] | None = None
                         ) -> dict[str, Any]:
    """Judge the one sentence a quote fallback is about to show.

    For question shapes the evidence gate has no bounded parser for (and for
    yes/no questions) the chat quotes its top hit unchecked. Only the policy
    dimensions that apply to those shapes (fragment, entity, relation) can be
    checked, but they are checked here: the sentence is either shown or
    withheld with the typed reasons, never replaced by another."""
    accepted, found, _score = _judge(
        question, str(row.get("text", "")), licensed_predicates or [],
        _row_title(row))
    return {"status": "accepted" if accepted else "rejected",
            "evidence": row, "reasons": [d.reason for d in found],
            "dimensions": sorted({d.dimension for d in found})}


def gate_passing_candidates(
        question: str, candidates: list[dict[str, Any]], *,
        licensed_predicates: list[dict[str, Any]] | None = None
        ) -> list[dict[str, Any]]:
    """Return every unique sentence that passes the exact evidence gate.

    This exposes the gate's eligible set for diagnostics and opt-in ranker
    experiments. It does not choose an answer or relax any acceptance check.
    """
    if not supports_question_type(question):
        return []
    licensed_predicates = licensed_predicates or []
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        sentence = str(row.get("text", "")).strip()
        if sentence:
            unique.setdefault(sentence.casefold(), row)
    checked = []
    for row in unique.values():
        accepted, _reasons, score = _check_candidate(
            question, str(row.get("text", "")), licensed_predicates,
            _row_title(row))
        if accepted:
            checked.append((score, row))
    checked.sort(key=lambda item: (-item[0],
                                   str(item[1].get("citation", "")),
                                   str(item[1].get("text", "")).casefold()))
    return [{**row, "gate_score": score} for score, row in checked]


def trace_gate_decision(question: str, rows: list[dict[str, Any]],
                        licensed_predicates: list[dict[str, Any]],
                        decision: dict[str, Any]) -> None:
    """Append the gate's inputs and outcome to ``$CRMS_GATE_TRACE`` (JSON lines).

    Development aid: it lets gate changes be replayed offline over the exact
    candidates a chat session produced. A no-op unless the variable is set."""
    path = os.environ.get("CRMS_GATE_TRACE")
    if not path:
        return
    keep = ("text", "title", "source_title", "citation", "document_id", "kind", "evidence")
    record = {"question": question,
              "rows": [{k: row[k] for k in keep if k in row} for row in rows],
              "licensed": [{k: r[k] for k in keep if k in r}
                           for r in licensed_predicates],
              "status": decision.get("status"),
              "reasons": decision.get("reasons", []),
              "dimensions": decision.get("dimensions", [])}
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def deviation_dimensions(question: str, sentence: str, title: str = "") -> list[str]:
    """Names of the deviations the rule gate finds for a sentence (features for the learned scorer)."""
    try:
        found, _score = _deviations(question, sentence, [], _answer_type(question), title)
    except Exception:
        return []
    return sorted({d.dimension for d in found})


CORROBORATED_THRESHOLD = 0.4        # minimum probability when the rule gate agrees (small collections only)
_HARD_VETOES = frozenset({"fragment", "entity_absent"})


def gate_with_scorer(question: str, candidates: list[dict[str, Any]], *,
                     licensed_predicates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Learned decision when the scorer is installed, else the rule gate.

    The best retrieved sentence by learned probability is answered only above the policy threshold and only
    if it is not a pasted fragment and names the question's entity; otherwise the answer is a typed
    refusal. Same result shape as `gate_quoted_evidence`."""
    from crms_pattern_defaults import scorer_model
    from crms_responsiveness import decide
    weights, threshold = scorer_model()
    if not weights or not is_plain_question(question):
        return gate_quoted_evidence(question, candidates, licensed_predicates=licensed_predicates)
    unique: dict[str, dict[str, Any]] = {}
    for row in candidates:
        sentence = str(row.get("text", "")).strip()
        if sentence:
            unique.setdefault(sentence.casefold(), row)
    if not unique:
        return {"status": "no_candidates", "evidence": None, "reasons": []}
    decision = decide(question, list(unique.values()), weights, threshold=threshold,
                      deviation_fn=deviation_dimensions)
    if decision["status"] == "rejected" and SMALL_INDEX["small"]:
        # in a small collection the rule gate's agreement is enough corroboration for a middling score
        rule = gate_quoted_evidence(question, candidates, licensed_predicates=licensed_predicates)
        chosen = decision.get("evidence") or {}
        if (rule["status"] == "accepted"
                and str((rule["evidence"] or {}).get("text", "")).strip().casefold()
                == str(chosen.get("text", "")).strip().casefold()
                and decision.get("probability", 0.0) >= CORROBORATED_THRESHOLD):
            decision = {"status": "accepted", "evidence": chosen, "reasons": [],
                        "probability": decision.get("probability")}
    if decision["status"] == "accepted":
        row = decision["evidence"]
        ok, fatal, _score = _judge(question, str(row.get("text", "")), licensed_predicates or [],
                                   _row_title(row))
        vetoes = [d for d in fatal if d.dimension in _HARD_VETOES]
        if vetoes:
            return {"status": "rejected", "evidence": row, "reasons": [d.reason for d in vetoes],
                    "dimensions": sorted({d.dimension for d in vetoes})}
    return {k: v for k, v in decision.items() if k != "probability" and k != "why"} | {
        "probability": decision.get("probability")}
