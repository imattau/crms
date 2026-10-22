"""Sentence sources for the relation engine (Phase 11).

`IndexSentenceSource` draws candidate sentences for an entity from a CRMS
research index: the entity's exact-title page, plus a bounded full-text search.
An infobox role field (occupation, office, ...) becomes a clearly marked
synthetic sentence about the page's subject, so a fact stated only in a field
can still be matched. Nothing here changes what the index stores.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from crms_relation_specs import ListSentenceSource  # noqa: F401  (re-exported)
from crms_research import _sentence_spans   # shared sentence splitter

_ROLE_FIELD = re.compile(
    r"^(occupation|position|office|title|role|profession)\s*=\s*(.+)$", re.I)


_PAGE_PRONOUNS = frozenset({"it", "he", "she", "they"})


def resolve_page_subject(sentence: str, title: str, modes: frozenset = frozenset({"bracket"})) -> str | None:
    """The sentence with its page's subject made explicit, or None.

    Two cases, both only for the first sentences of the page that the title names:
    a leading pronoun ("It was directed by X") and a lead sentence whose bold title
    was stripped, leaving a stray bracket ("... ) is a 2014 film directed by X").
    The result is a synthetic sentence; the original is kept as well."""
    if title.casefold() in sentence.casefold():
        return None
    first, _, rest = sentence.partition(" ")
    if "pronoun" in modes and first.casefold() in _PAGE_PRONOUNS and rest:
        return f"{title} {rest}"
    stripped = sentence.lstrip()
    if "bracket" in modes and stripped[:1] in ")(" and len(stripped) > 4:
        return f"{title} {stripped.lstrip(')( ').strip()}"
    return None


class IndexSentenceSource:
    def __init__(self, index: Any, *, search_limit: int = 25,
                 exact_limit: int = 400, subject_window: int = 6,
                 subject_modes: frozenset = frozenset({"bracket"})) -> None:
        self.index = index
        self.subject_modes = frozenset(subject_modes)
        self.subject_window = subject_window    # lead sentences where a missing subject is the page title
        self.search_limit = search_limit
        self.exact_limit = exact_limit
        self.synthetic: set[str] = set()
        self._cache: dict[str, list[tuple[str, str]]] = {}

    def sentences(self, entity: str, question: str = "") -> list[tuple[str, str]]:
        if entity in self._cache:
            return self._cache[entity]
        out: list[tuple[str, str]] = []
        hits: list[Any] = []
        for candidate in (entity, "The " + entity, "A " + entity, "An " + entity):
            try:
                hits = self.index.exact_title_matches(candidate)
            except Exception:
                hits = []
            if hits:
                break
        if len(hits) == 1:   # an ambiguous title is not guessed at
            document = self.index.document(hits[0].document_id)
            for position, (a, b) in enumerate(_sentence_spans(document.text)[:self.exact_limit]):
                for part in document.text[a:b].split("\n"):
                    if part.strip():
                        out.append((document.title, part.strip()))
                        if position < self.subject_window:
                            resolved = resolve_page_subject(part.strip(), document.title, self.subject_modes)
                            if resolved:
                                self.synthetic.add(resolved)
                                out.append((document.title, resolved))
        out.extend(self._search(entity))
        self._cache[entity] = out
        return out

    def _search(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        query = re.sub(r"[’']s\b", "", text)
        for hit in self.index.search(query, limit=self.search_limit, context_chars=400):
            document = self.index.document(hit.document_id)
            for a, b in _sentence_spans(hit.snippet):
                for part in hit.snippet[a:b].split("\n"):
                    part = part.strip()
                    if not part:
                        continue
                    m = _ROLE_FIELD.match(part)
                    if m:
                        sentence = f"{document.title} is {m.group(2).strip()}."
                        self.synthetic.add(sentence)
                    else:
                        sentence = part
                    out.append((document.title, sentence))
        return out
