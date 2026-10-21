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

from crms_research import _sentence_spans   # shared sentence splitter

_ROLE_FIELD = re.compile(
    r"^(occupation|position|office|title|role|profession)\s*=\s*(.+)$", re.I)


class ListSentenceSource:
    """A fixed pool of (title, sentence) pairs; used by tests and the verifier."""

    def __init__(self, pairs: Sequence[tuple[str, str]]) -> None:
        self.pairs = list(pairs)
        self.synthetic: set[str] = set()

    def sentences(self, entity: str, question: str) -> Iterable[tuple[str, str]]:
        return list(self.pairs)


class IndexSentenceSource:
    def __init__(self, index: Any, *, search_limit: int = 25,
                 exact_limit: int = 400) -> None:
        self.index = index
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
            for a, b in _sentence_spans(document.text)[:self.exact_limit]:
                for part in document.text[a:b].split("\n"):
                    if part.strip():
                        out.append((document.title, part.strip()))
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
