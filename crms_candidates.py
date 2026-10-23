"""Extra candidate sentences for the answerability scorer (Phase 13).

The chat's retrieval returns sentences by full-text match on the question. On natural-style questions the
answer is in none of them for more than half the questions, so the scorer never sees it. Two additions,
both deterministic:

* entity page: when the question names an entity whose own page exists (exact title), the page's sentences
  that share a content term with the question;
* neighbour expansion: a second query in which each content term is joined by its nearest neighbours in
  the corpus's word-association space (`word_neighbours.json`, built from PPMI/SVD vectors), which finds
  paraphrases such as colour/color or founded/established.

Every row says where it came from (`source`) so the scorer can weigh it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from crms_intent_rules import words
from crms_responsiveness import _loose, question_terms

NEIGHBOURS_FILE = Path(__file__).resolve().parent / "corpus" / "phase13_model" / "word_neighbours.json"
_neighbours: dict[str, dict[str, float]] | None = None
_QUESTION_WORDS = frozenset({"what", "who", "when", "where", "why", "how", "which", "whom", "whose", "is",
                             "are", "was", "were", "did", "does", "do", "name", "list", "in", "on", "at"})


def neighbours() -> Mapping[str, Mapping[str, float]]:
    global _neighbours
    if _neighbours is None:
        _neighbours = (json.loads(NEIGHBOURS_FILE.read_text(encoding="utf-8"))
                       if NEIGHBOURS_FILE.is_file() else {})
    return _neighbours


def set_neighbours(table: Mapping[str, Mapping[str, float]] | None) -> None:
    global _neighbours
    _neighbours = {k: dict(v) for k, v in (table or {}).items()}


def entity_phrases(question: str) -> list[str]:
    """Runs of capitalised words after the first word, longest first (the candidate page titles)."""
    toks = question.replace("’", "'").replace("?", " ").split()
    runs, cur = [], []
    for i, t in enumerate(toks):
        bare = t.strip(",.;:!\"'()")
        if i > 0 and bare[:1].isupper() and bare.casefold() not in _QUESTION_WORDS:
            cur.append(bare)
        else:
            if cur:
                runs.append(" ".join(cur))
            cur = []
    if cur:
        runs.append(" ".join(cur))
    return sorted(set(runs), key=lambda r: (-len(r.split()), r))


def expansion_query(question: str, per_term: int = 2, floor: float = 0.6) -> str | None:
    """The question plus nearest neighbours of its content terms, or None when nothing is added."""
    _wh, terms, _entity = question_terms(question)
    add: list[str] = []
    table = neighbours()
    for term in terms:
        for word, sim in list(table.get(term, {}).items())[:per_term]:
            if sim >= floor and word not in terms and word not in add:
                add.append(word)
    return (question + " " + " ".join(add)) if add else None


def page_rows(index: Any, question: str, sentence_spans, limit: int = 12) -> list[dict[str, Any]]:
    """Sentences of the entity's own page that share a content term with the question."""
    _wh, terms, _entity = question_terms(question)
    stems = {_loose(t) for t in terms}
    for phrase in entity_phrases(question)[:3]:
        for candidate in (phrase, "The " + phrase):
            try:
                hits = index.exact_title_matches(candidate)
            except Exception:
                hits = []
            if len(hits) == 1:
                document = index.document(hits[0].document_id)
                out: list[dict[str, Any]] = []
                for position, (a, b) in enumerate(sentence_spans(document.text)[:80]):
                    sentence = document.text[a:b].strip().split("\n")[-1].strip()
                    if len(sentence) < 25 or sentence[-1:] not in ".!?":
                        continue
                    if {_loose(w) for w in words(sentence)} & stems:
                        out.append({"text": sentence, "title": document.title, "source": "page",
                                    "page_pos": position, "document_id": hits[0].document_id})
                    if len(out) >= limit:
                        break
                return out
    return []
