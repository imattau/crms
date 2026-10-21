"""Phase 7 corpus program: audited ingestion, sharded FTS, and clean-room QA.

The program keeps three things separate:

* a per-document licence and provenance record;
* the cleaned source text in sharded SQLite FTS indexes;
* a frozen evaluation question set whose text and expected phrases are never
  ingested (the target documents remain searchable).

The builder is deterministic apart from timestamps. It accepts documents from
existing CRMS SQLite indexes and from local text/code files, applies the same
licence, quality, language, PII, deduplication, and boilerplate rules, and
writes a small catalog plus one FTS shard per configured partition.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from crms_research import (
    CRMSSQLiteResearchIndex, SearchHit, SourceDocument,
    _is_programming_query, _research_query_terms, _sentence_spans,
)
from crms_text import iter_word_matches, word_matches

PROJECT = Path(__file__).resolve().parent
FORMAT = "crms-phase7-corpus"
MODEL_FORMAT = "crms-phase7-model"
VERSION = 1
CATALOG_SCHEMA_VERSION = 1
IMPORTER_VERSION = "crms-corpus-program/1.0"
DEFAULT_SHARDS = 8
DEFAULT_BATCH_SIZE = 512
CORE_ALLOWED_CLASSES = frozenset({"public-domain", "permissive", "share-alike"})
LICENCE_CLASSES = frozenset({
    "public-domain", "permissive", "share-alike", "copyleft",
    "restricted", "unknown",
})
DOMAINS = (
    "reference", "general", "code", "math", "science",
    "books", "docs", "qa", "translation", "dialogue",
)

_MIN_WORDS = 20
_MAX_CHARS = 4_000_000
_NEAR_DUP_WORDS = 50
_NEAR_DUP_DISTANCE = 6
_NEAR_DUP_CANDIDATE_CAP = 64


# ---------------------------------------------------------------------------
# Source and licence records


@dataclass(frozen=True)
class SourceProfile:
    """A source-level licence and attribution policy."""

    source_id: str
    licence: str
    licence_class: str
    licence_url: str
    attribution: str
    redistribution: str
    domains: tuple[str, ...]
    retrieved_at: str
    retrieval: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "licence": self.licence,
            "licence_class": self.licence_class,
            "licence_url": self.licence_url,
            "attribution": self.attribution,
            "redistribution": self.redistribution,
            "domains": list(self.domains),
            "retrieved_at": self.retrieved_at,
            "retrieval": self.retrieval,
        }


@dataclass(frozen=True)
class LicenceAudit:
    document_id: str
    source_id: str
    licence: str
    licence_class: str
    licence_url: str
    attribution: str
    redistribution: str
    retrieved_at: str
    revision: str
    domains: tuple[str, ...]
    retrieval: str
    errors: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.errors


def _today() -> str:
    return date.today().isoformat()


def _default_profiles() -> dict[str, SourceProfile]:
    retrieved = _today()
    return {
        "wiki": SourceProfile(
            "simplewiki", "CC BY-SA 4.0", "share-alike",
            "https://creativecommons.org/licenses/by-sa/4.0/",
            "Simple English Wikipedia contributors, CC BY-SA 4.0",
            "allowed", ("reference", "general"), "2026-10-20",
            "Wikimedia dump, existing local source index",),
        "project": SourceProfile(
            "crms-project", "MIT License", "permissive",
            "https://opensource.org/license/mit",
            "CRMS project contributors, MIT License", "allowed",
            ("code", "docs"), retrieved, "local repository",),
        "arxiv": SourceProfile(
            "arxiv-metadata", "CC0 1.0 (bibliographic metadata)", "public-domain",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            "arXiv metadata contributors, CC0 1.0", "allowed",
            ("science", "research"), "2026-10-20",
            "arXiv API, existing local source index",),
        "pmc": SourceProfile(
            "pmc-open-access", "CC BY 4.0", "permissive",
            "https://creativecommons.org/licenses/by/4.0/",
            "PMC open-access article authors, CC BY 4.0", "allowed",
            ("science",), "2026-10-20",
            "PMC Open Access subset, existing local source index",),
        "curated": SourceProfile(
            "curated-local", "Python Software Foundation License Version 2",
            "permissive", "https://docs.python.org/3/license.html",
            "Python Software Foundation, PSF License Version 2", "allowed",
            ("docs", "reference"), "2026-10-18", "local curated source",),
        "conversation": SourceProfile(
            "user-design-notes", "Unknown user-supplied text", "unknown",
            "https://example.invalid/user-supplied-text",
            "User-supplied design note", "excluded", ("docs",), retrieved,
            "local user attachment",),
        "unknown": SourceProfile(
            "unknown-source", "Unknown", "unknown",
            "https://example.invalid/unknown-licence",
            "Unknown source", "excluded", ("general",), retrieved,
            "unknown",),
    }


def _first_http_url(location: str | None) -> str:
    if not location:
        return ""
    match = re.search(r"https?://[^\s\]]+", location)
    return match.group(0) if match else ""


def _wiki_revision(location: str | None, body: str) -> str:
    for source in (location or "", body[:2000]):
        match = re.search(r"\brevision:\s*(\d+)\b", source, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _arxiv_profile(body: str, base: SourceProfile) -> SourceProfile:
    head = body[:4000]
    # Full text is only present when the importer recorded an observed or
    # declared article licence. Metadata-only records are CC0 metadata.
    article_license = ""
    match = re.search(
        r"(?:Article license observed via OAI|Declared license):\s*([^\n]+)",
        head, re.IGNORECASE)
    if match:
        article_license = match.group(1).strip()
    folded = article_license.casefold()
    if article_license and not re.search(
            r"cc0|creativecommons\.org/publicdomain/zero|cc by(?![- ]?nc)|"
            r"creativecommons\.org/licenses/by/", folded):
        return SourceProfile(
            base.source_id, "Unverified article licence", "unknown",
            base.licence_url, base.attribution, "excluded", base.domains,
            base.retrieved_at, base.retrieval)
    if "cc by" in folded or "creativecommons.org/licenses/by/" in folded:
        return SourceProfile(
            "arxiv-cc-by", "CC BY 4.0", "permissive",
            "https://creativecommons.org/licenses/by/4.0/",
            "arXiv article authors, CC BY 4.0", "allowed",
            base.domains, base.retrieved_at, base.retrieval)
    return base


def _pmc_profile(body: str, base: SourceProfile) -> SourceProfile:
    head = body[:4000]
    match = re.search(
        r"(?:Redistribution license|License):\s*(CC BY|CC0)[^\n]*",
        head, re.IGNORECASE)
    if not match:
        return SourceProfile(
            base.source_id, "Unverified PMC licence", "unknown",
            base.licence_url, base.attribution, "excluded", base.domains,
            base.retrieved_at, base.retrieval)
    code = match.group(1).upper()
    if code == "CC0":
        return SourceProfile(
            "pmc-cc0", "CC0 1.0", "public-domain",
            "https://creativecommons.org/publicdomain/zero/1.0/",
            "PMC open-access article authors, CC0 1.0", "allowed",
            base.domains, base.retrieved_at, base.retrieval)
    return base


def _curated_profile(body: str, base: SourceProfile) -> SourceProfile:
    match = re.search(r"(?im)^\s*Page license:\s*(.+)$", body[:4000])
    if not match:
        return SourceProfile(
            base.source_id, "Unverified curated licence", "unknown",
            base.licence_url, base.attribution, "excluded", base.domains,
            base.retrieved_at, base.retrieval)
    text = match.group(1).strip()
    if "Python Software Foundation" in text:
        return base
    if "public domain" in text.casefold():
        return SourceProfile(
            "curated-public-domain", "Public domain", "public-domain",
            base.licence_url, "Curated public-domain source", "allowed",
            base.domains, base.retrieved_at, base.retrieval)
    return SourceProfile(
        base.source_id, text, "unknown", base.licence_url, base.attribution,
        "excluded", base.domains, base.retrieved_at, base.retrieval)


def profile_for_document(document_id: str, location: str | None,
                         body: str,
                         profiles: Mapping[str, SourceProfile] | None = None
                         ) -> SourceProfile:
    """Infer the source policy from the stable document ID and stored text."""
    defaults = dict(_default_profiles())
    if profiles:
        defaults.update(profiles)
    prefix = document_id.split(":", 1)[0].casefold()
    base = defaults.get(prefix, defaults["unknown"])
    if prefix == "wiki":
        revision = _wiki_revision(location, body)
        if revision and base.licence_class != "unknown":
            return base
        return SourceProfile(
            base.source_id, "Unverified Wikipedia licence", "unknown",
            base.licence_url, base.attribution, "excluded", base.domains,
            base.retrieved_at, base.retrieval)
    if prefix == "arxiv":
        return _arxiv_profile(body, base)
    if prefix == "pmc":
        return _pmc_profile(body, base)
    if prefix == "curated":
        return _curated_profile(body, base)
    return base


def _revision_for(document_id: str, location: str | None, body: str,
                  profile: SourceProfile) -> str:
    prefix = document_id.split(":", 1)[0].casefold()
    if prefix == "wiki":
        return _wiki_revision(location, body)
    if prefix == "pmc":
        match = re.search(r"source revision\s+([0-9a-f]+)", body[:4000],
                          re.IGNORECASE)
        if match:
            return match.group(1)
    if prefix == "arxiv":
        match = re.search(r"arXiv ID and version:\s*(\S+)", body[:4000])
        if match:
            return match.group(1)
        return document_id.partition(":")[2]
    if prefix == "curated":
        match = re.search(r"(?im)^\s*Captured:\s*(\d{4}-\d{2}-\d{2})\s*$",
                          body[:4000])
        if match:
            return match.group(1)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def audit_licence(document_id: str, location: str | None, body: str,
                  *, profile: SourceProfile | None = None,
                  profiles: Mapping[str, SourceProfile] | None = None
                  ) -> LicenceAudit:
    """Return a per-document manifest record and explicit audit errors."""
    profile = profile or profile_for_document(
        document_id, location, body, profiles)
    errors: list[str] = []
    if not profile.licence.strip():
        errors.append("missing licence")
    if profile.licence_class not in LICENCE_CLASSES:
        errors.append(f"unknown licence class: {profile.licence_class}")
    if profile.licence_class == "unknown":
        errors.append("licence is unknown")
    if profile.licence_class not in CORE_ALLOWED_CLASSES:
        errors.append(f"licence class is not packaged: {profile.licence_class}")
    if profile.redistribution != "allowed":
        errors.append(f"redistribution is {profile.redistribution}")
    if not profile.attribution.strip():
        errors.append("missing attribution")
    if not profile.licence_url.strip():
        errors.append("missing licence URL")
    if not profile.retrieved_at.strip():
        errors.append("missing retrieval date")
    revision = _revision_for(document_id, location, body, profile)
    if not revision:
        errors.append("missing revision or content hash")
    return LicenceAudit(
        document_id=document_id, source_id=profile.source_id,
        licence=profile.licence, licence_class=profile.licence_class,
        licence_url=profile.licence_url, attribution=profile.attribution,
        redistribution=profile.redistribution,
        retrieved_at=profile.retrieved_at, revision=revision,
        domains=profile.domains, retrieval=profile.retrieval,
        errors=tuple(errors))


# ---------------------------------------------------------------------------
# Cleaning, filtering, language/script detection, and PII


_BOILERPLATE_LINE = re.compile(
    r"(?i)^\s*(?:(?:retrieved from|this page was last|text is available under|"
    r"privacy policy|about wikipedia|disclaimers|contact wikipedia|"
    r"mobile view|jump to content|main page|random article|donate|"
    r"create account|log in|toggle|wikimedia foundation|powered by|"
    r"cookie statement|terms of use|developers|statistics|"
    r"category:|defaultsort:|reflist|other websites\b|related pages\b|"
    r"see also\b|further reading\b|external links\b|more reading\b|"
    r"authority control\b|commonscat\b|wikiquote-en\b|wikispecies\b|"
    r"s-start\b|s-bef\b|s-ttl\b|s-aft\b|end\b).*|references\s*:?)\s*$",
    re.IGNORECASE)
_SECTION_HEADINGS = frozenset({
    "references", "other websites", "related pages", "see also",
    "further reading", "external links", "more reading", "authority control",
    "notes", "sources", "citations",
})
_WIKI_FILE = re.compile(r"\[\[(?:File|Image|Category):[^\]]*\]\]", re.I)
_WIKI_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_WIKI_LEFTOVER = re.compile(r"\[\[|\]\]")
_WIKI_FIELD = re.compile(r"^\s*[A-Za-z][\w -]{0,48}\s*=\s*\S")
_WIKI_NAV = re.compile(
    r"(?i)^\s*(?:commons|wikiquote|wikispecies|webarchive|chem-stub|"
    r"religion-stub|math-stub|stub|flagicon|reflist|refbegin|refend)\b"
    r"[^A-Za-z0-9]*[;:]?\s*")

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(
    r"(?<![\w])(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{2,4}\)[\s.-]?|\d{3,4}[\s.-])"
    r"\d{3,4}[\s.-]\d{3,4}(?![\w])")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_NAMED_SECRET = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*"
    r"['\"]?([A-Za-z0-9_+/=-]{32,})")


def _strip_wiki_markup(text: str) -> tuple[str, int]:
    removed = 0
    text, count = _WIKI_FILE.subn(" ", text)
    removed += count
    def link(match: re.Match[str]) -> str:
        return (match.group(2) or match.group(1)).strip()
    text, count = _WIKI_LINK.subn(link, text)
    removed += count
    text, count = _WIKI_LEFTOVER.subn("", text)
    removed += count
    return text, removed


def _strip_trailing_sections(lines: list[str]) -> tuple[list[str], int]:
    """Drop reference/navigation tails, which are not answer-bearing prose."""
    for index in range(len(lines) - 1, -1, -1):
        heading = lines[index].strip().casefold().rstrip(":")
        if heading in _SECTION_HEADINGS:
            return lines[:index], len(lines) - index
    return lines, 0


def _drop_leading_captions(lines: list[str]) -> tuple[list[str], int]:
    """Drop image/caption residue before the first complete prose line."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if len(stripped.split()) >= 6 and stripped[-1:] in ".!?":
            return lines[index:], index
    return lines, 0


def clean_text(text: str, source_id: str) -> tuple[str, dict[str, int]]:
    """Normalize, remove boilerplate, and return the cleaned text plus counts."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    removed = 0
    if source_id.startswith("pmc"):
        abstract = text.find("Abstract:")
        if abstract > 0:
            text = text[abstract:]
        else:
            # No labelled abstract: drop the licence/front-matter block.
            source = text.rfind("Source: https://")
            if source > 0:
                newline = text.find("\n", source)
                if newline > 0:
                    text = text[newline + 1:]
    if source_id.startswith("simplewiki") or source_id == "wiki":
        text, wiki_removed = _strip_wiki_markup(text)
        removed += wiki_removed
    lines: list[str] = []
    in_wiki_field_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            in_wiki_field_block = False
            continue
        if _BOILERPLATE_LINE.fullmatch(stripped):
            removed += 1
            continue
        if _WIKI_NAV.match(stripped):
            removed += 1
            continue
        if source_id.startswith("simplewiki"):
            if stripped.casefold() in {
                    "multiple image", "infobox", "taxobox",
                    "automatic taxobox", "infobox christian leader"}:
                in_wiki_field_block = True
                removed += 1
                continue
            if in_wiki_field_block and _WIKI_FIELD.match(stripped):
                removed += 1
                continue
            in_wiki_field_block = False
        # Keep indentation for code so generated snippets remain readable.
        if source_id == "crms-project":
            line = line.rstrip()
            if not line.strip():
                continue
        else:
            line = re.sub(r"[ \t]+", " ", stripped)
        lines.append(line)
    lines, tail_removed = _strip_trailing_sections(lines)
    removed += tail_removed
    if source_id.startswith("simplewiki"):
        lines, leading_removed = _drop_leading_captions(lines)
        removed += leading_removed
    # Collapse runs of blank lines while preserving paragraph and code blocks.
    output: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                output.append("")
            blank = True
        else:
            output.append(line)
            blank = False
    cleaned = "\n".join(output).strip()
    return cleaned, {"boilerplate_removed": removed}


def detect_language(text: str) -> tuple[str, float]:
    """A small deterministic stopword profile, not a statistical classifier."""
    sample = text[:6000].casefold()
    words = re.findall(r"[a-zà-ÿ']+", sample)
    if not words:
        return "unknown", 0.0
    profiles = {
        "en": {"the", "and", "of", "to", "in", "is", "that", "for", "with",
               "as", "was", "on", "by", "this", "are", "from", "it", "be"},
        "es": {"el", "la", "de", "que", "y", "en", "un", "una", "los",
               "las", "del", "por", "con", "para", "es", "son"},
        "fr": {"le", "la", "de", "et", "les", "des", "un", "une", "du",
               "en", "est", "que", "pour", "dans", "sur", "au"},
        "de": {"der", "die", "das", "und", "von", "zu", "den", "mit",
               "ist", "im", "ein", "eine", "auf", "für", "als"},
        "it": {"il", "la", "di", "che", "e", "in", "un", "una", "per",
               "con", "del", "della", "sono", "è"},
        "pt": {"o", "a", "de", "que", "e", "em", "um", "uma", "para",
               "com", "do", "da", "os", "as", "são"},
    }
    counts = {name: sum(1 for word in words if word in stop)
              for name, stop in profiles.items()}
    best, hits = max(counts.items(), key=lambda item: item[1])
    if hits < 2:
        # Code and short reference records have few ordinary stopwords but are
        # still Latin-script English. Keep them when the script is clear.
        latin = sum(1 for char in sample if "a" <= char <= "z")
        return ("en", 0.5) if latin >= max(8, len(sample) // 4) else ("unknown", 0.0)
    return best, hits / max(1, len(words))


def detect_script(text: str) -> str:
    counts = Counter()
    for char in text[:10000]:
        code = ord(char)
        if ("a" <= char.casefold() <= "z") or 0x00C0 <= code <= 0x024F:
            counts["latin"] += 1
        elif 0x0400 <= code <= 0x04FF:
            counts["cyrillic"] += 1
        elif 0x0600 <= code <= 0x06FF:
            counts["arabic"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["han"] += 1
        elif 0x3040 <= code <= 0x30FF:
            counts["kana"] += 1
        elif 0xAC00 <= code <= 0xD7AF:
            counts["hangul"] += 1
    if not counts:
        return "unknown"
    return counts.most_common(1)[0][0]


def scan_sensitive(text: str) -> tuple[str, dict[str, int], str]:
    """Redact ordinary PII and reject credential material outright."""
    findings: Counter[str] = Counter()
    if _PRIVATE_KEY.search(text):
        findings["private_key"] += 1
        return text, dict(findings), "private key material"
    if _AWS_KEY.search(text):
        findings["aws_access_key"] += 1
        return text, dict(findings), "cloud access key"
    secret = _NAMED_SECRET.search(text)
    if secret is not None:
        # A high-entropy assignment is treated as a secret. Short test strings
        # and prose uses such as "password: required" are left alone.
        value = secret.group(1)
        if len(set(value)) >= 10:
            findings["named_secret"] += 1
            return text, dict(findings), "named secret"
    text, count = _EMAIL.subn("[email]", text)
    findings["email"] += count
    text, count = _SSN.subn("[ssn]", text)
    findings["ssn"] += count
    text, count = _PHONE.subn("[phone]", text)
    findings["phone"] += count
    return text, dict(findings), ""


# ---------------------------------------------------------------------------
# Near-duplicate detection


def _token_hash(token: str) -> int:
    return binascii.crc32(token.encode("utf-8")) & 0xFFFFFFFF


def simhash64(text: str, *, max_tokens: int = 20_000) -> int:
    """A stable 64-bit word-frequency SimHash for near-duplicate banding."""
    words = [match.group().casefold() for match in iter_word_matches(text)]
    if len(words) > max_tokens:
        step = max(1, len(words) // max_tokens)
        words = words[::step][:max_tokens]
    counts = Counter(words)
    vector = [0] * 64
    for token, weight in counts.items():
        hashed = _token_hash(token)
        for bit in range(64):
            vector[bit] += weight if (hashed >> bit) & 1 else -weight
    return sum(1 << bit for bit in range(64) if vector[bit] > 0)


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _shingle_sketch(text: str, *, shingle_words: int = 5,
                    sample_size: int = 128, keep: int = 32) -> tuple[int, ...]:
    """A bottom-k sketch of 5-word hashes for a second near-duplicate check.

    SimHash alone is too permissive on short records that share source
    boilerplate (for example arXiv metadata). The sketch requires substantial
    shingle overlap before two distinct IDs are treated as near duplicates.
    """
    words = [match.group().casefold() for match in iter_word_matches(text)]
    if len(words) < shingle_words:
        return ()
    total = len(words) - shingle_words + 1
    step = max(1, total // sample_size)
    hashes = {
        _token_hash(" ".join(words[index:index + shingle_words]))
        for index in range(0, total, step)
    }
    return tuple(sorted(hashes)[:keep])


def _sketch_similarity(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if not left or not right:
        return 0.0
    left_set, right_set = set(left), set(right)
    return len(left_set & right_set) / len(left_set | right_set)


class NearDuplicateIndex:
    """Exact hashes plus banded SimHash candidates confirmed by shingles."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.exact: dict[str, str] = {}
        self.bands: list[dict[int, list[tuple[int, str, tuple[int, ...]]]]] = [
            defaultdict(list) for _ in range(4)]

    def find(self, digest: str, fingerprint: int, words: int,
             sketch: tuple[int, ...]) -> tuple[str, str] | None:
        previous = self.exact.get(digest)
        if previous is not None:
            return "exact", previous
        if not self.enabled or words < _NEAR_DUP_WORDS:
            return None
        candidates: set[tuple[int, str, tuple[int, ...]]] = set()
        for band in range(4):
            key = (fingerprint >> (band * 16)) & 0xFFFF
            candidates.update(self.bands[band].get(key, ())[: _NEAR_DUP_CANDIDATE_CAP])
        for other, document_id, other_sketch in candidates:
            if (_hamming(fingerprint, other) <= _NEAR_DUP_DISTANCE
                    and _sketch_similarity(sketch, other_sketch) >= 0.75):
                return "near", document_id
        return None

    def add(self, digest: str, fingerprint: int, document_id: str,
            words: int, sketch: tuple[int, ...]) -> None:
        self.exact[digest] = document_id
        if not self.enabled or words < _NEAR_DUP_WORDS:
            return
        for band in range(4):
            key = (fingerprint >> (band * 16)) & 0xFFFF
            bucket = self.bands[band][key]
            if len(bucket) < _NEAR_DUP_CANDIDATE_CAP:
                bucket.append((fingerprint, document_id, sketch))


# ---------------------------------------------------------------------------
# Catalog and builder


_CATALOG_SCHEMA = """
CREATE TABLE corpus_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_id TEXT NOT NULL,
    shard INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    location TEXT,
    retrieved_at TEXT NOT NULL,
    revision TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    licence TEXT NOT NULL,
    licence_class TEXT NOT NULL,
    licence_url TEXT NOT NULL,
    attribution TEXT NOT NULL,
    redistribution TEXT NOT NULL,
    retrieval TEXT NOT NULL,
    importer_version TEXT NOT NULL,
    domains TEXT NOT NULL,
    language TEXT NOT NULL,
    script TEXT NOT NULL,
    word_count INTEGER NOT NULL,
    byte_count INTEGER NOT NULL,
    original_chars INTEGER NOT NULL,
    cleaned_chars INTEGER NOT NULL,
    boilerplate_removed INTEGER NOT NULL,
    redactions_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL
);
CREATE INDEX documents_source ON documents(source_id);
CREATE INDEX documents_licence ON documents(licence_class);
CREATE INDEX documents_shard ON documents(shard);
CREATE TABLE rejected (
    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL,
    licence_class TEXT,
    word_count INTEGER,
    rejected_at TEXT NOT NULL
);
CREATE INDEX rejected_reason ON rejected(reason);
"""


def _title_from_text(text: str, fallback: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:240]
    return fallback[:240]


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT))
    except ValueError:
        return str(path)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CorpusBuilder:
    """Build one audited, sharded corpus from a stream of documents."""

    def __init__(self, output: str | Path, *, shards: int = DEFAULT_SHARDS,
                 holdout_ids: Iterable[str] = (), near_dedup: bool = True,
                 min_words: int = _MIN_WORDS,
                 profiles: Mapping[str, SourceProfile] | None = None,
                 replace: bool = False, batch_size: int = DEFAULT_BATCH_SIZE):
        if type(shards) is not int or not 1 <= shards <= 64:
            raise ValueError("shards must be between 1 and 64")
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        self.output = Path(output).expanduser().resolve()
        if self.output.exists() and not replace:
            raise FileExistsError(f"corpus directory already exists: {self.output}")
        if self.output.exists():
            shutil.rmtree(self.output)
        self.output.mkdir(parents=True)
        self.shards = shards
        self.batch_size = batch_size
        self.min_words = min_words
        self.profiles = dict(profiles or {})
        self.holdout_ids = set(holdout_ids)
        self.deduper = NearDuplicateIndex(enabled=near_dedup)
        self.near_dedup = near_dedup
        self.started = time.perf_counter()
        self._catalog = sqlite3.connect(str(self.output / "catalog.sqlite"))
        self._catalog.executescript(_CATALOG_SCHEMA)
        self._catalog.execute(
            "INSERT INTO corpus_meta(key,value) VALUES('format',?)", (FORMAT,))
        self._catalog.execute(
            "INSERT INTO corpus_meta(key,value) VALUES('version',?)",
            (str(VERSION),))
        self._catalog.execute(
            "INSERT INTO corpus_meta(key,value) VALUES('catalog_schema',?)",
            (str(CATALOG_SCHEMA_VERSION),))
        self._indexes = [
            CRMSSQLiteResearchIndex(self.output / f"shard-{index:02d}.sqlite")
            for index in range(shards)
        ]
        self._pending: dict[int, list[tuple[str, str, str, str]]] = defaultdict(list)
        self._pending_records: list[tuple[Any, ...]] = []
        self._seen: set[str] = set()
        self._stats: Counter[str] = Counter()
        self._by_source: Counter[str] = Counter()
        self._by_licence: Counter[str] = Counter()
        self._by_domain: Counter[str] = Counter()
        self._by_language: Counter[str] = Counter()
        self._by_script: Counter[str] = Counter()
        self._rejected: Counter[str] = Counter()
        self._rejected_rows: list[tuple[Any, ...]] = []
        self._input_sources: list[str] = []
        self._closed = False

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def _reject(self, document_id: str, source_id: str, reason: str,
                detail: str = "", *, licence_class: str | None = None,
                word_count: int | None = None) -> None:
        self._stats["rejected"] += 1
        self._rejected[reason] += 1
        self._rejected_rows.append((
            document_id, source_id, reason, detail[:500], licence_class,
            word_count, date.today().isoformat()))
        if len(self._rejected_rows) >= 512:
            self._flush_rejected()

    def _flush_rejected(self) -> None:
        if not self._rejected_rows:
            return
        self._catalog.executemany(
            "INSERT INTO rejected(document_id,source_id,reason,detail,"
            "licence_class,word_count,rejected_at) VALUES(?,?,?,?,?,?,?)",
            self._rejected_rows)
        self._catalog.commit()
        self._rejected_rows.clear()

    def add(self, document_id: str, title: str, text: str,
            location: str | None = None, *,
            profile: SourceProfile | None = None) -> str:
        """Audit and stage one document. Returns accepted/rejected reason."""
        document_id = str(document_id).strip()
        if not document_id:
            self._reject(document_id, "unknown", "missing_document_id")
            return "missing_document_id"
        if document_id in self.holdout_ids:
            self._reject(document_id, document_id.split(":", 1)[0],
                         "held_out", "excluded from ingestion by the frozen "
                         "evaluation fixture", word_count=None)
            return "held_out"
        if document_id in self._seen:
            self._reject(document_id, document_id.split(":", 1)[0],
                         "duplicate_id", "document ID already ingested")
            return "duplicate_id"
        self._seen.add(document_id)
        source_prefix = document_id.split(":", 1)[0]
        if not isinstance(text, str) or not text.strip():
            self._reject(document_id, source_prefix, "empty")
            return "empty"
        audit = audit_licence(
            document_id, location, text, profile=profile, profiles=self.profiles)
        if not audit.accepted:
            self._reject(document_id, audit.source_id, "licence_audit",
                         "; ".join(audit.errors), licence_class=audit.licence_class)
            return "licence_audit"
        cleaned, clean_info = clean_text(text, audit.source_id)
        if not cleaned.strip():
            self._reject(document_id, audit.source_id, "empty_after_cleaning",
                         licence_class=audit.licence_class)
            return "empty_after_cleaning"
        cleaned, sensitive, reject_reason = scan_sensitive(cleaned)
        if reject_reason:
            self._reject(document_id, audit.source_id, "sensitive_content",
                         reject_reason, licence_class=audit.licence_class)
            return "sensitive_content"
        words = sum(1 for _ in iter_word_matches(cleaned))
        if words < self.min_words:
            self._reject(document_id, audit.source_id, "too_short",
                         f"{words} words", licence_class=audit.licence_class,
                         word_count=words)
            return "too_short"
        if len(cleaned) > _MAX_CHARS:
            self._reject(document_id, audit.source_id, "too_large",
                         f"{len(cleaned)} characters",
                         licence_class=audit.licence_class, word_count=words)
            return "too_large"
        if cleaned.count("\ufffd") > 2:
            self._reject(document_id, audit.source_id, "encoding_damage",
                         f"{cleaned.count(chr(0xfffd))} replacement characters",
                         licence_class=audit.licence_class, word_count=words)
            return "encoding_damage"
        letters = sum(1 for char in cleaned if char.isalpha())
        if letters / max(1, len(cleaned)) < 0.15:
            self._reject(document_id, audit.source_id, "low_alpha_ratio",
                         f"{letters / max(1, len(cleaned)):.3f}",
                         licence_class=audit.licence_class, word_count=words)
            return "low_alpha_ratio"
        language, confidence = detect_language(cleaned)
        script = detect_script(cleaned)
        if script not in {"latin", "unknown"}:
            self._reject(document_id, audit.source_id, "non_latin_script",
                         script, licence_class=audit.licence_class,
                         word_count=words)
            return "non_latin_script"
        if language not in {"en", "unknown"}:
            self._reject(document_id, audit.source_id, "non_english",
                         f"{language} ({confidence:.2f})",
                         licence_class=audit.licence_class, word_count=words)
            return "non_english"
        digest = _sha256(cleaned)
        fingerprint = simhash64(cleaned)
        sketch = _shingle_sketch(cleaned)
        duplicate = self.deduper.find(digest, fingerprint, words, sketch)
        if duplicate is not None:
            kind, previous = duplicate
            self._reject(document_id, audit.source_id, f"duplicate_{kind}",
                         f"matches {previous}", licence_class=audit.licence_class,
                         word_count=words)
            return f"duplicate_{kind}"
        self.deduper.add(digest, fingerprint, document_id, words, sketch)
        shard = int.from_bytes(
            hashlib.sha256(document_id.encode("utf-8")).digest()[:4], "big"
        ) % self.shards
        title = _title_from_text(str(title), document_id)
        self._pending[shard].append((document_id, title, cleaned, location or ""))
        source_url = _first_http_url(location) or (location or "")
        self._pending_records.append((
            document_id, title, audit.source_id, shard, source_url,
            location or "", audit.retrieved_at, audit.revision,
            _sha256(text), digest, audit.licence, audit.licence_class,
            audit.licence_url, audit.attribution, audit.redistribution,
            audit.retrieval, IMPORTER_VERSION, json.dumps(list(audit.domains)),
            language, script, words, len(cleaned.encode("utf-8")), len(text),
            len(cleaned), clean_info["boilerplate_removed"],
            json.dumps(sensitive, sort_keys=True), f"{fingerprint:016x}"))
        self._stats["accepted"] += 1
        self._stats["words"] += words
        self._stats["bytes"] += len(cleaned.encode("utf-8"))
        self._by_source[audit.source_id] += 1
        self._by_licence[audit.licence_class] += 1
        for domain in audit.domains:
            self._by_domain[domain] += 1
        self._by_language[language] += 1
        self._by_script[script] += 1
        if sum(len(batch) for batch in self._pending.values()) >= self.batch_size:
            self.flush()
        return "accepted"

    def flush(self) -> None:
        for shard, batch in list(self._pending.items()):
            if not batch:
                continue
            index = self._indexes[shard]
            with index._bulk_write_context():
                for document_id, title, text, location in batch:
                    index.add_document(document_id, title, text, location)
            batch.clear()
        if self._pending_records:
            self._catalog.executemany(
                "INSERT INTO documents(document_id,title,source_id,shard,"
                "source_url,location,retrieved_at,revision,source_sha256,"
                "body_sha256,licence,licence_class,licence_url,attribution,"
                "redistribution,retrieval,importer_version,domains,language,"
                "script,word_count,byte_count,original_chars,cleaned_chars,"
                "boilerplate_removed,redactions_json,fingerprint) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                self._pending_records)
            self._catalog.commit()
            self._pending_records.clear()
        self._flush_rejected()

    def close(self) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("corpus builder is already closed")
        self.flush()
        self._closed = True
        for index in self._indexes:
            index._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            index._db.execute("PRAGMA journal_mode=DELETE")
            index.close()
        self._catalog.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._catalog.execute("PRAGMA journal_mode=DELETE")
        elapsed = max(0.0001, self.elapsed)
        summary = {
            "format": FORMAT,
            "model_format": MODEL_FORMAT,
            "version": VERSION,
            "catalog_schema": CATALOG_SCHEMA_VERSION,
            "importer_version": IMPORTER_VERSION,
            "built_at": date.today().isoformat(),
            "shards": self.shards,
            "near_dedup": self.near_dedup,
            "min_words": self.min_words,
            "holdout_documents": len(self.holdout_ids),
            "input_sources": self._input_sources,
            "documents": self._stats["accepted"],
            "words": self._stats["words"],
            "bytes": self._stats["bytes"],
            "rejected": self._stats["rejected"],
            "rejected_reasons": dict(sorted(self._rejected.items())),
            "by_source": dict(sorted(self._by_source.items())),
            "by_licence_class": dict(sorted(self._by_licence.items())),
            "by_domain": dict(sorted(self._by_domain.items())),
            "by_language": dict(sorted(self._by_language.items())),
            "by_script": dict(sorted(self._by_script.items())),
            "throughput": {
                "elapsed_seconds": round(elapsed, 3),
                "documents_per_second": round(self._stats["accepted"] / elapsed, 2),
                "words_per_second": round(self._stats["words"] / elapsed, 2),
            },
            "licence_coverage": _licence_coverage(self._catalog),
            "index_bytes": sum(
                path.stat().st_size for path in self.output.glob("shard-*.sqlite")),
            "catalog_bytes": (self.output / "catalog.sqlite").stat().st_size,
        }
        self._catalog.execute(
            "INSERT OR REPLACE INTO corpus_meta(key,value) VALUES('summary',?)",
            (json.dumps(summary, sort_keys=True),))
        self._catalog.commit()
        self._catalog.close()
        (self.output / "corpus.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        self._write_model_metadata(summary)
        return summary

    def _write_model_metadata(self, summary: Mapping[str, Any]) -> None:
        model = {
            "format": MODEL_FORMAT,
            "version": VERSION,
            "catalog": "catalog.sqlite",
            "shards": [f"shard-{index:02d}.sqlite" for index in range(self.shards)],
            "documents": summary["documents"],
            "words": summary["words"],
            "licence_coverage": summary["licence_coverage"]["coverage"],
            "clean_room_ready": True,
            "notes": (
                "Self-contained sharded FTS corpus. Original source indexes and "
                "files are not required at query time."),
        }
        (self.output / "model.json").write_text(
            json.dumps(model, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")


def _licence_coverage(catalog: sqlite3.Connection) -> dict[str, Any]:
    row = catalog.execute(
        "SELECT count(*), "
        "sum(CASE WHEN licence_class IN ('public-domain','permissive','share-alike') "
        "THEN 1 ELSE 0 END), "
        "sum(CASE WHEN attribution<>'' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN redistribution='allowed' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN revision<>'' THEN 1 ELSE 0 END), "
        "sum(CASE WHEN licence_url<>'' THEN 1 ELSE 0 END) "
        "FROM documents").fetchone()
    total = int(row[0] or 0)
    known = int(row[1] or 0)
    return {
        "documents": total,
        "redistributable_documents": known,
        "with_attribution": int(row[2] or 0),
        "redistribution_allowed": int(row[3] or 0),
        "with_revision": int(row[4] or 0),
        "with_licence_url": int(row[5] or 0),
        "coverage": (known / total) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Source discovery and local importers


def _iter_project_files(root: Path = PROJECT
                        ) -> Iterator[tuple[str, str, str, str]]:
    """Yield top-level code/docs and tracked documentation as project sources."""
    candidates: list[Path] = []
    for pattern in ("*.py", "*.md", "LICENSE", "CONTRIBUTING.md"):
        candidates.extend(sorted(root.glob(pattern)))
    candidates.extend(sorted((root / "docs").rglob("*.md")))
    candidates.extend(sorted((root / "experiments").rglob("*.py")))
    excluded_parts = {"__pycache__", ".git", "data", "corpus"}
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        relative = path.relative_to(root)
        if any(part in excluded_parts for part in relative.parts):
            continue
        if relative.as_posix().startswith(("experiments/reports/",)):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not text.strip():
            continue
        document_id = f"project:{relative.as_posix()}"
        title = _title_from_text(text, relative.as_posix())
        yield document_id, title, text, f"CRMS project file: {relative.as_posix()}"


def _source_specs(root: Path = PROJECT) -> list[dict[str, Any]]:
    """Return the default core acquisition inputs that exist locally."""
    academic = root / "data" / "crms_academic_simplewiki_research.sqlite"
    simplewiki = root / "data" / "crms_simplewiki_research.sqlite"
    arxiv = root / "data" / "crms_arxiv_cc0_ccby.sqlite"
    specs: list[dict[str, Any]] = []
    if academic.is_file():
        specs.append({
            "path": academic,
            "prefixes": ("wiki:", "arxiv:", "pmc:", "curated:"),
            "label": "academic-simplewiki-index",
        })
    elif simplewiki.is_file():
        specs.append({
            "path": simplewiki, "prefixes": ("wiki:",),
            "label": "simplewiki-index",
        })
        if arxiv.is_file():
            specs.append({
                "path": arxiv, "prefixes": ("arxiv:",),
                "label": "arxiv-index",
            })
    return specs


def _stream_index(path: Path, prefixes: Sequence[str]
                  ) -> Iterator[tuple[str, str, str | None, str]]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        clause = ""
        parameters: list[Any] = []
        if prefixes:
            clause = " WHERE " + " OR ".join(
                "document_id LIKE ?" for _ in prefixes)
            parameters = [f"{prefix}%" for prefix in prefixes]
        cursor = connection.execute(
            "SELECT document_id,title,location,body FROM source_documents"
            + clause + " ORDER BY document_id", parameters)
        for row in cursor:
            yield row[0], row[1], row[2], row[3]
    finally:
        connection.close()


def build_core_corpus(output: str | Path, *,
                      source_specs: Sequence[Mapping[str, Any]] | None = None,
                      include_project_files: bool = True,
                      project_root: Path = PROJECT,
                      shards: int = DEFAULT_SHARDS,
                      holdout_ids: Iterable[str] = (),
                      near_dedup: bool = True,
                      replace: bool = False,
                      limit: int | None = None,
                      progress: bool = False) -> dict[str, Any]:
    """Build the measured core corpus from local indexes and project sources."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    specs = list(source_specs if source_specs is not None
                 else _source_specs(project_root))
    if not specs and not include_project_files:
        raise ValueError("no corpus source inputs were found")
    builder = CorpusBuilder(
        output, shards=shards, holdout_ids=holdout_ids, near_dedup=near_dedup,
        profiles=None, replace=replace)
    considered = 0
    try:
        for spec in specs:
            path = Path(spec["path"]).expanduser()
            if not path.is_absolute():
                path = project_root / path
            if not path.is_file():
                raise FileNotFoundError(f"corpus source index does not exist: {path}")
            label = str(spec.get("label", path.name))
            builder._input_sources.append(
                f"{label}: {_display_path(path)}")
            prefixes = tuple(spec.get("prefixes", ()))
            for document_id, title, location, body in _stream_index(path, prefixes):
                if limit is not None and considered >= limit:
                    break
                considered += 1
                builder.add(document_id, title, body, location)
                if progress and considered % 25_000 == 0:
                    print(f"  audited {considered:,} documents...",
                          file=sys.stderr, flush=True)
            if limit is not None and considered >= limit:
                break
        if include_project_files and (limit is None or considered < limit):
            builder._input_sources.append(
                f"crms-project-files: {_display_path(project_root)}")
            for document_id, title, text, location in _iter_project_files(project_root):
                if limit is not None and considered >= limit:
                    break
                considered += 1
                builder.add(document_id, title, text, location)
    except Exception:
        for index in builder._indexes:
            try:
                index.close()
            except Exception:
                pass
        try:
            builder._catalog.close()
        except Exception:
            pass
        raise
    summary = builder.close()
    summary["considered"] = considered
    summary["input_sources"] = list(builder._input_sources)
    path = Path(output).expanduser().resolve()
    (path / "corpus.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


_GENERIC_QUERY_TERMS = frozenset({
    "about", "allowed", "article", "capital", "characterized", "city",
    "command", "describe", "description", "docstring", "file", "format",
    "implements",
    "from", "identifiers", "kind", "largest", "made", "main", "many", "model",
    "module", "name", "number", "paper", "passage", "play", "players", "point",
    "portable", "potential", "process", "python", "role", "second", "smallest",
    "source", "starts", "study", "temperature", "type", "used", "uses",
    "what", "which", "who", "when", "where",
})
_NUMBER_WORDS = frozenset({
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "dozen", "half", "quarter", "percent",
})
_CODE_SUFFIXES = (".py", ".js", ".ts", ".java", ".c", ".h", ".cpp", ".rs",
                  ".go", ".rb", ".php", ".sh", ".sql")


def _specific_query_term(terms: Sequence[str]) -> str:
    pool = [term for term in terms
            if len(term) >= 5 and term not in _GENERIC_QUERY_TERMS]
    if pool:
        return max(pool, key=len)
    return max(terms, key=len) if terms else ""


def _window_around(text: str, position: int, *, before: int = 240,
                   after: int = 420) -> tuple[int, int]:
    start = max(0, position - before)
    end = min(len(text), position + after)
    if start > 0:
        newline = text.rfind("\n", 0, start)
        start = 0 if newline < 0 else newline + 1
    newline = text.find("\n", end)
    end = len(text) if newline < 0 else newline
    if end <= start:
        end = min(len(text), start + 1)
    return start, end


# ---------------------------------------------------------------------------
# Reader


def _location_boost(hit: SearchHit, terms: Sequence[str]) -> float:
    location = (hit.location or "").casefold()
    if not location.endswith(_CODE_SUFFIXES + (".md",)):
        return 0.0
    match = re.search(r"([a-z0-9_]+)\.(?:py|md|txt)$", location)
    if match is None:
        return 0.0
    stem = match.group(1)
    boost = 0.0
    for term in terms:
        if term == stem:
            boost = max(boost, 300.0)
        elif len(term) >= 4 and term in stem:
            boost = max(boost, 120.0)
    return boost


def _is_programming_request(question: str, terms: Sequence[str]) -> bool:
    return (_is_programming_query(question)
            or bool(re.search(r"\b[\w_-]+\.(?:py|md|txt)\b", question,
                              re.IGNORECASE))
            or bool({"readme", "docstring", "module", "python"}
                    & set(terms)))


class CorpusReader:
    """Read a self-contained sharded corpus and answer with exact citations."""

    def __init__(self, root: str | Path, *, read_only: bool = True
                 ) -> None:
        self.root = Path(root).expanduser().resolve()
        model_path = self.root / "model.json"
        catalog_path = self.root / "catalog.sqlite"
        if not model_path.is_file() or not catalog_path.is_file():
            raise FileNotFoundError(f"not a CRMS Phase 7 corpus: {self.root}")
        self.model = json.loads(model_path.read_text(encoding="utf-8"))
        if self.model.get("format") != MODEL_FORMAT:
            raise ValueError("unsupported Phase 7 corpus model format")
        self._catalog = sqlite3.connect(
            catalog_path.as_uri() + "?mode=ro", uri=True)
        self._catalog.row_factory = sqlite3.Row
        self.shards = [
            CRMSSQLiteResearchIndex(self.root / name, read_only=read_only)
            for name in self.model["shards"]
        ]
        self._shard_by_document: dict[str, int] = {}

    @property
    def document_count(self) -> int:
        return int(self._catalog.execute(
            "SELECT count(*) FROM documents").fetchone()[0])

    @property
    def word_count(self) -> int:
        return int(self._catalog.execute(
            "SELECT COALESCE(sum(word_count),0) FROM documents").fetchone()[0])

    def summary(self) -> dict[str, Any]:
        path = self.root / "corpus.json"
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"documents": self.document_count, "words": self.word_count}

    def manifest(self, document_id: str) -> dict[str, Any]:
        row = self._catalog.execute(
            "SELECT * FROM documents WHERE document_id=?", (document_id,)
        ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return dict(row)

    def contains_document(self, document_id: str) -> bool:
        return self._catalog.execute(
            "SELECT 1 FROM documents WHERE document_id=?", (document_id,)
        ).fetchone() is not None

    def shard_for(self, document_id: str) -> int:
        shard = self._shard_by_document.get(document_id)
        if shard is not None:
            return shard
        row = self._catalog.execute(
            "SELECT shard FROM documents WHERE document_id=?", (document_id,)
        ).fetchone()
        if row is None:
            raise KeyError(document_id)
        shard = int(row[0])
        self._shard_by_document[document_id] = shard
        return shard

    def document(self, document_id: str) -> SourceDocument:
        return self.shards[self.shard_for(document_id)].document(document_id)

    def _location_hits(self, terms: Sequence[str]) -> list[SearchHit]:
        """Find module/file targets whose path, not body, carries the query."""
        wanted = [term for term in terms if len(term) >= 5]
        if not wanted:
            return []
        clauses = " OR ".join("lower(location) LIKE ?" for _ in wanted)
        rows = self._catalog.execute(
            f"SELECT document_id,shard FROM documents WHERE {clauses} "
            "ORDER BY document_id LIMIT 12",
            [f"%{term}%" for term in wanted]).fetchall()
        hits = []
        for document_id, shard in rows:
            document = self.document(document_id)
            text = document.text
            position = 0
            for term in sorted(wanted, key=len, reverse=True):
                match = re.search(rf"(?i)\b{re.escape(term)}\b", text)
                if match is not None:
                    position = match.start()
                    break
            start, end = _window_around(text, position, before=200, after=1200)
            snippet = text[start:end]
            matched = tuple(sorted({
                term for term in wanted
                if re.search(rf"(?i)\b{re.escape(term)}\b", snippet)}))
            hits.append(SearchHit(
                document_id, document.title, document.location, 50.0, snippet,
                start, end, matched))
        return hits

    def _exact_title_hits(self, terms: Sequence[str],
                          specific: str) -> list[SearchHit]:
        candidates = {
            " ".join(terms).casefold(),
            specific.casefold(),
        }
        candidates.discard("")
        if not candidates:
            return []
        placeholders = ",".join("?" for _ in candidates)
        rows = self._catalog.execute(
            f"SELECT document_id,shard FROM documents "
            f"WHERE lower(title) IN ({placeholders})",
            sorted(candidates)).fetchall()
        hits = []
        for document_id, _shard in rows:
            document = self.document(document_id)
            start = 0
            end = min(len(document.text), 500)
            snippet = document.text[start:end].strip()
            if not snippet:
                continue
            end = start + len(snippet)
            matched = tuple(sorted({
                term for term in terms
                if re.search(rf"(?i)\b{re.escape(term)}\b", snippet)}))
            hits.append(SearchHit(
                document_id, document.title, document.location, 500.0,
                snippet, start, end, matched))
        return hits

    def search(self, query: str, *, limit: int = 5,
               context_chars: int = 120) -> list[SearchHit]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        merged: dict[str, SearchHit] = {}
        per_shard = max(limit, 3)
        for shard in self.shards:
            for hit in shard.search(
                    query, limit=per_shard, context_chars=context_chars):
                previous = merged.get(hit.document_id)
                if previous is None or hit.score > previous.score:
                    merged[hit.document_id] = hit
        terms = _research_query_terms(query)
        programming_query = _is_programming_request(query, terms)
        for hit in self._exact_title_hits(terms, _specific_query_term(terms)):
            if (programming_query
                    and not (hit.location or "").casefold().endswith(
                        _CODE_SUFFIXES + (".md",))):
                continue
            previous = merged.get(hit.document_id)
            if previous is None or hit.score > previous.score:
                merged[hit.document_id] = hit
        if programming_query:
            for hit in self._location_hits(terms):
                previous = merged.get(hit.document_id)
                if previous is None or hit.score > previous.score:
                    merged[hit.document_id] = hit
        boosted = []
        for hit in merged.values():
            boost = _location_boost(hit, terms)
            if boost:
                hit = replace(hit, score=hit.score + boost)
            boosted.append(hit)
        return sorted(boosted,
                      key=lambda hit: (-hit.score, hit.document_id))[:limit]

    def citation(self, hit: SearchHit) -> str:
        return self.shards[self.shard_for(hit.document_id)].citation(hit)

    def resolve_citation(self, citation: str) -> str:
        document_id, separator, _ = citation.partition("#")
        if not separator:
            raise ValueError("malformed source citation")
        return self.shards[self.shard_for(document_id)].resolve_citation(citation)

    def verify_hit(self, hit: SearchHit) -> SourceDocument:
        return self.shards[self.shard_for(hit.document_id)].verify_hit(hit)

    def _candidate_answer(self, question: str, hits: Sequence[SearchHit]
                          ) -> tuple[SearchHit, str, tuple[str, ...], float] | None:
        terms = _research_query_terms(question)
        if not terms:
            return None
        specific = _specific_query_term(terms)
        programming = _is_programming_request(question, terms)
        folded = " " + question.casefold() + " "
        numeric = bool(re.search(
            r"\b(?:how many|how much|what temperature|when|what year|"
            r"what date|how old)\b", folded))
        definitional = bool(re.match(
            r"^\s*(?:what|who)\s+(?:is|are|was|were)\b", folded.strip()))
        definitional = definitional and not any(
            cue in folded for cue in (" made from ", " used for ", " about ",
                                      " difference ", " mean by "))
        from_cue = " from " in folded
        who_cue = folded.strip().startswith("who ")
        term_set = set(terms)
        candidates: list[tuple[float, float, int, SearchHit, str,
                               tuple[str, ...]]] = []

        def consider(hit: SearchHit, start: int, end: int, answer: str,
                     sentence_terms: set[str], title_terms: set[str],
                     location_terms: set[str],
                     document_terms: set[str]) -> None:
            stripped = answer.strip()
            if stripped != answer:
                left = len(answer) - len(answer.lstrip())
                start += left
                end = start + len(stripped)
                answer = stripped
            else:
                answer = stripped
            words = answer.split()
            if not 4 <= len(words) <= (1000 if programming else 300):
                return
            if re.match(
                    r"^(?:source|license|licence|metadata\s+license|"
                    r"authors?|title)\s*:", answer, re.IGNORECASE):
                return
            covered = (sentence_terms | title_terms | location_terms) & term_set
            if not covered or specific not in covered:
                return
            coverage = len(covered) / max(1, len(terms))
            minimum_coverage = 0.10 if programming else 0.5
            minimum_terms = 1 if programming else (1 if len(terms) <= 1 else 2)
            if len(covered) < minimum_terms or coverage < minimum_coverage:
                return
            verifiable = ((sentence_terms | title_terms)
                          & document_terms & term_set)
            if not verifiable and not programming:
                return
            score = 2.0 * len(covered) + coverage
            score += min(max(float(hit.score), 0.0), 80.0) * 0.02
            title_norm = " ".join(
                match.group().casefold() for match in word_matches(hit.title))
            if set(title_terms) == term_set:
                score += 60.0
            elif title_norm == specific:
                score += 40.0
            elif specific in (sentence_terms | title_terms):
                score += 5.0 + 5.0 * len(title_terms & term_set)
                if len(title_terms) <= 2:
                    score += 10.0
            score += max(0.0, 0.4 * (1.0 - start / max(1, len(answer))))
            if programming:
                location = (hit.location or "").casefold()
                if location.endswith(_CODE_SUFFIXES):
                    score += 2.0
            if definitional and re.search(r"\b(?:is|are|was|were)\b",
                                          answer, re.IGNORECASE):
                if specific in (sentence_terms | title_terms):
                    score += 2.0
                if re.search(
                        rf"\b{re.escape(specific)}\b[^.]{{0,140}}"
                        rf"\b(?:is|are|was|were)\b", answer, re.IGNORECASE):
                    score += 2.0
            if specific in sentence_terms:
                score += 1.5
            if re.match(r"^(?:It|They|He|She|This|That|These|Those)\b",
                        answer) and specific not in sentence_terms:
                score -= 1.5
            if numeric and (re.search(r"\d", answer)
                            or any(word in answer.casefold()
                                   for word in _NUMBER_WORDS)):
                score += 3.0
            if from_cue and " from " in " " + answer.casefold() + " ":
                score += 1.0
            if who_cue and re.search(r"\b[A-Z][a-z]+\b", answer[1:]):
                score += 0.5
            candidate = replace(
                hit, snippet=answer, start=start, end=end,
                matched_terms=tuple(sorted(verifiable)),
                page_number=None, match_start=None, match_end=None)
            candidates.append((score, float(hit.score), start, candidate,
                               answer, tuple(sorted(covered))))

        for hit in (hits[:1] if programming else hits[:20]):
            document = self.document(hit.document_id)
            text = document.text
            title_terms = {match.group().casefold()
                           for match in word_matches(hit.title)}
            location_terms = {match.group().casefold()
                              for match in word_matches(hit.location or "")}
            document_terms = ({match.group().casefold()
                               for match in word_matches(text)}
                              | title_terms)
            if programming:
                present = []
                for term in sorted(set([specific] + list(terms)),
                                   key=len, reverse=True):
                    if term in _GENERIC_QUERY_TERMS and len(term) < 8:
                        continue
                    match = re.search(
                        rf"(?i)\b{re.escape(term)}\b", text)
                    if match is not None:
                        present.append((len(term), match.start()))
                if "command" in terms and "chat" in terms:
                    match = re.search(r"python3\s+crms_chat\.py", text)
                    position = match.start() if match is not None else 0
                elif "docstring" in terms:
                    position = 0
                elif present:
                    _, position = max(present, key=lambda item: item[0])
                else:
                    position = 0
                start, end = _window_around(
                    text, position, before=2000, after=2500)
                answer = text[start:end]
                sentence_terms = {token.group().casefold()
                                  for token in word_matches(answer)}
                consider(hit, start, end, answer, sentence_terms,
                         title_terms, location_terms, document_terms)
            if not programming:
                if (hit.snippet.strip() and len(hit.snippet.split()) >= 4
                        and not hit.snippet.rstrip().endswith(":")):
                    sentence_terms = {token.group().casefold()
                                      for token in word_matches(hit.snippet)}
                    consider(hit, hit.start, hit.end, hit.snippet,
                             sentence_terms, title_terms, location_terms,
                             document_terms)
                for start, end in _sentence_spans(text):
                    if not 5 <= len(text[start:end].split()) <= 120:
                        continue
                    answer = text[start:end]
                    if answer.rstrip().endswith(":"):
                        end = min(len(text), end + 400)
                        while end < len(text) and text[end - 1] not in "\n":
                            end += 1
                        answer = text[start:end]
                    sentence_terms = {token.group().casefold()
                                      for token in word_matches(answer)}
                    consider(hit, start, end, answer, sentence_terms,
                             title_terms, location_terms, document_terms)
        if not candidates:
            return None
        best = max(candidates, key=lambda item: (item[0], item[1], -item[2]))
        hit, answer, covered = best[3], best[4], best[5]
        coverage = len(covered) / max(1, len(terms))
        return hit, answer, covered, coverage

    def answer_question(self, question: str, *, limit: int = 5
                        ) -> dict[str, Any]:
        """Return a grounded extractive answer or an explicit abstention."""
        started = time.perf_counter()
        hits = self.search(question, limit=max(limit, 30))
        result: dict[str, Any] = {
            "question": question,
            "status": "abstained",
            "answer": "",
            "citation": "",
            "document_id": "",
            "title": "",
            "score": 0.0,
            "matched_terms": [],
            "coverage": 0.0,
            "latency_ms": 0.0,
        }
        if not hits:
            result["latency_ms"] = (time.perf_counter() - started) * 1000
            return result
        selected = self._candidate_answer(question, hits)
        if selected is None:
            best = hits[0]
            result.update({
                "document_id": best.document_id, "title": best.title,
                "score": best.score, "matched_terms": sorted(best.matched_terms),
                "coverage": len(set(best.matched_terms) & set(
                    _research_query_terms(question))) / max(
                        1, len(_research_query_terms(question))),
                "latency_ms": (time.perf_counter() - started) * 1000,
            })
            return result
        hit, answer, matched, coverage = selected
        try:
            citation = self.citation(hit)
            self.resolve_citation(citation)
        except Exception:
            result["latency_ms"] = (time.perf_counter() - started) * 1000
            return result
        result.update({
            "status": "answered",
            "answer": answer,
            "citation": citation,
            "document_id": hit.document_id,
            "title": hit.title,
            "score": hit.score,
            "matched_terms": list(matched),
            "coverage": coverage,
            "latency_ms": (time.perf_counter() - started) * 1000,
        })
        return result

    def close(self) -> None:
        for shard in self.shards:
            shard.close()
        self._catalog.close()


# ---------------------------------------------------------------------------
# CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build an audited sharded corpus")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--shards", type=int, default=DEFAULT_SHARDS)
    build.add_argument("--holdout", type=Path, default=None,
                       help="diagnostic JSON fixture whose evaluation_documents "
                       "are excluded from ingestion")
    build.add_argument("--limit", type=int, default=None)
    build.add_argument("--no-near-dedup", action="store_true")
    build.add_argument("--no-project-files", action="store_true")
    build.add_argument("--replace", action="store_true")

    inspect = sub.add_parser("inspect", help="print corpus and licence totals")
    inspect.add_argument("--corpus", type=Path, required=True)

    search = sub.add_parser("search", help="search the sharded corpus")
    search.add_argument("--corpus", type=Path, required=True)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)

    answer = sub.add_parser("answer", help="answer with an exact citation")
    answer.add_argument("--corpus", type=Path, required=True)
    answer.add_argument("question")

    args = parser.parse_args(argv)
    if args.command == "build":
        holdout: tuple[str, ...] = ()
        if args.holdout is not None:
            payload = json.loads(args.holdout.read_text(encoding="utf-8"))
            documents = payload.get(
                "evaluation_documents", payload.get("heldout_documents", ()))
            holdout = tuple(item["document_id"] for item in documents)
        summary = build_core_corpus(
            args.out, shards=args.shards, holdout_ids=holdout,
            near_dedup=not args.no_near_dedup,
            include_project_files=not args.no_project_files,
            replace=args.replace, limit=args.limit, progress=True)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    reader = CorpusReader(args.corpus)
    try:
        if args.command == "inspect":
            summary = reader.summary()
            manifest = reader.manifest
            print(json.dumps({
                "corpus": str(reader.root),
                "format": summary.get("format"),
                "documents": reader.document_count,
                "words": reader.word_count,
                "shards": len(reader.shards),
                "licence_coverage": summary.get("licence_coverage"),
                "by_licence_class": summary.get("by_licence_class"),
                "rejected_reasons": summary.get("rejected_reasons"),
                "throughput": summary.get("throughput"),
            }, indent=2, sort_keys=True))
            return 0
        if args.command == "search":
            hits = reader.search(args.query, limit=args.limit)
            for hit in hits:
                print(f"{hit.document_id}\t{hit.title}\t"
                      f"{reader.citation(hit)}")
                print(f"  {hit.snippet}")
            return 0 if hits else 1
        result = reader.answer_question(args.question)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "answered" else 1
    finally:
        reader.close()


if __name__ == "__main__":
    raise SystemExit(main())
