"""Deterministic, source-verifiable retrieval over supplied documents."""

from __future__ import annotations

import json
import hashlib
from html.parser import HTMLParser
import math
import os
import posixpath
import re
import shutil
import sqlite3
import subprocess
import zipfile
import xml.etree.ElementTree as ElementTree
from contextlib import contextmanager, nullcontext
from collections import Counter
from dataclasses import asdict, dataclass
from bisect import bisect_left
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen
from crms_text import word_matches


# Function words contribute little to document selection and can make a query
# such as "what is the capital of France" match almost the whole corpus.
_RESEARCH_STOPWORDS = frozenset({
    "a", "an", "and", "am", "are", "as", "at", "be", "by", "did", "do",
    "can", "could", "does", "for", "from", "had", "has", "have",
    "how", "i", "in", "is", "it", "may", "might", "must", "of",
    "on", "or", "should", "that", "the", "this", "to", "was", "were",
    "these", "those", "they", "them", "their",
    "what",
    "when", "where", "which", "who", "whom", "why", "will", "with",
    "would",
})
_SOURCE_METADATA_LINE = re.compile(
    r"^\s*(?:source|metadata\s+license|title|authors|license):\s*",
    re.IGNORECASE)
_STRUCTURED_SOURCE_QUERY = re.compile(
    r"\b(?:table|figure|fig\.?|caption|rows?|columns?)\b",
    re.IGNORECASE)
_STRUCTURAL_LABEL = re.compile(
    r"(?im)^\s*(?:Fig(?:ure)?\.?|Table)\s+\d+[a-z]?\s*$")
_INFOBOX_PREFIX = re.compile(r"(?im)^\s*Infobox\b")
_NONPROSE_SECTION = re.compile(
    r"(?im)^\s*(?:references|external links|other websites|"
    r"further reading|see also)\s*(?:\n|$)")


def _is_imported_structured_metadata(text: str) -> bool:
    """Reject normalized infobox/property dumps where prose is expected."""
    if (_INFOBOX_PREFIX.search(text)
            or _NONPROSE_SECTION.search(text)):
        return True
    # Several normalized wiki properties may be joined into one sentence-like
    # span because they lack terminal punctuation. A single equals sign can be
    # ordinary prose or math; repeated field assignments indicate metadata.
    return len(re.findall(r"(?m)^\s*[\w -]{1,48}\s*=\s*\S", text)) >= 2
_CODE_SOURCE_SUFFIXES = frozenset({
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h",
    ".cpp", ".hpp", ".rs", ".go", ".rb", ".php", ".sh", ".sql",
})
_CODE_QUERY_CUES = frozenset({
    "code", "coding", "program", "programming", "syntax", "module",
    "class", "method", "function", "script", "compile",
    "debug", "variable", "package", "library", "api",
})
_CODE_INTENT_CUES = frozenset({
    "code", "coding", "programming", "syntax", "compile", "debug",
    "variable", "api",
})
_PROGRAMMING_LANGUAGES = frozenset({
    "python", "javascript", "typescript", "java", "c", "cpp", "rust",
    "go", "ruby", "php", "swift", "kotlin", "sql",
})
_QUESTION_STARTERS = frozenset({
    "who", "whom", "what", "how", "why", "where", "when", "which",
    # Include yes/no forms as natural-language questions too. Without these,
    # a query like "Is Sydney the capital of Australia?" bypasses the prose
    # preference and can surface a matching assertion from a Python test.
    "am", "are", "can", "could", "did", "do", "does", "had", "has",
    "have", "is", "may", "might", "must", "shall", "should", "was",
    "were", "will", "would",
})


def _is_code_source(location: str | None) -> bool:
    if not location:
        return False
    source = location.split("#", 1)[0].rsplit(": ", 1)[-1]
    return Path(source).suffix.casefold() in _CODE_SOURCE_SUFFIXES


def _prefers_prose_sources(query: str) -> bool:
    """Route natural-language questions away from code unless coding is explicit."""
    words = tuple(match.group().casefold() for match in word_matches(query))
    if not words or words[0] not in _QUESTION_STARTERS:
        return False
    return not _is_programming_query(query)


def _is_programming_query(query: str) -> bool:
    words = {match.group().casefold() for match in word_matches(query)}
    if words & _CODE_INTENT_CUES:
        return True
    if any("_" in match.group() for match in word_matches(query)):
        return True
    return bool(words & _PROGRAMMING_LANGUAGES
                and words & {"function", "method", "class", "module",
                             "script", "package", "library"})


def _research_query_terms(query: str) -> tuple[str, ...]:
    terms = tuple(dict.fromkeys(
        match.group().casefold() for match in word_matches(query)))
    content = tuple(term for term in terms if term not in _RESEARCH_STOPWORDS)
    # Short and purely functional queries still need a useful literal search.
    return content or terms


def _research_query_focus_terms(query: str) -> frozenset[str]:
    """Return a narrow predicate focus for object-wh modal questions.

    In ``What can SUBJECT VERB?`` the final content word is the requested
    relation. Giving it extra retrieval weight helps distinguish a sentence
    that states what the predicate does from a nearby sentence that only
    repeats the subject phrase. This is a ranking cue, not a semantic alias.
    """
    words = tuple(match.group().casefold() for match in word_matches(query))
    if (len(words) < 4 or words[0] != "what"
            or words[1] not in {"can", "could", "did", "do", "does",
                               "may", "might", "must", "should", "will",
                               "would"}):
        return frozenset()
    predicate = words[-1]
    if predicate in _RESEARCH_STOPWORDS:
        return frozenset()
    # Keep this inference conservative. These productive endings strongly
    # suggest a lexical verb in the final predicate slot; other forms retain
    # ordinary term weighting until CRMS has POS evidence for them.
    if predicate.endswith(("ate", "ify", "ise", "ize")):
        return frozenset({predicate})
    return frozenset()


_NON_TERMINAL_ABBREVIATIONS = {
    "capt", "col", "dr", "gen", "gov", "lt", "mt", "mr", "mrs", "ms",
    "prof", "rep", "rev", "sen", "sgt", "st",
}
_ABBREVIATION_FOLLOWING_PROPER_NOUN = re.compile(
    r"\s+([A-Z][\w’'-]*)\b")


def _is_sentence_boundary(text: str, index: int) -> bool:
    """Return whether punctuation at index ends a sentence.

    Keep common title and place abbreviations attached to a following
    capitalized word (``Dr. Lovelace``, ``St. Petersburg``). This is a
    mechanical boundary rule; it does not parse the sentence meaning.
    """
    if not 0 <= index < len(text) or text[index] not in ".!?":
        return False
    if text[index] != ".":
        return True
    previous_is_digit = index > 0 and text[index - 1].isdigit()
    next_is_digit = index + 1 < len(text) and text[index + 1].isdigit()
    if previous_is_digit and next_is_digit:
        return False
    token_match = re.search(r"([A-Za-z]+)$", text[max(0, index - 8):index])
    if (token_match is not None
            and token_match.group(1).casefold()
                in _NON_TERMINAL_ABBREVIATIONS):
        next_word = _ABBREVIATION_FOLLOWING_PROPER_NOUN.match(text, index + 1)
        if next_word is not None:
            return False
    return True


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """Find conservative sentence spans without splitting dotted IDs/decimals."""
    spans: list[tuple[int, int]] = []
    start = 0

    def append(end: int) -> None:
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            spans.append((left, right))

    for index, character in enumerate(text):
        if character == "\n":
            # Markdown and many plain-text sources wrap a single sentence at
            # line boundaries. Do not turn a lower-case continuation (often
            # following a colon or comma) into a standalone sentence. Empty
            # lines and explicit structural markers still split paragraphs.
            previous = text[start:index].rstrip()
            following = text[index + 1:].lstrip()
            line_start = text.rfind("\n", start, index) + 1
            started_after_sentence = start > line_start
            if (previous and following
                    and previous[-1] not in ".!?"
                    and (following[0].islower() or started_after_sentence)):
                continue
            append(index)
            start = index + 1
            continue
        if character not in ".!?":
            continue
        end = index + 1
        while end < len(text) and text[end] in "\"'”’)]}":
            end += 1
        next_is_boundary = end == len(text) or text[end].isspace()
        if not next_is_boundary:
            continue
        # Keep decimal points, dotted numeric identifiers, and common
        # abbreviations intact while still allowing sentence-final numbers.
        if not _is_sentence_boundary(text, index):
            continue
        append(end)
        start = end
    append(len(text))
    return spans


def _sentence_span_at(text: str, position: int,
                      lower_bound: int = 0) -> tuple[int, int]:
    """Return the conservative sentence span containing one character offset.

    Unlike ``_sentence_spans``, this searches only around a matched term. Large
    source documents can contain millions of characters, while a search hit
    usually needs only a handful of local sentence boundaries.
    """
    start = lower_bound
    cursor = position - 1
    while cursor >= 0:
        boundary = max(text.rfind("\n", lower_bound, cursor + 1),
                       text.rfind(".", lower_bound, cursor + 1),
                       text.rfind("!", lower_bound, cursor + 1),
                       text.rfind("?", lower_bound, cursor + 1))
        if boundary < 0:
            break
        if text[boundary] == "\n":
            line_start = text.rfind("\n", lower_bound, boundary) + 1
            line_text = text[line_start:boundary].rstrip()
            following = text[boundary + 1:].lstrip()
            last_sentence_mark = max(
                text.rfind(".", line_start, boundary),
                text.rfind("!", line_start, boundary),
                text.rfind("?", line_start, boundary))
            # A line can contain the end of one sentence followed by the
            # beginning of another that wraps onto the next physical line.
            # Keep that trailing sentence together (for example, "Create one
            # portable\\nSQLite model ...") while retaining the punctuation
            # boundary before it.
            continued_by_lowercase = (
                bool(line_text and following)
                and line_text[-1] not in ".!?"
                and following[0].islower())
            if (line_text and (last_sentence_mark >= line_start
                               or continued_by_lowercase)):
                cursor = boundary - 1
                continue
            start = boundary + 1
            break
        if not _is_sentence_boundary(text, boundary):
            cursor = boundary - 1
            continue
        end = boundary + 1
        while end < len(text) and text[end] in "\"'”’)]}":
            end += 1
        if end > position:
            break
        if (end == len(text) or text[end].isspace()) and not (
                text[boundary] == "." and boundary > 0
                and boundary + 1 < len(text)
                and text[boundary - 1].isdigit()
                and text[boundary + 1].isdigit()):
            start = end
            break
        cursor = boundary - 1

    end = len(text)
    cursor = position
    while cursor < len(text):
        boundary = min((found for found in (
            text.find("\n", cursor), text.find(".", cursor),
            text.find("!", cursor), text.find("?", cursor)) if found >= 0),
            default=-1)
        if boundary < 0:
            break
        if text[boundary] == "\n":
            end = boundary
            break
        if not _is_sentence_boundary(text, boundary):
            cursor = boundary + 1
            continue
        sentence_end = boundary + 1
        while sentence_end < len(text) and text[sentence_end] in "\"'”’)]}":
            sentence_end += 1
        if (sentence_end == len(text) or text[sentence_end].isspace()) and not (
                text[boundary] == "." and boundary > 0
                and boundary + 1 < len(text)
                and text[boundary - 1].isdigit()
                and text[boundary + 1].isdigit()):
            end = sentence_end
            break
        cursor = boundary + 1
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _sentence_context_kind(sentence: str, document_text: str,
                           sentence_start: int) -> str:
    """Classify obvious illustrative examples separately from assertions."""
    if len(re.findall(r"```", document_text[:sentence_start])) % 2:
        return "example"
    if (re.match(r"\s*(?:=>|->|assert\b|return\b)", sentence)
            or sentence.count("|") >= 2):
        return "example"
    if (re.match(r"\s*\d+[.)]\s+\*\*[^*]+\*\*", sentence)
            or re.search(r"\b(?:who|what|where)\s+_{2,}", sentence,
                         re.IGNORECASE)):
        return "example"
    if re.search(r"\b(?:can|could|may)\s+extend\s+to\b", sentence,
                 re.IGNORECASE):
        return "example"
    quoted_questions = re.findall(
        r"`([^`]{1,240}\?)`|[\"“‘]([^\"”’]{1,240}\?)[\"”’]",
        sentence)
    metalinguistic_cues = re.compile(
        r"\b(?:question|query|route|sentence|pattern|frame|template|"
        r"retrieve|retrieval|example|ask|wording)\b", re.IGNORECASE)
    if (quoted_questions and metalinguistic_cues.search(sentence)
            and any(re.match(
                r"\s*(?:who|whom|what|which|where|when|why|how|is|are|"
                r"was|were|do|does|did|can|could|will|would)\b",
                first or second, flags=re.IGNORECASE)
                    for first, second in quoted_questions)):
        return "example"
    example_marker = re.compile(
        r"\b(?:such\s+as|for\s+example|e\.g\.?)\b", re.IGNORECASE)
    if re.search(example_marker.pattern + r"[^.!?]*[\"'“‘]",
                  sentence, re.IGNORECASE):
        return "example"
    prefix = document_text[max(0, sentence_start - 200):sentence_start]
    markers = list(example_marker.finditer(prefix))
    if markers:
        after_marker = prefix[markers[-1].end():]
        if not re.search(r"[.!?][\"'”’)]*\s", after_marker):
            return "example"
    return "assertion"


def _in_figure_caption(document_text: str, sentence_start: int) -> bool:
    """Detect text in the bounded block following a standalone figure label."""
    # Look slightly ahead because the sentence splitter treats the period in
    # the abbreviation ``Fig.`` as sentence punctuation and may start the next
    # span at the figure number itself.
    lookahead_end = min(len(document_text), sentence_start + 64)
    markers = [marker for marker in
               _STRUCTURAL_LABEL.finditer(document_text[:lookahead_end])
               if marker.start() <= sentence_start]
    if not markers:
        return False
    marker = markers[-1]
    if not marker.group().lstrip().casefold().startswith(("fig", "figure")):
        return False
    # JATS flattening can leave the caption and following body text on
    # adjacent single-newline blocks. The next figure/table label closes the
    # caption; the distance cap prevents a missing label from swallowing prose.
    return sentence_start - marker.end() <= 3_000


class _ReadableHTML(HTMLParser):
    """Extract visible page text and its title without executing page code."""

    _BLOCKS = {"article", "br", "dd", "div", "dt", "h1", "h2", "h3",
               "h4", "h5", "h6", "li", "main", "p", "section", "tr"}
    _IGNORED = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._ignored = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and self._ignored == 0:
            href = next((value for name, value in attrs
                         if name.casefold() == "href" and value), None)
            if href:
                self.links.append(href)
        if tag in self._IGNORED:
            self._ignored += 1
        elif tag == "title":
            self._in_title = True
        elif self._ignored == 0 and tag in self._BLOCKS:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED and self._ignored:
            self._ignored -= 1
        elif tag == "title":
            self._in_title = False
        elif self._ignored == 0 and tag in self._BLOCKS:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._ignored == 0 and not self._in_title:
            self.text_parts.append(data)


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _extract_readable_html(source: str) -> tuple[str, str]:
    parser = _ReadableHTML()
    parser.feed(source)
    title = " ".join(" ".join(parser.title_parts).split())
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(parser.text_parts))
    text = re.sub(r" *\n+ *", "\n", text).strip()
    if not text:
        raise ValueError("HTML source contains no readable text")
    return title, text


def _xml_child_text(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == name and element.text:
            value = element.text.strip()
            if value:
                return value
    return None


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    title: str
    text: str
    location: str | None = None
    pages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchHit:
    document_id: str
    title: str
    location: str | None
    score: float
    snippet: str
    start: int
    end: int
    matched_terms: tuple[str, ...]
    page_number: int | None = None
    match_start: int | None = None
    match_end: int | None = None


@dataclass(frozen=True)
class ExactTitleMatch:
    """A source whose title token sequence exactly matches a requested name."""

    document_id: str
    title: str
    location: str | None


@dataclass(frozen=True)
class LatestSearchHit:
    """A lexically matched source with an explicit publication date."""

    hit: SearchHit
    publication_date: str


@dataclass(frozen=True)
class SiteCrawlResult:
    captured: tuple[str, ...]
    visited: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DirectoryIngestResult:
    added: tuple[str, ...]
    skipped: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SummarySentence:
    """One extractive sentence with an exact citation to supplied text."""

    text: str
    citation: str
    document_id: str
    title: str
    location: str | None
    score: float
    matched_terms: tuple[str, ...]
    page_number: int | None = None
    context_kind: str = "assertion"


def _render_pipe_table(source_text: str) -> list[str] | None:
    """Render a flattened JATS table as Markdown while retaining cell wording."""
    lines = source_text.splitlines()
    header_index = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        if len(cells) >= 2:
            header_index, headers = index, cells
            break
    if header_index is None:
        return None

    rows: list[list[str]] = []
    current: list[str] | None = None

    def finish_row() -> None:
        nonlocal current
        if current is not None and any(current):
            rows.append(current)
        current = None

    for line in lines[header_index + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if "|" in line:
            raw_cells = [cell.strip() for cell in line.split("|")]
            interior = (raw_cells[1:-1]
                        if line.lstrip().startswith("|")
                        and line.rstrip().endswith("|") else raw_cells)
            first_cell = interior[0] if interior else ""
            cells = [cell for cell in interior if cell]
            if first_cell:
                finish_row()
                current = [first_cell]
                current.extend(cells[1:])
                current = (current + [""] * len(headers))[:len(headers)]
            elif current is not None:
                for cell in cells:
                    empty_index = next((position for position in
                                        range(len(current) - 1, 0, -1)
                                        if not current[position]), None)
                    if empty_index is None:
                        current[-1] = (current[-1] + "<br>" + cell
                                       if current[-1] else cell)
                    else:
                        current[empty_index] = cell
            continue
        if current is None:
            continue
        if current[-1]:
            finish_row()
            break
        middle_index = max(1, len(current) - 2)
        current[middle_index] = (
            current[middle_index] + "<br>" + stripped
            if current[middle_index] else stripped)
    finish_row()
    if not rows:
        return None

    preamble = [line.strip() for line in lines[:header_index] if line.strip()]
    rendered = []
    if preamble:
        rendered.append("### " + preamble[0])
        rendered.extend(preamble[1:])
    rendered.append("| " + " | ".join(headers) + " |")
    rendered.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        padded = (row + [""] * len(headers))[:len(headers)]
        rendered.append("| " + " | ".join(padded) + " |")
    return rendered


@dataclass(frozen=True)
class ExtractiveSummary:
    query: str
    sentences: tuple[SummarySentence, ...]
    expansion_licenses: tuple[dict[str, Any], ...] = ()

    def render(self) -> str:
        if not self.sentences:
            return f"No supplied source sentences matched: {self.query}"
        lines = [f"Extractive summary for: {self.query}"]
        lines.append("Selected source sentences; wording is unchanged from the sources.")
        if self.expansion_licenses:
            lines.append("Grounded query expansions used:")
            for license_record in self.expansion_licenses:
                attribution = []
                if license_record.get("sources"):
                    attribution.append(
                        "sources: " + ", ".join(license_record["sources"]))
                if license_record.get("rules"):
                    attribution.append(
                        "rules: " + ", ".join(license_record["rules"]))
                details = f" [{'; '.join(attribution)}]" if attribution else ""
                lines.append(
                    f"- {license_record.get('kind', 'licensed')}: "
                    f"{license_record.get('evidence', '')} → "
                    f"{license_record.get('text', '')}{details}")
        for sentence in self.sentences:
            label = sentence.title
            if sentence.location:
                label += f" ({sentence.location})"
            if sentence.page_number is not None:
                label += f", page {sentence.page_number}"
            if sentence.context_kind == "table":
                table_lines = _render_pipe_table(sentence.text)
                if table_lines:
                    lines.extend(table_lines)
                    lines.append(
                        f"[Source: {label}; {sentence.citation}]")
                    continue
            context = ("; illustrative example, not an asserted fact"
                       if sentence.context_kind == "example" else "")
            lines.append(
                f"- {sentence.text} [{label}{context}; {sentence.citation}]")
        return "\n".join(lines)


class CRMSResearchIndex:
    """Index supplied document text with lexical ranking and exact citations.

    This is retrieval rather than a fact generator. Returned snippets are exact
    character slices from the indexed source and include their source offsets.
    """

    FORMAT_VERSION = 1
    DIRECTORY_BATCH_SIZE = 256

    def __init__(self) -> None:
        self._documents: dict[str, SourceDocument] = {}
        self._body_spans: dict[str, list[tuple[str, int, int]]] = {}
        self._body_counts: dict[str, Counter[str]] = {}
        self._title_terms: dict[str, set[str]] = {}
        self._postings: dict[str, set[str]] = {}
        self._title_postings: dict[str, set[str]] = {}

    def document_count(self) -> int:
        """Return the number of indexed documents."""
        return len(self._documents)

    def _bulk_write_context(self):
        """Context used to group directory ingestion writes when available."""
        return nullcontext()

    def _source_file_is_current(self, path: Path, document_id: str, *,
                                verify_content: bool = False) -> bool:
        return (self.contains_document(document_id)
                and not verify_content)

    def _record_source_file(self, path: Path, document_id: str) -> None:
        return None

    def add_document(self, document_id: str, title: str, text: str,
                     location: str | None = None, *, replace: bool = False,
                     pages: Iterable[str] | None = None) -> None:
        document_id = _text(document_id, "document_id")
        title = _text(title, "title")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if location is not None:
            location = _text(location, "location")
        page_text = tuple(pages or ())
        if any(not isinstance(page, str) for page in page_text):
            raise ValueError("pages must contain only strings")
        if page_text and "\n\f\n".join(page_text) != text:
            raise ValueError("joined page text must match document text exactly")
        if document_id in self._documents and not replace:
            raise ValueError("document_id already exists; pass replace=True to replace it")
        old_counts = self._body_counts.get(document_id, Counter())
        for term in old_counts:
            posting = self._postings.get(term)
            if posting is not None:
                posting.discard(document_id)
                if not posting:
                    self._postings.pop(term, None)
        for term in self._title_terms.get(document_id, set()):
            posting = self._title_postings.get(term)
            if posting is not None:
                posting.discard(document_id)
                if not posting:
                    self._title_postings.pop(term, None)
        self._documents[document_id] = SourceDocument(
            document_id, title, text, location, page_text)
        spans = self._token_spans(text)
        counts = Counter(token for token, _, _ in spans)
        self._body_spans[document_id] = spans
        self._body_counts[document_id] = counts
        self._title_terms[document_id] = {
            token for token, _, _ in self._token_spans(title)}
        for term in self._title_terms[document_id]:
            self._title_postings.setdefault(term, set()).add(document_id)
        for term in counts:
            self._postings.setdefault(term, set()).add(document_id)

    def add_file(self, path: str | Path, *, document_id: str | None = None,
                 title: str | None = None, location: str | None = None,
                 replace: bool = False) -> None:
        """Index one explicitly supplied text, table, web, chat, or office source."""
        source_path = Path(path)
        if source_path.suffix.casefold() == ".pdf":
            self.add_pdf(source_path, document_id=document_id, title=title,
                         location=location, replace=replace)
            return
        if source_path.suffix.casefold() == ".epub":
            self.add_epub(source_path, document_id=document_id, title=title,
                          location=location, replace=replace)
            return
        if source_path.suffix.casefold() == ".docx":
            extracted_title, content = self._read_docx(source_path)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() == ".odt":
            extracted_title, content = self._read_odt(source_path)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() == ".xlsx":
            extracted_title, content = self._read_xlsx(source_path)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() == ".pptx":
            extracted_title, content = self._read_pptx(source_path)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() == ".json":
            extracted_title, content = self._read_chat_export(source_path)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() in {".html", ".htm", ".xhtml"}:
            source = source_path.read_text(encoding="utf-8")
            extracted_title, content = _extract_readable_html(source)
            self.add_document(
                document_id or str(source_path),
                title or extracted_title or source_path.name, content,
                location or str(source_path), replace=replace)
            return
        if source_path.suffix.casefold() not in {
                ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv"}:
            raise ValueError(
                "supported local source files are text/markup, CSV/TSV, XLSX/PPTX, HTML, "
                "ChatGPT JSON, DOCX, ODT, EPUB, and PDF")
        content = source_path.read_text(encoding="utf-8-sig")
        self.add_document(
            document_id or str(source_path), title or source_path.name, content,
            location or str(source_path), replace=replace)

    @staticmethod
    def _read_docx(path: Path) -> tuple[str, str]:
        """Extract visible paragraphs and table text from a DOCX file."""
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"could not open DOCX archive: {error}") from error
        with archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ValueError("DOCX contains too many archive entries")
            if sum(member.file_size for member in members) > 512 * 1024 * 1024:
                raise ValueError("DOCX expands beyond the 512 MiB ingestion limit")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted DOCX entries are not supported")
            by_name = {member.filename: member for member in members}

            def read_member(name: str, max_bytes: int) -> bytes | None:
                member = by_name.get(name)
                if member is None:
                    return None
                if member.is_dir() or member.file_size > max_bytes:
                    raise ValueError(f"DOCX entry exceeds the size limit: {name}")
                return archive.read(member)

            body = read_member("word/document.xml", 128 * 1024 * 1024)
            if body is None:
                raise ValueError("DOCX is missing word/document.xml")
            try:
                document = ElementTree.fromstring(body)
                properties_data = read_member("docProps/core.xml", 4_000_000)
                properties = (ElementTree.fromstring(properties_data)
                              if properties_data is not None else None)
            except ElementTree.ParseError as error:
                raise ValueError("DOCX XML is malformed") from error
            paragraphs = []
            for paragraph in document.iter():
                if paragraph.tag.rsplit("}", 1)[-1] != "p":
                    continue
                parts = []
                for element in paragraph.iter():
                    local_name = element.tag.rsplit("}", 1)[-1]
                    if local_name == "t" and element.text:
                        parts.append(element.text)
                    elif local_name == "tab":
                        parts.append("\t")
                    elif local_name in {"br", "cr"}:
                        parts.append("\n")
                text = "".join(parts).strip()
                if text:
                    paragraphs.append(text)
            content = "\n".join(paragraphs)
            if not content:
                raise ValueError("DOCX contains no extractable document text")
            title = (_xml_child_text(properties, "title")
                     if properties is not None else None)
            return title or "", content

    @staticmethod
    def _read_odt(path: Path) -> tuple[str, str]:
        """Extract headings, paragraphs, and table-cell text from an ODT file."""
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"could not open ODT archive: {error}") from error
        with archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ValueError("ODT contains too many archive entries")
            if sum(member.file_size for member in members) > 512 * 1024 * 1024:
                raise ValueError("ODT expands beyond the 512 MiB ingestion limit")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted ODT entries are not supported")
            by_name = {member.filename: member for member in members}

            def read_member(name: str, max_bytes: int) -> bytes | None:
                member = by_name.get(name)
                if member is None:
                    return None
                if member.is_dir() or member.file_size > max_bytes:
                    raise ValueError(f"ODT entry exceeds the size limit: {name}")
                return archive.read(member)

            body = read_member("content.xml", 128 * 1024 * 1024)
            if body is None:
                raise ValueError("ODT is missing content.xml")
            try:
                content_root = ElementTree.fromstring(body)
                metadata_data = read_member("meta.xml", 4_000_000)
                metadata = (ElementTree.fromstring(metadata_data)
                            if metadata_data is not None else None)
            except ElementTree.ParseError as error:
                raise ValueError("ODT XML is malformed") from error

            paragraphs = []
            for paragraph in content_root.iter():
                if paragraph.tag.rsplit("}", 1)[-1] not in {"p", "h"}:
                    continue
                parts = []

                def append_element_text(element: ElementTree.Element) -> None:
                    local_name = element.tag.rsplit("}", 1)[-1]
                    if local_name == "s":
                        count_text = next((value for name, value
                                           in element.attrib.items()
                                           if name.rsplit("}", 1)[-1] == "c"), None)
                        try:
                            count = int(count_text) if count_text is not None else 1
                        except ValueError as error:
                            raise ValueError("ODT contains an invalid repeated-space count") from error
                        if not 1 <= count <= 10_000:
                            raise ValueError("ODT repeated-space count exceeds the limit")
                        parts.append(" " * count)
                    elif local_name == "tab":
                        parts.append("\t")
                    elif local_name in {"line-break", "soft-page-break"}:
                        parts.append("\n")
                    else:
                        if element.text:
                            parts.append(element.text)
                        for child in element:
                            append_element_text(child)
                            if child.tail:
                                parts.append(child.tail)

                append_element_text(paragraph)
                text = "".join(parts).strip()
                if text:
                    paragraphs.append(text)
            extracted_text = "\n".join(paragraphs)
            if not extracted_text:
                raise ValueError("ODT contains no extractable document text")
            title = (_xml_child_text(metadata, "title")
                     if metadata is not None else None)
            return title or "", extracted_text

    @staticmethod
    def _read_xlsx(path: Path) -> tuple[str, str]:
        """Extract worksheet headers and values from an OOXML workbook."""
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"could not open XLSX archive: {error}") from error
        with archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ValueError("XLSX contains too many archive entries")
            if sum(member.file_size for member in members) > 512 * 1024 * 1024:
                raise ValueError("XLSX expands beyond the 512 MiB ingestion limit")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted XLSX entries are not supported")
            by_name = {member.filename: member for member in members}

            def read_member(name: str, max_bytes: int) -> bytes | None:
                member = by_name.get(name)
                if member is None:
                    return None
                if member.is_dir() or member.file_size > max_bytes:
                    raise ValueError(f"XLSX entry exceeds the size limit: {name}")
                return archive.read(member)

            workbook_data = read_member("xl/workbook.xml", 16 * 1024 * 1024)
            relationships_data = read_member(
                "xl/_rels/workbook.xml.rels", 16 * 1024 * 1024)
            if workbook_data is None or relationships_data is None:
                raise ValueError("XLSX is missing workbook metadata")
            try:
                workbook = ElementTree.fromstring(workbook_data)
                relationships = ElementTree.fromstring(relationships_data)
                shared_data = read_member("xl/sharedStrings.xml", 128 * 1024 * 1024)
                shared_root = (ElementTree.fromstring(shared_data)
                               if shared_data is not None else None)
                properties_data = read_member("docProps/core.xml", 4_000_000)
                properties = (ElementTree.fromstring(properties_data)
                              if properties_data is not None else None)
            except ElementTree.ParseError as error:
                raise ValueError("XLSX XML is malformed") from error

            relationship_targets = {}
            for relation in relationships.iter():
                if relation.tag.rsplit("}", 1)[-1] != "Relationship":
                    continue
                rel_id = relation.attrib.get("Id")
                target = relation.attrib.get("Target")
                if (not rel_id or not target
                        or relation.attrib.get("TargetMode") == "External"):
                    continue
                target = target.lstrip("/")
                resolved = (target if target.startswith("xl/") else
                            posixpath.normpath(posixpath.join("xl", target)))
                if resolved == ".." or resolved.startswith("../"):
                    raise ValueError("XLSX worksheet path escapes the archive root")
                relationship_targets[rel_id] = resolved

            shared_strings = []
            if shared_root is not None:
                for item in shared_root.iter():
                    if item.tag.rsplit("}", 1)[-1] == "si":
                        shared_strings.append("".join(
                            child.text or "" for child in item.iter()
                            if child.tag.rsplit("}", 1)[-1] == "t"))

            def column_index(reference: str) -> int | None:
                letters = "".join(character for character in reference
                                 if character.isalpha())
                if not letters or len(letters) > 4:
                    return None
                value = 0
                for character in letters.upper():
                    value = value * 26 + ord(character) - ord("A") + 1
                return value if value <= 16_384 else None

            rendered_sheets = []
            sheet_elements = [element for element in workbook.iter()
                              if element.tag.rsplit("}", 1)[-1] == "sheet"]
            if len(sheet_elements) > 10_000:
                raise ValueError("XLSX contains too many worksheets")
            for sheet_number, sheet in enumerate(sheet_elements, 1):
                sheet_name = sheet.attrib.get("name", f"Sheet {sheet_number}")
                relationship_id = next((value for key, value in sheet.attrib.items()
                                        if key.rsplit("}", 1)[-1] == "id"), None)
                sheet_path = relationship_targets.get(relationship_id)
                if sheet_path is None:
                    continue
                sheet_data = read_member(sheet_path, 128 * 1024 * 1024)
                if sheet_data is None:
                    raise ValueError(f"XLSX worksheet is missing: {sheet_name}")
                try:
                    sheet_root = ElementTree.fromstring(sheet_data)
                except ElementTree.ParseError as error:
                    raise ValueError(f"XLSX worksheet XML is malformed: {sheet_name}") from error
                rows = []
                for row_number, row in enumerate(
                        (element for element in sheet_root.iter()
                         if element.tag.rsplit("}", 1)[-1] == "row"), 1):
                    if row_number > 1_048_576:
                        raise ValueError(f"XLSX worksheet has too many rows: {sheet_name}")
                    cells = {}
                    for cell in row:
                        if cell.tag.rsplit("}", 1)[-1] != "c":
                            continue
                        reference = cell.attrib.get("r", "")
                        column = column_index(reference)
                        if column is None:
                            continue
                        cell_type = cell.attrib.get("t")
                        value_node = next((child for child in cell
                                           if child.tag.rsplit("}", 1)[-1] == "v"), None)
                        value = value_node.text if value_node is not None else None
                        if cell_type == "s" and value is not None:
                            try:
                                shared_index = int(value)
                                if shared_index < 0:
                                    raise ValueError
                                value = shared_strings[shared_index]
                            except (ValueError, IndexError) as error:
                                raise ValueError(
                                    f"XLSX shared-string index is invalid in {reference}") from error
                        elif cell_type == "inlineStr":
                            value = "".join(
                                child.text or "" for child in cell.iter()
                                if child.tag.rsplit("}", 1)[-1] == "t")
                        elif cell_type == "b" and value in {"0", "1"}:
                            value = "TRUE" if value == "1" else "FALSE"
                        if value is None:
                            formula = next((child.text for child in cell
                                            if child.tag.rsplit("}", 1)[-1] == "f"), None)
                            value = f"={formula}" if formula else ""
                        cells[column] = value
                    if cells:
                        explicit_number = row.attrib.get("r")
                        try:
                            number = int(explicit_number) if explicit_number else row_number
                        except ValueError:
                            number = row_number
                        rows.append((number, cells))
                if not rows:
                    continue
                first_number, header_cells = rows[0]
                max_column = max(column for _, cells in rows
                                 for column in cells)
                headers = [header_cells.get(column, f"Column {column}").strip()
                           or f"Column {column}"
                           for column in range(1, max_column + 1)]
                lines = [f"Sheet: {sheet_name}", "Columns: " + " | ".join(headers)]
                for number, cells in rows[1:]:
                    fields = [f"{headers[column - 1]}: {value}"
                              for column, value in sorted(cells.items()) if value]
                    if fields:
                        lines.append(f"Row {number}: " + " | ".join(fields))
                rendered_sheets.append("\n".join(lines))
            if not rendered_sheets:
                raise ValueError("XLSX contains no readable worksheet data")
            title = (_xml_child_text(properties, "title")
                     if properties is not None else None)
            return title or "", "\n\n".join(rendered_sheets)

    @staticmethod
    def _read_pptx(path: Path) -> tuple[str, str]:
        """Extract slide-ordered paragraph and table text from a PPTX deck."""
        try:
            archive = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"could not open PPTX archive: {error}") from error
        with archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ValueError("PPTX contains too many archive entries")
            if sum(member.file_size for member in members) > 512 * 1024 * 1024:
                raise ValueError("PPTX expands beyond the 512 MiB ingestion limit")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted PPTX entries are not supported")
            by_name = {member.filename: member for member in members}

            def read_member(name: str, max_bytes: int) -> bytes | None:
                member = by_name.get(name)
                if member is None:
                    return None
                if member.is_dir() or member.file_size > max_bytes:
                    raise ValueError(f"PPTX entry exceeds the size limit: {name}")
                return archive.read(member)

            presentation_data = read_member("ppt/presentation.xml", 16 * 1024 * 1024)
            relationships_data = read_member(
                "ppt/_rels/presentation.xml.rels", 16 * 1024 * 1024)
            if presentation_data is None or relationships_data is None:
                raise ValueError("PPTX is missing presentation metadata")
            try:
                presentation = ElementTree.fromstring(presentation_data)
                relationships = ElementTree.fromstring(relationships_data)
                properties_data = read_member("docProps/core.xml", 4_000_000)
                properties = (ElementTree.fromstring(properties_data)
                              if properties_data is not None else None)
            except ElementTree.ParseError as error:
                raise ValueError("PPTX XML is malformed") from error

            relationship_targets = {}
            for relation in relationships.iter():
                if relation.tag.rsplit("}", 1)[-1] != "Relationship":
                    continue
                rel_id = relation.attrib.get("Id")
                target = relation.attrib.get("Target")
                if (not rel_id or not target
                        or relation.attrib.get("TargetMode") == "External"):
                    continue
                target = target.lstrip("/")
                resolved = (target if target.startswith("ppt/") else
                            posixpath.normpath(posixpath.join("ppt", target)))
                if resolved == ".." or resolved.startswith("../"):
                    raise ValueError("PPTX slide path escapes the archive root")
                relationship_targets[rel_id] = resolved

            slide_ids = [element for element in presentation.iter()
                         if element.tag.rsplit("}", 1)[-1] == "sldId"]
            if not slide_ids or len(slide_ids) > 100_000:
                raise ValueError("PPTX has no slides or exceeds its slide limit")
            rendered_slides = []
            drawing_namespace_suffix = "/drawingml/2006/main"
            for slide_number, slide_id in enumerate(slide_ids, 1):
                relationship_id = next((
                    value for key, value in slide_id.attrib.items()
                    if key.startswith("{") and key.rsplit("}", 1)[-1] == "id"),
                    None)
                slide_path = relationship_targets.get(relationship_id)
                if slide_path is None:
                    raise ValueError(f"PPTX slide {slide_number} has no internal target")
                slide_data = read_member(slide_path, 128 * 1024 * 1024)
                if slide_data is None:
                    raise ValueError(f"PPTX slide {slide_number} is missing")
                try:
                    slide_root = ElementTree.fromstring(slide_data)
                except ElementTree.ParseError as error:
                    raise ValueError(f"PPTX slide {slide_number} XML is malformed") from error
                paragraphs = []
                for paragraph in slide_root.iter():
                    namespace, _, local_name = paragraph.tag.rpartition("}")
                    if (local_name != "p"
                            or not namespace.endswith(drawing_namespace_suffix)):
                        continue
                    parts = []
                    for element in paragraph.iter():
                        child_namespace, _, child_name = element.tag.rpartition("}")
                        if not child_namespace.endswith(drawing_namespace_suffix):
                            continue
                        if child_name == "t" and element.text:
                            parts.append(element.text)
                        elif child_name == "tab":
                            parts.append("\t")
                        elif child_name == "br":
                            parts.append("\n")
                    text = "".join(parts).strip()
                    if text:
                        paragraphs.append(text)
                if paragraphs:
                    slide_title = paragraphs[0]
                    lines = [f"Slide {slide_number}: {slide_title}"]
                    lines.extend(paragraphs[1:])
                    rendered_slides.append("\n".join(lines))
            if not rendered_slides:
                raise ValueError("PPTX contains no extractable slide text")
            title = (_xml_child_text(properties, "title")
                     if properties is not None else None)
            return title or "", "\n\n".join(rendered_slides)

    @staticmethod
    def _read_chat_export(path: Path) -> tuple[str, str]:
        """Extract user and assistant turns from a ChatGPT conversations export."""
        if path.stat().st_size > 512 * 1024 * 1024:
            raise ValueError("chat export exceeds the 512 MiB ingestion limit")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"could not read chat export: {error}") from error
        if isinstance(payload, dict) and isinstance(payload.get("conversations"), list):
            conversations = payload["conversations"]
        elif isinstance(payload, list):
            conversations = payload
        elif isinstance(payload, dict) and isinstance(payload.get("mapping"), dict):
            conversations = [payload]
        else:
            raise ValueError("JSON file is not a ChatGPT conversation export")
        if not conversations or len(conversations) > 100_000:
            raise ValueError("chat export has no conversations or exceeds its conversation limit")

        def message_text(message: dict[str, Any]) -> str:
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if not isinstance(content, dict):
                return ""
            parts = content.get("parts")
            if isinstance(parts, list):
                text_parts = []
                for part in parts:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict):
                        # Text exports may wrap textual content, while image,
                        # audio, and other binary parts do not have text fields.
                        value = part.get("text")
                        if isinstance(value, str):
                            text_parts.append(value)
                return "\n".join(value for value in text_parts if value.strip()).strip()
            value = content.get("text")
            return value.strip() if isinstance(value, str) else ""

        rendered_conversations = []
        titles = []
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            mapping = conversation.get("mapping")
            ordered_messages: list[dict[str, Any]] = []
            if isinstance(mapping, dict):
                if len(mapping) > 1_000_000:
                    raise ValueError("chat conversation exceeds the message limit")
                if any(not isinstance(node, dict) for node in mapping.values()):
                    raise ValueError("chat export contains a malformed message node")
                current = conversation.get("current_node")
                if current is None:
                    parents = {node.get("parent") for node in mapping.values()}
                    leaves = sorted(set(mapping) - parents)
                    current = leaves[-1] if leaves else None
                if current is not None and not isinstance(current, str):
                    raise ValueError("chat export has an invalid current message id")
                chain = []
                seen = set()
                while current is not None:
                    if current in seen or current not in mapping:
                        raise ValueError("chat export contains an invalid message tree")
                    seen.add(current)
                    node = mapping[current]
                    message = node.get("message")
                    if isinstance(message, dict):
                        chain.append(message)
                    parent = node.get("parent")
                    if parent is not None and not isinstance(parent, str):
                        raise ValueError("chat export has an invalid parent message id")
                    current = parent
                ordered_messages = list(reversed(chain))
            elif isinstance(conversation.get("messages"), list):
                ordered_messages = [message for message in conversation["messages"]
                                    if isinstance(message, dict)]
            else:
                continue

            title = conversation.get("title")
            if isinstance(title, str) and title.strip():
                title = title.strip()
                titles.append(title)
            else:
                title = "Untitled conversation"
            lines = [f"Conversation: {title}"]
            for message in ordered_messages:
                author = message.get("author")
                role = author.get("role") if isinstance(author, dict) else None
                if role not in {"user", "assistant"}:
                    continue
                metadata = message.get("metadata")
                if isinstance(metadata, dict):
                    channel = metadata.get("channel")
                    message_type = metadata.get("message_type")
                    if channel == "analysis" or message_type == "analysis":
                        continue
                text = message_text(message)
                if text:
                    lines.append(f"{role.capitalize()}: {text}")
            if len(lines) > 1:
                rendered_conversations.append("\n".join(lines))
        if not rendered_conversations:
            raise ValueError("chat export contains no readable user/assistant turns")
        archive_title = (f"Chat export ({len(rendered_conversations)} conversations)"
                         if not titles else
                         titles[0] if len(titles) == 1 else
                         f"Chat export ({len(rendered_conversations)} conversations)")
        return archive_title, "\n\n".join(rendered_conversations)

    def add_epub(self, path: str | Path, *, document_id: str | None = None,
                 title: str | None = None, location: str | None = None,
                 replace: bool = False) -> None:
        """Index readable EPUB chapters in declared spine order."""
        source_path = Path(path)
        try:
            archive = zipfile.ZipFile(source_path)
        except (OSError, zipfile.BadZipFile) as error:
            raise ValueError(f"could not open EPUB archive: {error}") from error
        with archive:
            members = archive.infolist()
            if len(members) > 100_000:
                raise ValueError("EPUB contains too many archive entries")
            if sum(member.file_size for member in members) > 512 * 1024 * 1024:
                raise ValueError("EPUB expands beyond the 512 MiB ingestion limit")
            if any(member.flag_bits & 0x1 for member in members):
                raise ValueError("encrypted EPUB entries are not supported")
            member_by_name = {member.filename: member for member in members}

            def read_member(name: str, max_bytes: int = 128 * 1024 * 1024) -> bytes:
                member = member_by_name.get(name)
                if member is None or member.is_dir():
                    raise ValueError(f"EPUB is missing required entry: {name}")
                if member.file_size > max_bytes:
                    raise ValueError(f"EPUB entry exceeds the size limit: {name}")
                return archive.read(member)

            try:
                container = ElementTree.fromstring(
                    read_member("META-INF/container.xml", 1_000_000))
            except ElementTree.ParseError as error:
                raise ValueError("EPUB container.xml is malformed") from error
            rootfile = next((element.attrib.get("full-path")
                             for element in container.iter()
                             if element.tag.rsplit("}", 1)[-1] == "rootfile"
                             and element.attrib.get("full-path")), None)
            if not rootfile or rootfile.startswith("/"):
                raise ValueError("EPUB does not identify a valid package document")
            package_name = posixpath.normpath(rootfile)
            if package_name.startswith("../") or package_name == "..":
                raise ValueError("EPUB package path escapes the archive root")
            try:
                package = ElementTree.fromstring(
                    read_member(package_name, 8_000_000))
            except ElementTree.ParseError as error:
                raise ValueError("EPUB package document is malformed") from error

            manifest: dict[str, str] = {}
            for element in package.iter():
                if element.tag.rsplit("}", 1)[-1] != "item":
                    continue
                item_id = element.attrib.get("id")
                href = element.attrib.get("href")
                media_type = element.attrib.get("media-type", "").casefold()
                if (not item_id or not href or media_type not in {
                        "application/xhtml+xml", "text/html"}):
                    continue
                href = href.split("#", 1)[0].split("?", 1)[0]
                resolved = posixpath.normpath(posixpath.join(
                    posixpath.dirname(package_name), href))
                if resolved.startswith("../") or resolved == "..":
                    continue
                manifest[item_id] = resolved
            chapter_names = []
            for element in package.iter():
                if element.tag.rsplit("}", 1)[-1] == "itemref":
                    chapter = manifest.get(element.attrib.get("idref", ""))
                    if chapter and chapter not in chapter_names:
                        chapter_names.append(chapter)
            if not chapter_names:
                raise ValueError("EPUB reading order contains no HTML chapters")

            chapters = []
            for chapter_name in chapter_names:
                try:
                    chapter_html = read_member(chapter_name).decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError(
                        f"EPUB chapter is not UTF-8: {chapter_name}") from error
                _chapter_title, chapter_text = _extract_readable_html(chapter_html)
                chapters.append(chapter_text)
            metadata_title = _xml_child_text(package, "title")
            self.add_document(
                document_id or str(source_path),
                title or metadata_title or source_path.stem,
                "\n\n".join(chapters), location or str(source_path),
                replace=replace)

    def add_url(self, url: str, *, replace: bool = False,
                timeout: float = 10.0, max_bytes: int = 2_000_000) -> None:
        """Capture one explicitly supplied HTTP(S) page as a local snapshot.

        The fetched page is never treated as a fact. Search citations resolve
        against the stored text snapshot and retain the page URL as location.
        Scripts and other non-readable HTML sections are discarded.
        """
        url = _text(url, "url")
        title, text, final_url, _links = self._capture_url(
            url, timeout=timeout, max_bytes=max_bytes)
        self.add_document(url, title, text, final_url, replace=replace)

    def add_site(self, url: str, *, max_pages: int = 10, max_depth: int = 1,
                 timeout: float = 10.0,
                 max_bytes_per_page: int = 2_000_000) -> SiteCrawlResult:
        """Capture a bounded same-origin set of linked HTML pages.

        Crawling is explicit, follows only HTTP(S) links on the starting
        origin, and keeps every page as a separate source document. Failures
        are reported per URL; a failed link does not discard successful pages.
        """
        url = _text(url, "url")
        parsed = urlparse(url)
        if (parsed.scheme.casefold() not in {"http", "https"}
                or not parsed.netloc or parsed.username or parsed.password):
            raise ValueError("url must be an HTTP(S) address without credentials")
        for name, value, minimum in (("max_pages", max_pages, 1),
                                     ("max_depth", max_depth, 0),
                                     ("max_bytes_per_page", max_bytes_per_page, 1)):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer of at least {minimum}")
        self._validate_fetch_limits(timeout, max_bytes_per_page)

        origin = self._url_origin(url)
        queue = [(urldefrag(url)[0], 0)]
        queued = {urldefrag(url)[0]}
        visited: list[str] = []
        captured: list[str] = []
        failures: list[tuple[str, str]] = []
        cursor = 0
        while cursor < len(queue) and len(visited) < max_pages:
            page_url, depth = queue[cursor]
            cursor += 1
            visited.append(page_url)
            try:
                title, text, final_url, links = self._capture_url(
                    page_url, timeout=timeout,
                    max_bytes=max_bytes_per_page, required_origin=origin)
                if page_url not in self._documents:
                    self.add_document(page_url, title, text, final_url)
                    captured.append(page_url)
                if depth >= max_depth:
                    continue
                for href in links:
                    target = urldefrag(urljoin(final_url, href))[0]
                    target_parsed = urlparse(target)
                    if target_parsed.scheme.casefold() not in {"http", "https"}:
                        continue
                    try:
                        target_origin = self._url_origin(target)
                    except ValueError:
                        continue
                    if target_origin != origin or target in queued:
                        continue
                    queued.add(target)
                    queue.append((target, depth + 1))
            except Exception as error:
                failures.append((page_url, str(error)))
        return SiteCrawlResult(tuple(captured), tuple(visited), tuple(failures))

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        scheme = parsed.scheme.casefold()
        port = parsed.port
        if port == {"http": 80, "https": 443}.get(scheme):
            port = None
        return (scheme, (parsed.hostname or "").casefold(), port)

    @staticmethod
    def _validate_fetch_limits(timeout: float, max_bytes: int) -> None:
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or timeout <= 0):
            raise ValueError("timeout must be positive")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")

    def _capture_url(
            self, url: str, *, timeout: float, max_bytes: int,
            required_origin: tuple[str, str, int | None] | None = None
            ) -> tuple[str, str, str, list[str]]:
        self._validate_fetch_limits(timeout, max_bytes)
        parsed = urlparse(url)
        if (parsed.scheme.casefold() not in {"http", "https"}
                or not parsed.netloc or parsed.username or parsed.password):
            raise ValueError("url must be an HTTP(S) address without credentials")
        request = Request(url, headers={"User-Agent": "CRMSResearch/1.0"})
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            final = urlparse(final_url)
            if (final.scheme.casefold() not in {"http", "https"}
                    or not final.netloc or final.username or final.password):
                raise ValueError("page redirected outside HTTP(S)")
            if (required_origin is not None
                    and self._url_origin(final_url) != required_origin):
                raise ValueError("page redirected outside the starting origin")
            if not response.headers.get("Content-Type"):
                raise ValueError("page response is missing a content type")
            content_type = response.headers.get_content_type().casefold()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError(f"unsupported page content type: {content_type}")
            raw = response.read(max_bytes + 1)
            charset = response.headers.get_content_charset() or "utf-8"
        if len(raw) > max_bytes:
            raise ValueError(f"page exceeds the {max_bytes}-byte capture limit")
        try:
            decoded = raw.decode(charset, errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8", errors="replace")
        links: list[str] = []
        if content_type == "text/plain":
            title = final.hostname or final_url
            text = decoded.strip()
        else:
            parser = _ReadableHTML()
            parser.feed(decoded)
            links = parser.links
            title = " ".join(" ".join(parser.title_parts).split())
            text = re.sub(r"[ \t\r\f\v]+", " ",
                          "".join(parser.text_parts))
            text = re.sub(r" *\n+ *", "\n", text).strip()
            title = title or final.hostname or final_url
        if not text:
            raise ValueError("page contains no readable text")
        return title, text, final_url, links

    def add_pdf(self, path: str | Path, *, document_id: str | None = None,
                title: str | None = None, location: str | None = None,
                replace: bool = False) -> None:
        """Extract searchable PDF text with page boundaries.

        Prefer pypdf; use Poppler's pdftotext utility when the Python package is
        unavailable. Scanned image-only PDFs still require a separate OCR step.
        """
        source_path = Path(path)
        try:
            from pypdf import PdfReader
        except ImportError:
            executable = shutil.which("pdftotext")
            if executable is None:
                raise RuntimeError(
                    "PDF ingestion requires pypdf or the Poppler pdftotext utility")
            try:
                completed = subprocess.run(
                    [executable, "-layout", "-enc", "UTF-8", str(source_path), "-"],
                    capture_output=True, timeout=120, check=False)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("PDF text extraction exceeded 120 seconds") from error
            if completed.returncode != 0:
                details = completed.stderr.decode("utf-8", errors="replace").strip()
                raise ValueError("pdftotext could not extract this PDF"
                                 + (f": {details}" if details else "."))
            extracted = completed.stdout.decode("utf-8", errors="replace")
            pages = tuple(page.strip() for page in extracted.split("\f")
                          if page.strip())
        else:
            reader = PdfReader(str(source_path))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as error:
                    raise ValueError(
                        "encrypted PDF could not be opened with an empty password") from error
                if reader.is_encrypted:
                    raise ValueError("encrypted PDF requires a password")
            pages = tuple(page.extract_text() or "" for page in reader.pages)
        if not pages or not any(page.strip() for page in pages):
            raise ValueError("PDF contains no extractable text")
        text = "\n\f\n".join(pages)
        self.add_document(
            document_id or str(source_path), title or source_path.name, text,
            location or str(source_path), replace=replace, pages=pages)

    def documents(self) -> list[SourceDocument]:
        return [self._documents[key] for key in sorted(self._documents)]

    def contains_document(self, document_id: str) -> bool:
        return document_id in self._documents

    def source_list(self, *, limit: int = 50, offset: int = 0
                    ) -> list[tuple[str, str, str | None]]:
        if type(limit) is not int or limit < 1 or type(offset) is not int or offset < 0:
            raise ValueError("source-list limit must be positive and offset non-negative")
        document_ids = sorted(self._documents)[offset:offset + limit]
        return [(document_id, self._documents[document_id].title,
                 self._documents[document_id].location)
                for document_id in document_ids]

    def corpus_stats(self) -> tuple[int, int]:
        """Return indexed source count and UTF-8 source-text size in bytes."""
        return (len(self._documents), sum(
            len(document.text.encode("utf-8"))
            for document in self._documents.values()))

    def add_directory(self, path: str | Path, *, replace: bool = False,
                      verify_content: bool = False
                       ) -> DirectoryIngestResult:
        """Index supported text, web, EPUB, and PDF files.

        Files are kept as supplied so citations retain exact source offsets.
        """
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("corpus path must be an existing directory")
        if type(replace) is not bool or type(verify_content) is not bool:
            raise ValueError("replace and verify_content must be booleans")
        added: list[str] = []
        skipped: list[str] = []
        failures: list[tuple[str, str]] = []
        batch: list[Path] = []

        def ingest_batch(paths: list[Path]) -> None:
            pending = []
            for source_path in paths:
                document_id = str(source_path.resolve())
                exists = self.contains_document(document_id)
                if (exists and not replace
                        and self._source_file_is_current(
                            source_path, document_id,
                            verify_content=verify_content)):
                    skipped.append(document_id)
                    continue
                pending.append((source_path, document_id, exists))
            if not pending:
                return
            with self._bulk_write_context():
                for source_path, document_id, exists in pending:
                    try:
                        self.add_file(
                            source_path, document_id=document_id,
                            title=(None if source_path.suffix.casefold() in {
                                ".html", ".htm", ".xhtml", ".docx", ".odt",
                                ".epub", ".json", ".xlsx", ".pptx"}
                                   else source_path.name),
                            location=document_id,
                            replace=(replace or exists))
                        self._record_source_file(source_path, document_id)
                        added.append(document_id)
                    except (OSError, RuntimeError, ValueError) as error:
                        failures.append((document_id, str(error)))

        supported = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv",
                     ".xlsx", ".pptx", ".html",
                     ".htm", ".xhtml", ".json", ".docx", ".odt", ".epub", ".pdf"}
        for current, directory_names, filenames in os.walk(root):
            directory_names[:] = sorted(
                name for name in directory_names
                if not (Path(current) / name).is_symlink())
            for filename in sorted(filenames):
                source_path = Path(current) / filename
                if (source_path.suffix.casefold() not in supported
                        or (source_path.suffix.casefold() == ".json"
                            and source_path.name.casefold() != "conversations.json"
                            and not source_path.name.casefold().endswith(
                                (".chat.json", ".chatgpt.json")))
                        or source_path.is_symlink()
                        or not source_path.is_file()):
                    continue
                batch.append(source_path)
                if len(batch) == self.DIRECTORY_BATCH_SIZE:
                    ingest_batch(batch)
                    batch = []
        if batch:
            ingest_batch(batch)
        return DirectoryIngestResult(tuple(added), tuple(skipped),
                                     tuple(failures))

    def document(self, document_id: str) -> SourceDocument:
        """Return a stored source or raise ``KeyError`` if it is unknown."""
        return self._documents[document_id]

    def exact_title_matches(self, title: str) -> list[ExactTitleMatch]:
        """Find exact normalized title matches without ranked body retrieval."""
        wanted = tuple(token.group().casefold() for token in word_matches(title))
        if not wanted:
            return []
        candidates = set.intersection(*(
            self._title_postings.get(token, set()) for token in wanted))
        matches = []
        for document_id in sorted(candidates):
            document = self._documents[document_id]
            if document.title.casefold() == title.casefold():
                matches.append(ExactTitleMatch(
                    document.document_id, document.title, document.location))
        return matches

    def verify_hit(self, hit: SearchHit) -> SourceDocument:
        """Verify source identity and that the cited span is an exact text slice."""
        document = self._documents.get(hit.document_id)
        if document is None:
            raise ValueError("search hit references a document outside this index")
        if (hit.title != document.title or hit.location != document.location
                or type(hit.start) is not int or type(hit.end) is not int
                or hit.start < 0 or hit.end < hit.start
                or hit.end > len(document.text)
                or document.text[hit.start:hit.end] != hit.snippet):
            raise ValueError("search hit metadata or excerpt does not match its source")
        document_terms = ({token for token, _, _ in self._body_spans[hit.document_id]}
                          | self._title_terms[hit.document_id])
        if any(term not in document_terms for term in hit.matched_terms):
            raise ValueError("search hit contains terms absent from its source or title")
        if hit.match_start is not None or hit.match_end is not None:
            if (type(hit.match_start) is not int or type(hit.match_end) is not int
                    or hit.match_start < hit.start or hit.match_end < hit.match_start
                    or hit.match_end > hit.end):
                raise ValueError("search hit match offsets are invalid")
        if document.pages:
            offset = 0
            expected_page = None
            for page_index, page in enumerate(document.pages, start=1):
                if (hit.match_start is not None
                        and offset <= hit.match_start < offset + len(page)):
                    expected_page = page_index
                    break
                offset += len(page) + len("\n\f\n")
            if hit.page_number != expected_page:
                raise ValueError("search hit page does not match its source offset")
        elif hit.page_number is not None:
            raise ValueError("non-paginated source cannot have a page citation")
        return document

    def citation(self, hit: SearchHit) -> str:
        """Return a stable source-and-offset reference after exact verification."""
        document = self.verify_hit(hit)
        digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        citation = (f"{hit.document_id}#sha256={digest}"
                    f"&chars={hit.start}:{hit.end}")
        if hit.page_number is not None:
            citation += (f"&page={hit.page_number}"
                         f"&match={hit.match_start}:{hit.match_end}")
        return citation

    def resolve_citation(self, citation: str) -> str:
        """Resolve a stored citation and reject stale or malformed references."""
        marker = "#sha256="
        if marker not in citation or "&chars=" not in citation:
            raise ValueError("malformed source citation")
        document_id, remainder = citation.rsplit(marker, 1)
        digest, span = remainder.split("&chars=", 1)
        page_number = None
        match_start = match_end = None
        if "&match=" in span:
            span, match_text = span.rsplit("&match=", 1)
            try:
                match_start_text, match_end_text = match_text.split(":", 1)
                match_start, match_end = int(match_start_text), int(match_end_text)
            except ValueError as error:
                raise ValueError("malformed citation match offsets") from error
        if "&page=" in span:
            span, page_text = span.rsplit("&page=", 1)
            try:
                page_number = int(page_text)
            except ValueError as error:
                raise ValueError("malformed citation page") from error
        try:
            start_text, end_text = span.split(":", 1)
            start, end = int(start_text), int(end_text)
        except (TypeError, ValueError) as error:
            raise ValueError("malformed citation offsets") from error
        document = self._documents.get(document_id)
        if document is None:
            raise ValueError("citation document is not in this index")
        actual_digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        if digest != actual_digest:
            raise ValueError("citation refers to a different source revision")
        if start < 0 or end < start or end > len(document.text):
            raise ValueError("citation offsets are outside the source")
        if page_number is not None and not 1 <= page_number <= len(document.pages):
            raise ValueError("citation page is outside the source")
        if page_number is not None:
            if (match_start is None or match_end is None
                    or match_start < start or match_end < match_start
                    or match_end > end):
                raise ValueError("page citation is missing valid matched-text offsets")
            page_start = sum(len(page) + len("\n\f\n")
                             for page in document.pages[:page_number - 1])
            page_end = page_start + len(document.pages[page_number - 1])
            if not (start < page_end and end > page_start):
                raise ValueError("citation page does not intersect the cited excerpt")
            if not page_start <= match_start < page_end:
                raise ValueError("citation page does not contain the matched text")
        return document.text[start:end]

    @staticmethod
    def _token_spans(text: str) -> list[tuple[str, int, int]]:
        return [(match.group(), match.start(), match.end())
                for match in word_matches(text)]

    @staticmethod
    def _snippet(document: SourceDocument, query_terms: set[str],
                 context_chars: int, spans: list[tuple[str, int, int]],
                 window_tokens: int = 36,
                 term_weights: Mapping[str, float] | None = None
                 ) -> tuple[str, int, int, int | None, int | None, int | None]:
        if not spans:
            return document.text, 0, len(document.text), None, None, None
        # Prefer one complete source sentence. The offsets remain a verbatim
        # slice of the document, so citations stay independently verifiable.
        sentence_choices = []
        weights = term_weights or {}
        matched_spans = [span for span in spans
                         if span[0].casefold() in query_terms]
        candidate_sentences = []
        sentence_end = 0
        span_index = 0
        while span_index < len(matched_spans):
            _token, position, _token_end = matched_spans[span_index]
            if position < sentence_end:
                span_index += 1
                continue
            sentence_span = _sentence_span_at(
                document.text, position, lower_bound=sentence_end)
            matching = []
            while (span_index < len(matched_spans)
                   and matched_spans[span_index][1] < sentence_span[1]):
                matching.append(matched_spans[span_index])
                span_index += 1
            candidate_sentences.append((sentence_span, matching))
            sentence_end = sentence_span[1]
        for (sentence_start, sentence_end), matching in candidate_sentences:
            # Source text sometimes contains a long unpunctuated block (for
            # example, extracted tables or malformed OCR). It is not a useful
            # answer snippet even when it contains the best matching terms.
            if sentence_end - sentence_start > 1000:
                continue
            if matching:
                matched_terms = {span[0].casefold() for span in matching}
                coverage = len(matched_terms)
                weighted_coverage = sum(
                    weights.get(term, 1.0)
                    * (8.0 if any(character.isdigit() for character in term)
                       else 1.0)
                    for term in matched_terms)
                sentence_choices.append((weighted_coverage, coverage,
                                         sentence_end - sentence_start,
                                         sentence_start, sentence_end, matching))
        if sentence_choices:
            _weighted, _coverage, _length, start, end, matching = min(
                sentence_choices,
                key=lambda item: (-item[0], -item[1], item[2], item[3]))
            # Strip surrounding whitespace without changing the cited text.
            while start < end and document.text[start].isspace():
                start += 1
            while end > start and document.text[end - 1].isspace():
                end -= 1
            match_start, match_end = matching[0][1], matching[-1][2]
            page_number = None
            if document.pages and match_start is not None:
                offset = 0
                for page_index, page in enumerate(document.pages, start=1):
                    if offset <= match_start < offset + len(page):
                        page_number = page_index
                        break
                    offset += len(page) + len("\n\f\n")
            return (document.text[start:end], start, end, page_number,
                    match_start, match_end)
        best_start = 0
        best_end = min(len(spans), window_tokens)
        best_coverage = -1
        for start_index in range(len(spans)):
            end_index = min(len(spans), start_index + window_tokens)
            coverage = len({spans[i][0] for i in range(start_index, end_index)}
                           & query_terms)
            if coverage > best_coverage:
                best_start, best_end = start_index, end_index
                best_coverage = coverage
        start = max(0, spans[best_start][1] - context_chars)
        end = min(len(document.text), spans[best_end - 1][2] + context_chars)
        matching = [spans[index] for index in range(best_start, best_end)
                    if spans[index][0] in query_terms]
        match_start = matching[0][1] if matching else None
        match_end = matching[-1][2] if matching else None
        page_number = None
        if document.pages and match_start is not None:
            offset = 0
            for page_index, page in enumerate(document.pages, start=1):
                if offset <= match_start < offset + len(page):
                    page_number = page_index
                    break
                offset += len(page) + len("\n\f\n")
        return document.text[start:end], start, end, page_number, match_start, match_end

    def search(self, query: str, *, limit: int = 5,
               context_chars: int = 120) -> list[SearchHit]:
        query = _text(query, "query")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if type(context_chars) is not int or context_chars < 0:
            raise ValueError("context_chars must be a non-negative integer")
        terms = _research_query_terms(query)
        focus_terms = _research_query_focus_terms(query)
        if not terms or not self._documents:
            return []
        query_words = tuple(match.group().casefold()
                            for match in word_matches(query))
        # Person-seeking questions expect biographical or other prose
        # evidence. Code remains searchable for programming requests, but
        # string literals and tests should not win a question such as
        # "Who created Python?" merely because they repeat the entity words.
        prose_preferred = _prefers_prose_sources(query)
        programming_query = _is_programming_query(query)

        document_frequency = {
            term: len(self._postings.get(term, set())
                      | self._title_postings.get(term, set()))
            for term in terms
        }
        count = len(self._documents)
        average_length = (sum(self._body_counts[key].total()
                              for key in self._documents) / count
                          if count else 0.0)
        hits = []
        candidate_ids = set().union(
            *(self._postings.get(term, set()) | self._title_postings.get(term, set())
              for term in terms))
        for key in candidate_ids:
            document = self._documents[key]
            if prose_preferred and _is_code_source(document.location):
                continue
            frequencies = self._body_counts[key]
            length = self._body_counts[key].total()
            score = 0.0
            matched = []
            inverse_frequency_sum = 0.0
            for term in terms:
                df = document_frequency[term]
                in_body = frequencies[term] > 0
                in_title = term in self._title_terms[key]
                if not in_body and not in_title:
                    continue
                matched.append(term)
                inverse = math.log(1 + (count - df + 0.5) / (df + 0.5))
                term_weight = 8.0 if term in focus_terms else 1.0
                inverse_frequency_sum += inverse * term_weight
                if in_body:
                    tf = frequencies[term]
                    denominator = tf + 1.2 * (
                        1 - 0.75 + 0.75 * length / max(average_length, 1.0))
                    score += term_weight * inverse * tf * 2.2 / denominator
                if in_title:
                    score += term_weight * inverse * 1.5
            if len(terms) > 1 and all(frequencies[term] for term in terms):
                query_pairs = set(zip(terms, terms[1:]))
                body_pairs = set()
                spans = self._body_spans[key]
                sentence_ids = [0] * len(spans)
                positions_by_term: dict[str, list[int]] = {
                    term: [] for term in terms
                }
                sentence_id = 0
                for span_index, (token, _, token_end) in enumerate(spans):
                    sentence_ids[span_index] = sentence_id
                    if token in positions_by_term:
                        positions_by_term[token].append(span_index)
                    if span_index + 1 < len(spans):
                        next_start = spans[span_index + 1][1]
                        separator = document.text[token_end:next_start]
                        if re.search(r"[.!?\n\f]", separator):
                            sentence_id += 1
                for (left, _, left_end), (right, right_start, _) in zip(
                        spans, spans[1:]):
                    separator = document.text[left_end:right_start]
                    if not re.search(r"[.!?\n\f]", separator):
                        body_pairs.add((left, right))
                adjacent_pairs = len(query_pairs & body_pairs)
                adjacency_fraction = (adjacent_pairs / len(query_pairs)
                                      if adjacent_pairs else 0.0)
                best_gap_count = None
                for start_index in positions_by_term[terms[0]]:
                    current_index = start_index
                    current_sentence = sentence_ids[start_index]
                    for term in terms[1:]:
                        positions = positions_by_term[term]
                        candidate_offset = bisect_left(positions,
                                                       current_index + 1)
                        if (candidate_offset >= len(positions)
                                or sentence_ids[positions[candidate_offset]]
                                != current_sentence):
                            break
                        current_index = positions[candidate_offset]
                    else:
                        gap_count = current_index - start_index - (len(terms) - 1)
                        if best_gap_count is None or gap_count < best_gap_count:
                            best_gap_count = gap_count
                            if gap_count == 0:
                                break
                ordered_proximity = (1 / (1 + best_gap_count)
                                     if best_gap_count is not None else 0.0)
                proximity_fraction = (
                    0.5 * adjacency_fraction + 0.5 * ordered_proximity)
                if proximity_fraction:
                    # Reward ordered query terms that occur next to each
                    # other or within a compact ordered span in one sentence.
                    # The IDF-scaled bonus only changes ranking; it never
                    # changes source spans or licenses a fact.
                    score += (0.5 * inverse_frequency_sum / len(terms)
                              * proximity_fraction)
            if not matched:
                continue
            if programming_query and _is_code_source(document.location):
                # Explicit code intent should let implementation files beat
                # prose notes that repeat an identifier or a generic word
                # such as "function". Ordinary natural-language questions
                # still filter code sources through prose_preferred above.
                score *= 3.0
            (snippet, start, end, page_number,
             match_start, match_end) = self._snippet(
                document, set(matched), context_chars,
                self._body_spans[key], term_weights={
                    term: math.log(1 + (count - document_frequency[term] + 0.5)
                                   / (document_frequency[term] + 0.5))
                    * (8.0 if term in focus_terms else 1.0)
                    for term in matched})
            hits.append(SearchHit(
                document.document_id, document.title, document.location,
                score, snippet, start, end, tuple(matched), page_number,
                match_start, match_end))
        hits.sort(key=lambda hit: (-hit.score, hit.document_id))
        return hits[:limit]

    def search_latest(self, query: str, *, limit: int = 5
                      ) -> list[LatestSearchHit]:
        """Find the newest dated documents among lexical topic matches.

        Publication dates must be explicitly present in source text. This
        reorders retrieved evidence; it does not infer dates from IDs or
        treat update dates as publication dates.
        """
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        hits = self.search(query, limit=max(1, self.document_count()))
        dated: list[LatestSearchHit] = []
        required_terms = set(_research_query_terms(query))
        for hit in hits:
            if not required_terms.issubset(set(hit.matched_terms)):
                continue
            document = self.document(hit.document_id)
            match = re.search(
                r"(?im)^\s*(?:published|publication date)\s*:\s*"
                r"(\d{4}-\d{2}-\d{2})(?:\b|T)", document.text)
            if match is not None:
                dated.append(LatestSearchHit(hit, match.group(1)))
        dated.sort(key=lambda item: (item.publication_date, item.hit.score,
                                    item.hit.document_id), reverse=True)
        return dated[:limit]

    def summarize(self, query: str, *, limit: int = 5,
                  per_document: int = 2,
                  retrieval_terms: Iterable[str] = (),
                  expansion_licenses: Iterable[Mapping[str, Any]] = (),
                  precomputed_hits: Iterable[SearchHit] | None = None
                  ) -> ExtractiveSummary:
        """Select exact cited sentences using query terms and licensed expansions.

        Internal callers can reuse hits from the identical expanded query to
        avoid running a large-corpus search twice for one chat turn.
        """
        query = _text(query, "query")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if type(per_document) is not int or per_document < 1:
            raise ValueError("per_document must be a positive integer")
        extra_terms = []
        for term in retrieval_terms:
            if (len(extra_terms) >= 128 or not isinstance(term, str)
                    or not term.strip() or len(term) > 512):
                raise ValueError("retrieval terms must be a bounded list of nonempty text")
            extra_terms.append(term)
        normalized_terms = tuple(dict.fromkeys(term.strip() for term in extra_terms))
        retrieval_query = " ".join((query, *normalized_terms))
        licenses = []
        seen_licenses: set[tuple[str, str, str, tuple[str, ...], tuple[str, ...]]] = set()
        for index, record in enumerate(expansion_licenses):
            if index >= 256:
                raise ValueError("query expansion licenses exceed the summary bound")
            if not isinstance(record, Mapping):
                raise ValueError("query expansion licenses must be structured records")
            kind, evidence, text = (record.get("kind"), record.get("evidence"),
                                    record.get("text"))
            sources, rules = record.get("sources", ()), record.get("rules", ())
            if (not all(isinstance(value, str) and value.strip()
                        for value in (kind, evidence, text))
                    or not isinstance(sources, (tuple, list))
                    or not isinstance(rules, (tuple, list))
                    or any(not isinstance(value, str) for value in (*sources, *rules))):
                raise ValueError("query expansion license is malformed")
            key = (kind, evidence, text, tuple(sorted(set(sources))),
                   tuple(sorted(set(rules))))
            if key in seen_licenses:
                continue
            seen_licenses.add(key)
            licenses.append({"kind": kind, "evidence": evidence, "text": text,
                             "sources": key[3], "rules": key[4]})
        licensed_terms = {record["text"] for record in licenses}
        if any(term not in licensed_terms for term in normalized_terms):
            raise ValueError("each retrieval term must have a supplied license")
        if precomputed_hits is None:
            hits = self.search(retrieval_query, limit=limit, context_chars=240)
        else:
            hits = list(precomputed_hits)
            if (len(hits) > limit
                    or any(not isinstance(hit, SearchHit) for hit in hits)):
                raise ValueError("precomputed search hits are malformed or exceed limit")
        # Coverage should measure content words, not auxiliaries and question
        # words such as "who", "was" and "of". Counting those function words
        # makes a licensed paraphrase frame fail sentence selection even when
        # every identity-bearing query term is present in the cited sentence.
        original_terms = set(_research_query_terms(query))
        query_words = tuple(match.group().casefold()
                            for match in word_matches(query))
        requests_structured_source = bool(
            _STRUCTURED_SOURCE_QUERY.search(query))
        requests_figure_source = bool(re.search(
            r"\b(?:figure|fig\.?|caption)\b", query, re.IGNORECASE))
        requested_table_number = re.search(
            r"\btable\s+(\d+[a-z]?)\b", query, re.IGNORECASE)
        person_question = bool(
            query_words and query_words[0] in {"who", "whom"})
        minimum_person_term_coverage = min(
            len(original_terms), max(2, len(original_terms) - 1))
        focus_terms = _research_query_focus_terms(query)
        retrieved_terms = {term for hit in hits for term in hit.matched_terms}
        used_licenses = []
        for record in licenses:
            expansion_terms = {match.group()
                               for match in word_matches(record["text"])}
            query_surface_is_licensed = (
                record["kind"] == "licensed_predicate"
                and bool(expansion_terms & original_terms))
            if (query_surface_is_licensed
                    or (expansion_terms - original_terms) & retrieved_terms):
                used_licenses.append(record)

        def frame_expansion_coverage(sentence_words: set[str]) -> set[str]:
            """Credit a query predicate only through its licensed frame chain."""
            covered: set[str] = set()
            # Transparent inflection expansions map only the exact query token
            # to a mechanically generated spelling found in the sentence.
            # They do not license any other query words or semantic aliases.
            for form in used_licenses:
                if form["kind"] != "regular_question_verb_inflection":
                    continue
                query_form = set(_research_query_terms(form["evidence"]))
                source_form = set(_research_query_terms(form["text"]))
                if query_form & original_terms and source_form & sentence_words:
                    covered.update(query_form & original_terms)
            # A bounded agent-noun morphology proposal (creator → created) may
            # cover that exact question token when its generated verb form is
            # present in the same cited sentence. This is retrieval evidence
            # only; the source sentence still has to state the claim.
            for form in used_licenses:
                if form["kind"] != "agent_noun_spelling_candidate":
                    continue
                query_form = set(_research_query_terms(form["evidence"]))
                source_form = set(_research_query_terms(form["text"]))
                if query_form & original_terms and source_form & sentence_words:
                    covered.update(query_form & original_terms)
            predicate_frames = [record for record in used_licenses
                                if record["kind"] == "learned_question_frame"]
            predicate_forms = [record for record in used_licenses
                               if record["kind"] in {
                                   "licensed_predicate",
                                   "regular_question_verb_inflection"}]
            for frame in predicate_frames:
                frame_words = {match.group() for match in
                               word_matches(frame["evidence"])}
                mapped_query_words = frame_words & original_terms
                relation = set(_research_query_terms(frame["text"]))
                if not mapped_query_words or not relation:
                    continue
                for form in predicate_forms:
                    if set(_research_query_terms(form["evidence"])) != relation:
                        continue
                    if set(_research_query_terms(form["text"])) & sentence_words:
                        covered.update(mapped_query_words)
            # Two independently observed surface predicates can share one
            # canonical relation (for example, "made" and "created" for
            # create). A reviewed cross-form alignment lets either wording
            # cover the predicate slot in a cited sentence, while entity
            # terms still have to match directly.
            forms_by_relation: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
            for record in used_licenses:
                if record["kind"] != "licensed_predicate":
                    continue
                relation = tuple(_research_query_terms(record["evidence"]))
                if relation:
                    forms_by_relation.setdefault(relation, []).append(record)
            for records in forms_by_relation.values():
                query_forms = [set(_research_query_terms(record["text"]))
                               & original_terms for record in records]
                sentence_forms = [set(_research_query_terms(record["text"]))
                                  & sentence_words for record in records]
                if any(query_form and sentence_form
                       for query_form in query_forms
                       for sentence_form in sentence_forms):
                    covered.update(set().union(*query_forms))
            return covered

        candidates: list[tuple[float, str, int, SummarySentence]] = []
        for hit in hits:
            document = self.verify_hit(hit)
            query_terms = set(hit.matched_terms)
            document_tokens = [token for token, _, _
                               in self._token_spans(document.text)]
            document_counts = Counter(document_tokens)
            document_pairs = Counter(zip(document_tokens,
                                          document_tokens[1:]))
            document_length = len(document_tokens)
            term_weights = {
                term: (8.0 if term in focus_terms else 1.0) * math.log(
                    1 + (document_length - document_counts[term] + 0.5)
                    / (document_counts[term] + 0.5))
                for term in query_terms if document_counts[term]
            }
            query_terms_in_order = [term for term in _research_query_terms(query)
                                    if term in document_counts]
            query_pairs = tuple(zip(query_terms_in_order,
                                    query_terms_in_order[1:]))
            pair_weights = {
                pair: math.log(
                    1 + (document_length - document_pairs[pair] + 0.5)
                    / (document_pairs[pair] + 0.5))
                for pair in query_pairs if document_pairs[pair]
            }
            maximum_sentence_score = (
                sum(term_weights.values()) +
                2.0 * sum(pair_weights.values()))
            page_offsets: list[tuple[int, int, int]] = []
            if document.pages:
                offset = 0
                for page_number, page in enumerate(document.pages, start=1):
                    page_offsets.append((offset, offset + len(page), page_number))
                    offset += len(page) + len("\n\f\n")
            sentence_pattern = (
                r"(?:(?:[.!?](?![\s\"'”’)]|$))|"
                r"(?!(?:\r?\n)[ \t]*(?:\r?\n))[^.!?\f])+"
                r"[.!?]*[\"'”’)]*(?=\s|$|[\n\f])")
            for match in re.finditer(sentence_pattern, document.text):
                raw = match.group(0)
                leading = len(raw) - len(raw.lstrip())
                trailing = len(raw.rstrip())
                if trailing <= leading:
                    continue
                local_start = match.start() + leading
                local_end = match.start() + trailing
                sentence_text = document.text[local_start:local_end]
                if _is_imported_structured_metadata(sentence_text):
                    continue
                if (requests_structured_source
                        and sentence_text.count("|") >= 2):
                    table_heading = re.search(
                        r"(?im)^\s*Table\s+\d+[a-z]?\s*$", sentence_text)
                    if table_heading is not None:
                        heading_start = table_heading.start()
                        while (heading_start < len(sentence_text)
                               and sentence_text[heading_start].isspace()):
                            heading_start += 1
                        local_start += heading_start
                        sentence_text = document.text[local_start:local_end]
                if (not requests_figure_source
                        and _in_figure_caption(document.text, local_start)):
                    continue
                # Importers prepend labeled source metadata to full text. It
                # remains searchable for structured lookups, but is not an
                # article claim and should not crowd extractive summaries.
                if _SOURCE_METADATA_LINE.match(sentence_text):
                    continue
                # Markdown-like JATS table rows are useful when the user asks
                # about a table, but they overwhelm a general paper summary.
                # Keep them searchable and include them for explicit layout
                # questions; otherwise select natural prose claims.
                if (sentence_text.count("|") >= 2
                        and not requests_structured_source):
                    continue
                sentence_tokens = word_matches(sentence_text)
                sentence_words = [token.group() for token in sentence_tokens]
                matching = [token for token in sentence_tokens
                            if token.group() in query_terms]
                if not matching:
                    continue
                matched_terms = tuple(sorted({token.group() for token in matching}))
                covered_terms = (set(matched_terms) & original_terms)
                if person_question:
                    covered_terms.update(
                        frame_expansion_coverage(set(sentence_words)))
                # Require multiple matching terms for ordinary retrieval so a
                # generic one-word match cannot masquerade as an answer. For
                # summaries, a one-term sentence can be useful when it covers
                # a distinct part of the requested topic; the coverage-first
                # selector below will prefer it only after selecting a more
                # informative sentence. This lets summaries cover all query
                # terms without rewarding repeated sentences.
                effective_coverage = (
                    len(covered_terms - focus_terms)
                    + 2 * len(covered_terms & focus_terms))
                if (len(original_terms) >= 2
                        and not requests_structured_source
                        and not requests_figure_source
                        and effective_coverage < (1 if limit > 1 else 2)):
                    continue
                if (person_question
                        and len(covered_terms)
                        < minimum_person_term_coverage):
                    continue
                matched_pairs = set(zip(sentence_words, sentence_words[1:]))
                relevance = (
                    sum(term_weights.get(term, 0.0)
                        for term in matched_terms) +
                    2.0 * sum(weight for pair, weight in pair_weights.items()
                              if pair in matched_pairs))
                # Sentence selection is local to the document. Weight rare
                # query terms and phrases there so one generic auxiliary or
                # a long command list cannot defeat a compact source sentence.
                coverage = (relevance / maximum_sentence_score
                            if maximum_sentence_score else
                            len(matched_terms) / max(len(query_terms), 1))
                absolute_start = local_start
                absolute_end = local_end
                match_start = absolute_start + matching[0].start()
                match_end = absolute_start + matching[0].end()
                page_number = next((page for start, end, page in page_offsets
                                    if start <= match_start < end), None)
                context_kind = (
                    "table" if requests_structured_source
                    and sentence_text.count("|") >= 2
                    else _sentence_context_kind(
                        sentence_text, document.text, absolute_start))
                polar_question = bool(query_words and query_words[0] in {
                    "am", "are", "can", "could", "did", "do", "does",
                    "had", "has", "have", "is", "may", "might", "must",
                    "shall", "should", "was", "were", "will", "would",
                })
                if polar_question and context_kind in {"example", "table"}:
                    # Examples can illustrate how a yes/no question is parsed,
                    # but they cannot establish the truth of its proposition.
                    continue
                sentence_score = hit.score * (0.5 + 0.5 * coverage)
                if person_question and context_kind == "example":
                    sentence_score *= 0.2
                sentence_hit = SearchHit(
                    hit.document_id, hit.title, hit.location,
                    # Keep sentence coverage as a refinement of document
                    # relevance, not a multiplier that can let one dense
                    # code/test sentence outrank a substantially stronger
                    # prose document match. A sentence with zero coverage is
                    # already excluded above, so this bounded blend retains
                    # at least half of the document-level score.
                    sentence_score,
                    sentence_text, absolute_start, absolute_end,
                    matched_terms, page_number, match_start, match_end)
                citation = self.citation(sentence_hit)
                result = SummarySentence(
                    sentence_text, citation, hit.document_id, hit.title,
                    hit.location, sentence_hit.score, matched_terms, page_number,
                    context_kind)
                candidates.append((result.score, hit.document_id,
                                   absolute_start, result))

        if (re.search(r"\btable\b", query, re.IGNORECASE)
                and any(item[3].context_kind == "table"
                        for item in candidates)):
            # A named-table request is a structured lookup. Once that table
            # has been found, do not append nearby prose just because it
            # repeats the same vocabulary.
            candidates = [item for item in candidates
                          if item[3].context_kind == "table"]
            if requested_table_number is not None:
                table_label = re.compile(
                    r"(?im)^\s*Table\s+"
                    + re.escape(requested_table_number.group(1))
                    + r"\s*$")
                numbered = [item for item in candidates
                            if table_label.search(item[3].text)]
                if numbered:
                    candidates = numbered
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        selected: list[SummarySentence] = []
        counts: Counter[str] = Counter()
        seen: set[tuple[str, str]] = set()
        covered_terms: set[str] = set()
        remaining = list(candidates)
        while remaining and len(selected) < limit:
            eligible = [item for item in remaining
                        if ((item[1], item[3].text) not in seen
                            and counts[item[1]] < per_document)]
            if not eligible:
                break
            novel = [item for item in eligible
                     if set(item[3].matched_terms) - covered_terms]
            if covered_terms and novel:
                # Once a high-relevance sentence is selected, cover another
                # query term before choosing a redundant sentence. The first
                # choice and each novel choice are still relevance-ranked.
                eligible = novel
            _score, document_id, _offset, sentence = min(
                eligible,
                key=lambda item: (
                    -item[0],
                    -len(set(item[3].matched_terms) - covered_terms),
                    item[1], item[2]))
            key = (document_id, sentence.text)
            remaining.remove(next(item for item in eligible
                                  if (item[1], item[3].text) == key))
            seen.add(key)
            counts[document_id] += 1
            selected.append(sentence)
            covered_terms.update(sentence.matched_terms)
        return ExtractiveSummary(query, tuple(selected), tuple(used_licenses))

    @staticmethod
    def render_hits(query: str, hits: list[SearchHit]) -> str:
        """Format retrieval results as attributed excerpts, without synthesis."""
        query = _text(query, "query")
        if not hits:
            return f"No supplied source matched: {query}"
        lines = [f"Retrieved {len(hits)} source passage(s) for: {query}"]
        for index, hit in enumerate(hits, start=1):
            location = f" ({hit.location})" if hit.location else ""
            page = f"page {hit.page_number}, " if hit.page_number is not None else ""
            lines.append(
                f"{index}. {hit.title}{location} [{hit.document_id}, "
                f"{page}characters {hit.start}:{hit.end}]\n   {hit.snippet}")
        return "\n".join(lines)

    def save(self, path: str | Path) -> None:
        payload: dict[str, Any] = {
            "format_version": self.FORMAT_VERSION,
            "documents": [asdict(document) for document in self.documents()],
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "CRMSResearchIndex":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("format_version") != cls.FORMAT_VERSION:
            raise ValueError("unsupported research-index format version")
        index = cls()
        for document in payload.get("documents", []):
            index.add_document(document["document_id"], document["title"],
                               document["text"], document.get("location"),
                               pages=document.get("pages"))
        return index


class CRMSSQLiteResearchIndex(CRMSResearchIndex):
    """Disk-backed source corpus using SQLite FTS5 and exact stored passages.

    Source text, page boundaries, and the full-text index stay on disk. Search
    loads only the top matching source documents to construct and verify exact
    character-offset citations.
    """

    SCHEMA_VERSION = 2
    CHUNK_TOKENS = 400
    CHUNK_OVERLAP = 50

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        super().__init__()
        if not isinstance(read_only, bool):
            raise TypeError("read_only must be a boolean")
        self.path = Path(path).expanduser().resolve()
        self.read_only = read_only
        self._term_document_frequency_cache: dict[str, int] = {}
        self._term_document_frequency_data_version: int | None = None
        self._fts_chunk_key = "CAST(source_fts.chunk_id AS INTEGER)"
        self._fts_contentless = False
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            try:
                self._db = sqlite3.connect(
                    self.path.as_uri() + "?mode=ro", uri=True)
                self._db.execute("PRAGMA query_only=ON")
                current = self._db.execute(
                    "SELECT value FROM corpus_meta "
                    "WHERE key='schema_version'").fetchone()
                if current is None:
                    raise ValueError(
                        "read-only source is not a CRMS SQLite research index")
                if current[0] != str(self.SCHEMA_VERSION):
                    raise ValueError(
                        "unsupported read-only SQLite research-index schema")
                tables = {row[0] for row in self._db.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                required = {"source_documents", "source_chunks", "source_fts"}
                if not required <= tables:
                    raise ValueError(
                        "read-only source is missing research-index tables")
                self._detect_fts_layout()
            except Exception:
                if hasattr(self, "_db"):
                    self._db.close()
                raise
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = sqlite3.connect(str(self.path))
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS corpus_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            current = self._db.execute(
                "SELECT value FROM corpus_meta WHERE key='schema_version'").fetchone()
            if current is None:
                self._db.execute(
                    "INSERT INTO corpus_meta(key,value) VALUES('schema_version',?)",
                    (str(self.SCHEMA_VERSION),))
            elif current[0] == "1":
                self._db.execute("DROP TABLE IF EXISTS source_fts")
                self._db.execute("DROP TABLE IF EXISTS source_chunks")
                self._db.execute(
                    "UPDATE corpus_meta SET value=? WHERE key='schema_version'",
                    (str(self.SCHEMA_VERSION),))
            elif current[0] != str(self.SCHEMA_VERSION):
                raise ValueError("unsupported SQLite research-corpus schema")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS source_documents ("
                "document_id TEXT PRIMARY KEY, title TEXT NOT NULL, "
                "location TEXT, body TEXT NOT NULL, pages_json TEXT NOT NULL, "
                "sha256 TEXT NOT NULL)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS source_file_state ("
                "document_id TEXT PRIMARY KEY, size_bytes INTEGER NOT NULL, "
                "mtime_ns INTEGER NOT NULL, file_sha256 TEXT, "
                "FOREIGN KEY(document_id) REFERENCES source_documents(document_id) "
                "ON DELETE CASCADE)")
            source_state_columns = {
                row[1] for row in self._db.execute(
                    "PRAGMA table_info(source_file_state)")}
            if "file_sha256" not in source_state_columns:
                self._db.execute(
                    "ALTER TABLE source_file_state ADD COLUMN file_sha256 TEXT")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS source_chunks ("
                "chunk_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "document_id TEXT NOT NULL, start_offset INTEGER NOT NULL, "
                "end_offset INTEGER NOT NULL, "
                "FOREIGN KEY(document_id) REFERENCES source_documents(document_id) "
                "ON DELETE CASCADE)")
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS source_chunks_document "
                "ON source_chunks(document_id)")
            self._create_fts_table()
            self._detect_fts_layout()
            self._db.commit()
            self._backfill_missing_chunks()
        except sqlite3.OperationalError as error:
            raise RuntimeError(
                "the active SQLite build must include FTS5 support") from error

    _CONTENTLESS_FTS_SQL = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5("
        "chunk_id UNINDEXED, title, body, tokenize='unicode61', "
        "content='', contentless_delete=1)")
    _LEGACY_FTS_SQL = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5("
        "chunk_id UNINDEXED, title, body, tokenize='unicode61')")

    def _create_fts_table(self) -> None:
        """Create the passage index without a second copy of the passage text.

        Chunks are substrings of ``source_documents.body``, and queries only use
        MATCH and bm25, so the index stores terms alone (contentless, keyed by
        rowid == chunk_id). Builds without ``contentless_delete`` (SQLite
        < 3.43) fall back to the older layout that stores the text again.
        """
        try:
            self._db.execute(self._CONTENTLESS_FTS_SQL)
        except sqlite3.OperationalError:
            self._db.execute(self._LEGACY_FTS_SQL)

    def _detect_fts_layout(self) -> None:
        """Choose the chunk join key for contentless or legacy indexes."""
        row = self._db.execute(
            "SELECT sql FROM sqlite_master WHERE name='source_fts'").fetchone()
        sql = (row[0] if row else "") or ""
        self._fts_contentless = "content=''" in sql.replace(" ", "")
        self._fts_chunk_key = ("source_fts.rowid" if self._fts_contentless
                               else "CAST(source_fts.chunk_id AS INTEGER)")

    def rebuild_contentless_index(self) -> bool:
        """Convert a legacy index to the contentless layout, then compact.

        Returns False when the index is already contentless. The rebuilt
        index tokenises the same chunk text, so MATCH results and bm25 ranks
        are unchanged.
        """
        if self.read_only:
            raise ValueError("a read-only index cannot be rebuilt")
        if self._fts_contentless:
            return False
        self._db.execute("DROP TABLE source_fts")
        self._create_fts_table()
        self._detect_fts_layout()
        if not self._fts_contentless:
            raise RuntimeError("SQLite 3.43 or newer is required")
        last_id = ""
        while True:
            documents = self._db.execute(
                "SELECT document_id,title,body FROM source_documents "
                "WHERE document_id>? ORDER BY document_id LIMIT ?",
                (last_id, self.DIRECTORY_BATCH_SIZE)).fetchall()
            if not documents:
                break
            with self._bulk_write_context():
                for document_id, title, text in documents:
                    for chunk_id, start, end in self._db.execute(
                            "SELECT chunk_id,start_offset,end_offset "
                            "FROM source_chunks WHERE document_id=?",
                            (document_id,)).fetchall():
                        self._db.execute(
                            "INSERT INTO source_fts(rowid,chunk_id,title,body) "
                            "VALUES(?,?,?,?)",
                            (chunk_id, chunk_id, title, text[start:end]))
            last_id = documents[-1][0]
        self._db.commit()
        self._term_document_frequency_cache.clear()
        self._db.execute("VACUUM")
        return True

    def add_document(self, document_id: str, title: str, text: str,
                     location: str | None = None, *, replace: bool = False,
                     pages: Iterable[str] | None = None) -> None:
        document_id = _text(document_id, "document_id")
        title = _text(title, "title")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if location is not None:
            location = _text(location, "location")
        page_text = tuple(pages or ())
        if any(not isinstance(page, str) for page in page_text):
            raise ValueError("pages must contain only strings")
        if page_text and "\n\f\n".join(page_text) != text:
            raise ValueError("joined page text must match document text exactly")
        if self.contains_document(document_id) and not replace:
            raise ValueError("document_id already exists; pass replace=True to replace it")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._db.execute("SAVEPOINT crms_add_document")
        try:
            self._delete_chunks(document_id)
            self._db.execute(
                "INSERT OR REPLACE INTO source_documents "
                "(document_id,title,location,body,pages_json,sha256) "
                "VALUES(?,?,?,?,?,?)",
                (document_id, title, location, text,
                 json.dumps(page_text, ensure_ascii=False), digest))
            self._insert_chunks(document_id, title, text)
        except Exception:
            self._db.execute("ROLLBACK TO crms_add_document")
            self._db.execute("RELEASE crms_add_document")
            raise
        else:
            self._db.execute("RELEASE crms_add_document")
            self._term_document_frequency_cache.clear()

    def _refresh_term_document_frequency_cache(self) -> None:
        """Discard cached corpus frequencies after another connection writes."""
        version = int(self._db.execute("PRAGMA data_version").fetchone()[0])
        if version != self._term_document_frequency_data_version:
            self._term_document_frequency_cache.clear()
            self._term_document_frequency_data_version = version

    def _term_document_frequency(self, term: str) -> int:
        """Count containing documents once per stable index version and term."""
        cached = self._term_document_frequency_cache.get(term)
        if cached is not None:
            return cached
        quoted_term = f'"{term.replace(chr(34), chr(34) * 2)}"'
        expression = f"title : {quoted_term} OR body : {quoted_term}"
        frequency = int(self._db.execute(
            "SELECT count(DISTINCT c.document_id) "
            "FROM source_fts JOIN source_chunks c "
            "ON c.chunk_id=" + self._fts_chunk_key + " "
            "WHERE source_fts MATCH ?", (expression,)).fetchone()[0])
        # Bound per-index memory when a long-lived session sees many topics.
        if len(self._term_document_frequency_cache) >= 4096:
            self._term_document_frequency_cache.clear()
        self._term_document_frequency_cache[term] = frequency
        return frequency

    @classmethod
    def _chunk_ranges(cls, text: str) -> list[tuple[int, int]]:
        spans = CRMSResearchIndex._token_spans(text)
        if not spans:
            return [(0, len(text))]
        ranges = []
        start_index = 0
        while start_index < len(spans):
            end_index = min(start_index + cls.CHUNK_TOKENS, len(spans))
            start = 0 if start_index == 0 else spans[start_index][1]
            end = spans[end_index - 1][2]
            ranges.append((start, end))
            if end_index == len(spans):
                break
            start_index = end_index - cls.CHUNK_OVERLAP
        return ranges

    def _delete_chunks(self, document_id: str) -> None:
        chunk_ids = [row[0] for row in self._db.execute(
            "SELECT chunk_id FROM source_chunks WHERE document_id=?",
            (document_id,))]
        if chunk_ids:
            key = "rowid" if self._fts_contentless else "chunk_id"
            self._db.executemany(
                f"DELETE FROM source_fts WHERE {key}=?",
                ((chunk_id,) for chunk_id in chunk_ids))
        self._db.execute(
            "DELETE FROM source_chunks WHERE document_id=?", (document_id,))

    def _insert_chunks(self, document_id: str, title: str, text: str) -> None:
        for start, end in self._chunk_ranges(text):
            cursor = self._db.execute(
                "INSERT INTO source_chunks(document_id,start_offset,end_offset) "
                "VALUES(?,?,?)", (document_id, start, end))
            self._db.execute(
                "INSERT INTO source_fts(rowid,chunk_id,title,body) "
                "VALUES(?,?,?,?)",
                (cursor.lastrowid, cursor.lastrowid, title, text[start:end]))

    def _backfill_missing_chunks(self) -> None:
        last_id = ""
        while True:
            missing = self._db.execute(
                "SELECT d.document_id,d.title,d.body FROM source_documents d "
                "WHERE d.document_id>? AND NOT EXISTS ("
                "SELECT 1 FROM source_chunks c "
                "WHERE c.document_id=d.document_id) "
                "ORDER BY d.document_id LIMIT ?",
                (last_id, self.DIRECTORY_BATCH_SIZE)).fetchall()
            if not missing:
                break
            with self._bulk_write_context():
                for document_id, title, text in missing:
                    self._insert_chunks(document_id, title, text)
            last_id = missing[-1][0]

    def _bulk_write_context(self):
        @contextmanager
        def transaction():
            self._db.execute("BEGIN")
            try:
                yield
            except Exception:
                self._db.rollback()
                raise
            else:
                self._db.commit()
        return transaction()

    def contains_document(self, document_id: str) -> bool:
        return self._db.execute(
            "SELECT 1 FROM source_documents WHERE document_id=?",
            (document_id,)).fetchone() is not None

    @staticmethod
    def _source_file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _source_file_is_current(self, path: Path, document_id: str, *,
                                verify_content: bool = False) -> bool:
        try:
            stat = path.stat()
        except OSError:
            return False
        row = self._db.execute(
            "SELECT size_bytes,mtime_ns,file_sha256 FROM source_file_state "
            "WHERE document_id=?", (document_id,)).fetchone()
        if row is None or row[:2] != (stat.st_size, stat.st_mtime_ns):
            return False
        if not verify_content:
            return True
        return row[2] is not None and row[2] == self._source_file_hash(path)

    def _record_source_file(self, path: Path, document_id: str) -> None:
        stat = path.stat()
        digest = self._source_file_hash(path)
        self._db.execute(
            "INSERT OR REPLACE INTO source_file_state "
            "(document_id,size_bytes,mtime_ns,file_sha256) VALUES(?,?,?,?)",
            (document_id, stat.st_size, stat.st_mtime_ns, digest))

    @staticmethod
    def _row_document(row) -> SourceDocument:
        return SourceDocument(row[0], row[1], row[3], row[2],
                              tuple(json.loads(row[4])))

    def document(self, document_id: str) -> SourceDocument:
        row = self._db.execute(
            "SELECT document_id,title,location,body,pages_json,sha256 "
            "FROM source_documents WHERE document_id=?",
            (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return self._row_document(row)

    def exact_title_matches(self, title: str) -> list[ExactTitleMatch]:
        """Use the FTS title column to avoid ranking body passages for a title."""
        wanted = tuple(token.group().casefold() for token in word_matches(title))
        if not wanted:
            return []
        phrase = '"' + " ".join(wanted).replace('"', '""') + '"'
        rows = self._db.execute(
            "SELECT DISTINCT d.document_id,d.title,d.location "
            "FROM source_fts JOIN source_chunks c "
            "ON c.chunk_id=" + self._fts_chunk_key + " "
            "JOIN source_documents d ON d.document_id=c.document_id "
            "WHERE source_fts MATCH ? ORDER BY d.document_id",
            (f"title : {phrase}",))
        return [ExactTitleMatch(document_id, actual_title, location)
                for document_id, actual_title, location in rows
                if actual_title.casefold() == title.casefold()]

    def documents(self) -> list[SourceDocument]:
        rows = self._db.execute(
            "SELECT document_id,title,location,body,pages_json,sha256 "
            "FROM source_documents ORDER BY document_id")
        return [self._row_document(row) for row in rows]

    def document_count(self) -> int:
        return int(self._db.execute(
            "SELECT count(*) FROM source_documents").fetchone()[0])

    def search_latest(self, query: str, *, limit: int = 5
                      ) -> list[LatestSearchHit]:
        """Use FTS to find newest dated documents matching every topic term."""
        if not isinstance(query, str):
            raise TypeError("query must be a string")
        query = query.strip()
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        terms = _research_query_terms(query)
        if not terms:
            publication_date = "date(substr(body,instr(body,'Published: ')+11,10))"
            rows = self._db.execute(
                "SELECT document_id,title,location," + publication_date +
                " FROM source_documents WHERE " + publication_date +
                " IS NOT NULL ORDER BY " + publication_date +
                " DESC,document_id ASC LIMIT ?", (limit,)).fetchall()
            results = []
            for document_id, _title, _location, date in rows:
                document = self.document(document_id)
                spans = self._token_spans(document.text)
                (snippet, start, end, page_number,
                 match_start, match_end) = CRMSResearchIndex._snippet(
                     document, set(), 120, spans)
                hit = SearchHit(
                    document.document_id, document.title, document.location,
                    0.0, snippet, start, end, (), page_number,
                    match_start, match_end)
                results.append(LatestSearchHit(hit, date))
            return results
        selects = []
        parameters: list[Any] = []
        for term_index, term in enumerate(terms):
            quoted = f'"{term.replace(chr(34), chr(34) * 2)}"'
            expression = f"title : {quoted} OR body : {quoted}"
            selects.append(
                "SELECT DISTINCT c.document_id, ? AS term_index, 0.0 AS rank "
                "FROM source_fts JOIN source_chunks c "
                "ON c.chunk_id=" + self._fts_chunk_key + " "
                "WHERE source_fts MATCH ?")
            parameters.extend((term_index, expression))
        publication_date = "date(substr(d.body,instr(d.body,'Published: ')+11,10))"
        sql = (
            "WITH term_hits AS (" + " UNION ALL ".join(selects) + "), "
            "matched AS (SELECT document_id,SUM(rank) AS rank, "
            "COUNT(DISTINCT term_index) AS term_count FROM term_hits "
            "GROUP BY document_id) "
            "SELECT d.document_id,d.title,d.location," + publication_date + ","
            "m.rank FROM matched m JOIN source_documents d "
            "ON d.document_id=m.document_id "
            "WHERE m.term_count=? AND " + publication_date + " IS NOT NULL "
            "ORDER BY " + publication_date + " DESC,m.rank ASC,d.document_id ASC "
            "LIMIT ?")
        parameters.extend((len(terms), limit))
        rows = self._db.execute(sql, parameters).fetchall()
        results = []
        query_terms = set(terms)
        for document_id, _title, _location, publication_date, rank in rows:
            document = self.document(document_id)
            spans = self._token_spans(document.text)
            (snippet, start, end, page_number,
             match_start, match_end) = CRMSResearchIndex._snippet(
                 document, query_terms, 120, spans)
            hit = SearchHit(
                document.document_id, document.title, document.location,
                -float(rank), snippet, start, end, tuple(terms), page_number,
                match_start, match_end)
            results.append(LatestSearchHit(hit, publication_date))
        return results

    def source_list(self, *, limit: int = 50, offset: int = 0
                    ) -> list[tuple[str, str, str | None]]:
        if type(limit) is not int or limit < 1 or type(offset) is not int or offset < 0:
            raise ValueError("source-list limit must be positive and offset non-negative")
        return list(self._db.execute(
            "SELECT document_id,title,location FROM source_documents "
            "ORDER BY document_id LIMIT ? OFFSET ?", (limit, offset)))

    def corpus_stats(self) -> tuple[int, int]:
        row = self._db.execute(
            "SELECT count(*), COALESCE(sum(length(CAST(body AS BLOB))),0) "
            "FROM source_documents").fetchone()
        return int(row[0]), int(row[1])

    def search(self, query: str, *, limit: int = 5,
               context_chars: int = 120) -> list[SearchHit]:
        query = _text(query, "query")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if type(context_chars) is not int or context_chars < 0:
            raise ValueError("context_chars must be a non-negative integer")
        terms = _research_query_terms(query)
        focus_terms = _research_query_focus_terms(query)
        count = self.document_count()
        if not terms or count == 0:
            return []
        self._refresh_term_document_frequency_cache()
        query_words = tuple(match.group().casefold()
                            for match in word_matches(query))
        prose_preferred = _prefers_prose_sources(query)
        programming_query = _is_programming_query(query)
        term_weights = {}
        for term in terms:
            frequency = self._term_document_frequency(term)
            term_weights[term] = math.log(
                1 + (count - frequency + 0.5) / (frequency + 0.5)) \
                * (8.0 if term in focus_terms else 1.0)
        quoted = [f'"{term.replace(chr(34), chr(34) * 2)}"'
                  for term in terms]
        expression = " OR ".join(
            f"title : {term} OR body : {term}" for term in quoted)
        source_filter = ""
        parameters: list[Any] = [expression]
        if prose_preferred:
            suffix_clauses = " OR ".join(
                "lower(coalesce(d.location,'')) LIKE ?"
                for _suffix in _CODE_SOURCE_SUFFIXES)
            source_filter = f" AND NOT ({suffix_clauses})"
            parameters.extend(f"%{suffix}" for suffix in sorted(
                _CODE_SOURCE_SUFFIXES))
        candidate_chunks_per_document = 4
        context_margin = 1200
        rank_expression = "bm25(source_fts,0,1.5,1.0) AS rank "
        if programming_query:
            code_suffix_clauses = " OR ".join(
                "lower(coalesce(d.location,'')) LIKE '%" + suffix + "'"
                for suffix in sorted(_CODE_SOURCE_SUFFIXES))
            rank_expression = (
                f"CASE WHEN ({code_suffix_clauses}) "
                "THEN bm25(source_fts,0,1.5,1.0)*3.0 "
                "ELSE bm25(source_fts,0,1.5,1.0) END AS rank ")
        sql = (
            "WITH chunk_hits AS ("
            "SELECT c.chunk_id,c.document_id,c.start_offset,c.end_offset,"
            + rank_expression +
            "FROM source_fts JOIN source_chunks c "
            "ON c.chunk_id=" + self._fts_chunk_key + " "
            "JOIN source_documents d ON d.document_id=c.document_id "
            "WHERE source_fts MATCH ?" + source_filter + "), ranked_chunks AS ("
            "SELECT chunk_id,document_id,start_offset,end_offset,rank,"
            "row_number() OVER (PARTITION BY document_id "
            "ORDER BY rank ASC,chunk_id ASC) AS chunk_rank "
            "FROM chunk_hits), ranked_documents AS ("
            "SELECT document_id,rank,"
            "row_number() OVER (ORDER BY rank ASC,document_id ASC) "
            "AS document_rank FROM ranked_chunks WHERE chunk_rank=1) "
            "SELECT r.document_id,d.title,d.location,d.pages_json,"
            "length(d.body),r.rank,"
            "r.start_offset,r.end_offset,r.chunk_rank,"
            "max(0,r.start_offset-?) AS context_start,"
            "substr(d.body,max(1,r.start_offset-?+1),"
            "r.end_offset-max(0,r.start_offset-?)+?) AS context_text "
            "FROM ranked_chunks r JOIN ranked_documents rd "
            "ON rd.document_id=r.document_id "
            "JOIN source_documents d ON d.document_id=r.document_id "
            "WHERE rd.document_rank<=? AND r.chunk_rank<=? "
            "ORDER BY rd.document_rank,r.chunk_rank")
        parameters.extend((context_margin, context_margin, context_margin,
                           context_margin, limit, candidate_chunks_per_document))
        rows = self._db.execute(sql, parameters).fetchall()
        title_tokens: dict[str, set[str]] = {}
        page_offsets_cache: dict[str, list[tuple[int, int, int]]] = {}
        best_by_document: dict[
            str, tuple[tuple[float, int, int, int], SearchHit]] = {}
        for (document_id, title, location, pages_json, document_length, rank,
             chunk_start,
             _chunk_end, chunk_rank, context_start, context_text) in rows:
            spans = self._token_spans(context_text)
            if not spans:
                continue
            known_title_terms = title_tokens.setdefault(
                title, {token.casefold() for token, _, _
                        in self._token_spans(title)})
            context_terms = {token.casefold() for token, _, _ in spans}
            matched = tuple(term for term in terms
                            if term in context_terms or term in known_title_terms)
            if not matched:
                continue
            local_document = SourceDocument(
                document_id, title, context_text, location, ())
            (snippet, local_start, local_end, _page_number,
             local_match_start, local_match_end) = (
                CRMSResearchIndex._snippet(
                    local_document, set(matched), context_chars, spans,
                    term_weights=term_weights))
            if ((local_start == 0 and context_start > 0)
                    or (local_end == len(context_text)
                        and context_start + len(context_text) < document_length)):
                # The local window clipped a sentence. Do not present that
                # fragment as a complete source sentence; another candidate
                # chunk may contain the full sentence.
                continue
            if local_match_start is not None:
                local_match_start += context_start
                local_match_end += context_start
            start = context_start + local_start
            end = context_start + local_end
            page_number = None
            if pages_json != "[]" and local_match_start is not None:
                page_offsets = page_offsets_cache.get(document_id)
                if page_offsets is None:
                    page_offsets = []
                    page_offset = 0
                    for page_index, page in enumerate(
                            json.loads(pages_json), start=1):
                        page_offsets.append((
                            page_offset, page_offset + len(page), page_index))
                        page_offset += len(page) + len("\n\f\n")
                    page_offsets_cache[document_id] = page_offsets
                page_number = next((page for start, page_end, page
                                    in page_offsets
                                    if start <= local_match_start < page_end),
                                   None)
            snippet_terms = {token.casefold() for token, _, _
                             in self._token_spans(snippet)}
            covered_terms = snippet_terms & set(matched)
            coverage_score = sum(term_weights.get(term, 1.0)
                                 for term in covered_terms)
            hit = SearchHit(
                document_id, title, location, -float(rank), snippet,
                start, end, matched, page_number, local_match_start,
                local_match_end)
            # The FTS rank identifies promising source chunks; sentence
            # coverage chooses the answer-bearing excerpt among those chunks.
            key = (coverage_score, len(covered_terms), -int(chunk_rank), -start)
            previous = best_by_document.get(document_id)
            if previous is None or key > previous[0]:
                best_by_document[document_id] = (key, hit)
        return [item[1] for item in sorted(
            best_by_document.values(),
            key=lambda item: (-item[1].score, item[1].document_id))]

    def verify_hit(self, hit: SearchHit) -> SourceDocument:
        document = self.document(hit.document_id)
        single = CRMSResearchIndex()
        single.add_document(document.document_id, document.title, document.text,
                            document.location, pages=document.pages)
        return single.verify_hit(hit)

    def citation(self, hit: SearchHit) -> str:
        document = self.verify_hit(hit)
        digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        citation = (f"{hit.document_id}#sha256={digest}"
                    f"&chars={hit.start}:{hit.end}")
        if hit.page_number is not None:
            citation += (f"&page={hit.page_number}"
                         f"&match={hit.match_start}:{hit.match_end}")
        return citation

    def resolve_citation(self, citation: str) -> str:
        marker = "#sha256="
        if marker not in citation or "&chars=" not in citation:
            raise ValueError("malformed source citation")
        document_id, remainder = citation.rsplit(marker, 1)
        digest, span = remainder.split("&chars=", 1)
        try:
            offsets, *page_fields = span.split("&page=", 1)
            start_text, end_text = offsets.split(":", 1)
            start, end = int(start_text), int(end_text)
            page_number = None
            match_start = match_end = None
            if page_fields:
                page_and_match = page_fields[0].split("&match=", 1)
                page_number = int(page_and_match[0])
                match_start_text, match_end_text = page_and_match[1].split(":", 1)
                match_start, match_end = int(match_start_text), int(match_end_text)
        except (ValueError, IndexError) as error:
            raise ValueError("malformed source citation") from error
        document = self.document(document_id)
        actual_digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
        if digest != actual_digest:
            raise ValueError("citation refers to a different source revision")
        if start < 0 or end < start or end > len(document.text):
            raise ValueError("citation offsets are outside the source")
        if page_number is not None:
            if (not 1 <= page_number <= len(document.pages)
                    or match_start is None or match_end is None
                    or match_start < start or match_end < match_start or match_end > end):
                raise ValueError("page citation offsets are invalid")
            page_start = sum(len(page) + len("\n\f\n")
                             for page in document.pages[:page_number - 1])
            page_end = page_start + len(document.pages[page_number - 1])
            if not (page_start <= match_start < page_end
                    and start < page_end and end > page_start):
                raise ValueError("page citation does not match its source offsets")
        return document.text[start:end]

    def save(self, path: str | Path | None = None) -> None:
        if path is not None and Path(path).expanduser().resolve() != self.path:
            raise ValueError("SQLite corpus must be saved to its configured database path")
        self._db.commit()

    @classmethod
    def load(cls, path: str | Path) -> "CRMSSQLiteResearchIndex":
        return cls(path)

    def close(self) -> None:
        self._db.commit()
        self._db.close()
