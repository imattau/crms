"""Document-derived candidate learning with an explicit review gate.

Phase 3 is deliberately a proposal pipeline, not a source-to-runtime shortcut:

* a licence-audited document manifest is validated before text is read;
* clause-aware extraction preserves roles, conditions, negation, contrast,
  uncertainty, pronoun antecedents, and table cells;
* every eligible claim is stored in the governed rule registry as ``proposed``
  and in a review queue with its citation;
* only an explicit review decision can validate and activate a rule;
* metrics are computed from the frozen evaluation corpus and the review ledger.

The extractor is bounded. It wraps the existing surface-relation and
``will``-clause extractors rather than claiming to be a general parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

from crms_intent_rules import classify as classify_intent
from crms_knowledge import CRMSKnowledgeBase
from crms_procedure_discovery import propose_procedure_phrase_candidates
from crms_research import _sentence_spans
from crms_rule_registry import RuleRegistry

FORMAT = "crms-document-learning"
CORPUS_FORMAT = "crms-phase3-eval-corpus"
VERSION = 1
EXTRACTOR_VERSION = 1
CLAIM_FAMILIES = frozenset({"fact-frame", "procedure"})
REVIEW_DECISIONS = frozenset({"accept", "reject", "abstain"})
LICENCE_CLASSES = frozenset({"public-domain", "permissive", "share-alike"})
MAX_CLAIMS_PER_DOCUMENT = 200
MAX_FIELD_CHARS = 240

_CONDITION_RE = re.compile(
    r"^\s*(?P<condition>(?:if|when|unless|provided\s+that|"
    r"as\s+long\s+as|assuming|given\s+that)\b[^,]{1,220}),\s*"
    r"(?P<claim>.+?)\s*[.!?]?\s*$", re.IGNORECASE | re.DOTALL)
_PRONOUN_RE = re.compile(
    r"^\s*(?P<pronoun>it|they|he|she|this|these|those)\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s+|\*\*[^*]+\*\*\s*$)")
_TABLE_SPLIT_RE = re.compile(r"\s*\|\s*")
_QUOTE_CHARS = frozenset("\"'“”‘’")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z’'-]*|\d+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.casefold()).strip("-")
    return cleaned or "claim"


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def _citation(document_id: str, text: str, start: int, end: int) -> str:
    return (f"{document_id}#sha256={_sha256(text)}"
            f"&chars={start}:{end}")


def _trim(value: str, limit: int = MAX_FIELD_CHARS) -> str:
    value = " ".join(value.split())
    return value[:limit]


@dataclass(frozen=True)
class DocumentManifest:
    id: str
    publisher: str
    genre: str
    title: str
    path: str
    url: str
    licence: str
    licence_class: str
    attribution: str
    retrieved: str
    sha256: str | None = None
    text: str = ""

    def validate(self, *, root: Path) -> "DocumentManifest":
        for name in ("id", "publisher", "genre", "title", "path", "url",
                     "licence", "licence_class", "attribution", "retrieved"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"document {self.id!r} has no {name}")
        if self.licence_class not in LICENCE_CLASSES:
            raise ValueError(
                f"document {self.id!r} has unsupported licence class "
                f"{self.licence_class!r}")
        if self.genre not in {"technical-reference", "prose"}:
            raise ValueError(f"document {self.id!r} has unknown genre {self.genre!r}")
        path = (root / self.path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as error:
            raise ValueError(f"document {self.id!r} escapes the corpus root") from error
        text = path.read_text(encoding="utf-8")
        actual = _sha256(text)
        if self.sha256 is not None and self.sha256 != actual:
            raise ValueError(
                f"document {self.id!r} hash mismatch: {actual} != {self.sha256}")
        return DocumentManifest(**{**self.__dict__, "text": text, "sha256": actual})


@dataclass(frozen=True)
class DocumentClaim:
    candidate_id: str
    source_id: str
    publisher: str
    genre: str
    title: str
    family: str
    statement: str
    subject: str
    relation: str
    object: str
    predicate: str
    polarity: bool
    status: str
    conditions: tuple[str, ...]
    roles: tuple[tuple[str, str], ...]
    sentence: str
    citation: str
    context_citation: str | None = None
    antecedent: str | None = None
    proposal_eligible: bool = True
    taxonomy: str = ""

    @property
    def canonical_key(self) -> tuple[str, ...]:
        return (
            self.source_id, self.family, _normal(self.subject),
            _normal(self.relation), _normal(self.object),
            "positive" if self.polarity else "negative", self.status,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_id": self.source_id,
            "publisher": self.publisher,
            "genre": self.genre,
            "title": self.title,
            "family": self.family,
            "statement": self.statement,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "predicate": self.predicate,
            "polarity": self.polarity,
            "status": self.status,
            "conditions": list(self.conditions),
            "roles": dict(self.roles),
            "sentence": self.sentence,
            "citation": self.citation,
            "context_citation": self.context_citation,
            "antecedent": self.antecedent,
            "proposal_eligible": self.proposal_eligible,
            "taxonomy": self.taxonomy,
        }


@dataclass(frozen=True)
class Corpus:
    root: Path
    manifest_path: Path
    publishers: dict[str, dict[str, Any]]
    documents: tuple[DocumentManifest, ...]
    labels: tuple[dict[str, Any], ...]
    controls: tuple[dict[str, Any], ...]
    reviewer: str
    review_seconds: float

    def document(self, document_id: str) -> DocumentManifest:
        for document in self.documents:
            if document.id == document_id:
                return document
        raise KeyError(document_id)


def load_corpus(manifest_path: str | Path) -> Corpus:
    path = Path(manifest_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != CORPUS_FORMAT:
        raise ValueError("not a Phase 3 evaluation corpus")
    if int(data.get("version", 0)) > VERSION:
        raise ValueError("corpus version is newer than this harness")
    publishers = data.get("publishers")
    if not isinstance(publishers, dict) or len(publishers) < 3:
        raise ValueError("Phase 3 corpus needs at least three publishers")
    genres = set()
    documents = []
    root = path.parent
    for row in data.get("documents", ()):
        if not isinstance(row, Mapping):
            raise ValueError("document manifest rows must be objects")
        document = DocumentManifest(
            id=str(row.get("id", "")),
            publisher=str(row.get("publisher", "")),
            genre=str(row.get("genre", "")),
            title=str(row.get("title", "")),
            path=str(row.get("path", "")),
            url=str(row.get("url", "")),
            licence=str(row.get("licence", "")),
            licence_class=str(row.get("licence_class", "")),
            attribution=str(row.get("attribution", "")),
            retrieved=str(row.get("retrieved", "")),
            sha256=row.get("sha256"),
        ).validate(root=root)
        if document.publisher not in publishers:
            raise ValueError(
                f"document {document.id!r} has unknown publisher "
                f"{document.publisher!r}")
        expected = publishers[document.publisher]
        if expected.get("licence") != document.licence:
            raise ValueError(
                f"document {document.id!r} licence disagrees with publisher")
        genres.add(document.genre)
        documents.append(document)
    if len(documents) < 3:
        raise ValueError("Phase 3 corpus needs at least three documents")
    if len(genres) < 2:
        raise ValueError("Phase 3 corpus needs both technical and prose genres")
    labels = tuple(dict(row) for row in data.get("labels", ()) if isinstance(row, Mapping))
    controls = tuple(dict(row) for row in data.get("controls", ()) if isinstance(row, Mapping))
    review = data.get("review") or {}
    return Corpus(
        root=root,
        manifest_path=path,
        publishers=dict(publishers),
        documents=tuple(documents),
        labels=labels,
        controls=controls,
        reviewer=str(review.get("reviewer", "phase3-reviewer")),
        review_seconds=float(review.get("seconds_per_claim", 24.0)),
    )


def _split_condition(sentence: str) -> tuple[str, str, str | None]:
    match = _CONDITION_RE.match(sentence)
    if match is None:
        return "", sentence, None
    condition = _trim(match.group("condition"))
    core = match.group("claim").strip()
    trailing = sentence[match.end():] if match.end() < len(sentence) else ""
    core = (core + " " + trailing).strip()
    return condition, core, condition


_CLAIM_STATUS_REASONS = {"denied": "denial", "attributed": "attribution",
                         "uncertain": "uncertainty", "negated": "negation"}


def _status_for(sentence: str, *, polarity: bool, quoted: bool) -> tuple[str, str]:
    if quoted and any(ch in _QUOTE_CHARS for ch in sentence):
        return "quoted", "quotation"
    # cue families (denial, attribution, hedge, negation) are SQL pattern rules
    status = classify_intent("claim_status", sentence.replace("’", "'"),
                             normalise=False)
    if status is None and not polarity:
        status = "negated"
    if status is not None:
        return status, _CLAIM_STATUS_REASONS[status]
    return "asserted", ""


def _fact_claims_for_sentence(
        knowledge: CRMSKnowledgeBase, sentence: str, *, citation: str,
        core_sentence: str | None = None) -> list[dict[str, Any]]:
    analysis = core_sentence or sentence
    candidates = knowledge._discover_surface_relation_candidates(
        analysis, source=citation)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.polarity:
            status, taxonomy = _status_for(sentence, polarity=False,
                                           quoted=False)
        else:
            status, taxonomy = _status_for(sentence, polarity=True,
                                           quoted=False)
        rows.append({
            "family": "fact-frame",
            "subject": _trim(candidate.subject),
            "relation": _trim(candidate.relation),
            "object": _trim(candidate.object),
            "predicate": _trim(candidate.relation),
            "polarity": bool(candidate.polarity),
            "status": status,
            "taxonomy": taxonomy,
            "roles": {
                "subject": _trim(candidate.subject),
                "relation": _trim(candidate.relation),
                "object": _trim(candidate.object),
            },
        })
    return rows


def _procedure_claims_for_sentence(
        sentence: str, *, citation: str,
        core_sentence: str | None = None) -> list[dict[str, Any]]:
    candidates = propose_procedure_phrase_candidates(
        core_sentence or sentence, source_citation=citation)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate.polarity:
            status, taxonomy = _status_for(sentence, polarity=False,
                                           quoted=candidate.quoted)
        else:
            status, taxonomy = _status_for(
                sentence, polarity=True, quoted=candidate.quoted)
        if candidate.assertion_status in {"denied", "uncertain"}:
            status = candidate.assertion_status
            taxonomy = "denial" if status == "denied" else "uncertainty"
        predicate = _trim(candidate.predicate_phrase)
        head = predicate.split()[0] if predicate else ""
        conditions = tuple(candidate.scope_notes)
        rows.append({
            "family": "procedure",
            "subject": _trim(candidate.subject),
            "relation": head,
            "object": predicate,
            "predicate": predicate,
            "polarity": bool(candidate.polarity),
            "status": status,
            "taxonomy": taxonomy,
            "roles": {
                "subject": _trim(candidate.subject),
                "predicate": predicate,
            },
            "conditions": conditions,
        })
    return rows


def _table_claims(document: DocumentManifest, text: str) -> list[dict[str, Any]]:
    lines = text.splitlines(keepends=True)
    offset = 0
    header: list[str] | None = None
    header_offset = 0
    rows: list[dict[str, Any]] = []

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z]+", "", value.casefold())

    for line in lines:
        stripped = line.strip()
        cells = [cell.strip() for cell in _TABLE_SPLIT_RE.split(stripped.strip("|"))]
        if stripped.startswith("|") and stripped.endswith("|") and len(cells) >= 2:
            normalized_cells = [normalized(cell) for cell in cells]
            if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", ""))
                   for cell in cells):
                pass
            elif ({"subject", "entity", "name"} & set(normalized_cells)
                  and {"relation", "predicate", "property"} & set(normalized_cells)
                  and {"object", "value", "target"} & set(normalized_cells)):
                header = normalized_cells
                header_offset = offset
            elif header is not None:
                by_name = dict(zip(header, cells))
                subject = by_name.get("subject") or by_name.get("entity") or by_name.get("name")
                relation = (by_name.get("relation") or by_name.get("predicate")
                            or by_name.get("property"))
                obj = by_name.get("object") or by_name.get("value") or by_name.get("target")
                if subject and relation and obj:
                    start = offset
                    end = offset + len(line.rstrip("\n"))
                    citation = _citation(document.id, text, start, end)
                    rows.append({
                        "family": "fact-frame",
                        "subject": _trim(subject),
                        "relation": _trim(relation),
                        "object": _trim(obj),
                        "predicate": _trim(relation),
                        "polarity": True,
                        "status": "asserted",
                        "taxonomy": "",
                        "roles": {
                            "subject": _trim(subject),
                            "relation": _trim(relation),
                            "object": _trim(obj),
                            "table_row": "true",
                        },
                        "sentence": stripped,
                        "citation": citation,
                    })
        else:
            header = None
        offset += len(line)
    return rows


def _make_claim(document: DocumentManifest, row: Mapping[str, Any], *,
                sentence: str, citation: str,
                context_citation: str | None = None,
                antecedent: str | None = None,
                conditions: Iterable[str] = ()) -> DocumentClaim | None:
    family = str(row.get("family", ""))
    if family not in CLAIM_FAMILIES:
        return None
    subject = str(row.get("subject", "")).strip()
    relation = str(row.get("relation", "")).strip()
    obj = str(row.get("object", "")).strip()
    predicate = str(row.get("predicate", relation)).strip()
    if not subject or not relation or not obj:
        return None
    status = str(row.get("status", "asserted"))
    polarity = bool(row.get("polarity", True))
    eligible = status == "asserted" and polarity
    if family == "fact-frame":
        statement = f"{subject} {relation} {obj}"
    else:
        statement = f"{subject} will {obj}"
    key = "|".join((
        document.id, family, _normal(subject), _normal(relation),
        _normal(obj), "positive" if polarity else "negative", status,
        citation,
    ))
    candidate_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return DocumentClaim(
        candidate_id=candidate_id,
        source_id=document.id,
        publisher=document.publisher,
        genre=document.genre,
        title=document.title,
        family=family,
        statement=statement,
        subject=subject,
        relation=relation,
        object=obj,
        predicate=predicate,
        polarity=polarity,
        status=status,
        conditions=tuple(dict.fromkeys(
            str(value) for value in conditions if str(value).strip())),
        roles=tuple(sorted(dict(row.get("roles") or {}).items())),
        sentence=_trim(sentence, 1000),
        citation=citation,
        context_citation=context_citation,
        antecedent=antecedent,
        proposal_eligible=eligible,
        taxonomy=str(row.get("taxonomy", "")),
    )


def extract_document_claims(
        document: DocumentManifest, knowledge: CRMSKnowledgeBase | None = None,
        *, allowed_relations: set[str] | None = None,
        allowed_predicate_heads: set[str] | None = None,
        ) -> tuple[DocumentClaim, ...]:
    """Extract review-only claims from one audited document."""
    knowledge = knowledge or CRMSKnowledgeBase()
    text = document.text
    claims: dict[tuple[str, ...], DocumentClaim] = {}
    for row in _table_claims(document, text):
        claim = _make_claim(
            document, row, sentence=str(row["sentence"]),
            citation=str(row["citation"]))
        if claim is not None:
            claims[claim.canonical_key] = claim

    last_subject: str | None = None
    last_subject_citation: str | None = None
    last_subject_count = 0
    for start, end in _sentence_spans(text):
        sentence = text[start:end].strip()
        if (not sentence or len(sentence) > 2000 or sentence.startswith("#")
                or "|" in sentence or _HEADING_RE.match(sentence)):
            continue
        if not re.search(r"[.!?]$", sentence) and _word_count(sentence) <= 8:
            continue
        citation = _citation(document.id, text, start, end)
        condition, core, _ = _split_condition(sentence)
        rows = _fact_claims_for_sentence(
            knowledge, sentence, citation=citation, core_sentence=core)
        rows.extend(_procedure_claims_for_sentence(
            sentence, citation=citation, core_sentence=core))
        local_subjects = {
            _normal(str(row.get("subject", ""))) for row in rows
            if str(row.get("subject", "")).strip()
        }
        resolved = False
        pronoun_match = _PRONOUN_RE.match(sentence)
        pronoun_subjects = {
            "it", "they", "he", "she", "this", "these", "those"}
        if (pronoun_match and last_subject and last_subject_count == 1
                and (not rows or local_subjects <= pronoun_subjects)):
            resolved = True
            rewritten = re.sub(
                _PRONOUN_RE, last_subject, sentence, count=1)
            condition, core, _ = _split_condition(rewritten)
            rewritten_rows = _fact_claims_for_sentence(
                knowledge, sentence, citation=citation, core_sentence=core)
            rewritten_rows.extend(_procedure_claims_for_sentence(
                sentence, citation=citation, core_sentence=core))
            if rewritten_rows:
                rows = rewritten_rows
            for row in rows:
                row["roles"] = {
                    **dict(row.get("roles") or {}),
                    "resolved_pronoun": pronoun_match.group("pronoun"),
                    "antecedent": last_subject,
                }
        for row in rows:
            conditions = list(row.get("conditions") or ())
            if condition:
                conditions.insert(0, "before: " + condition)
            claim = _make_claim(
                document, row, sentence=sentence, citation=citation,
                context_citation=(last_subject_citation if resolved else None),
                antecedent=(last_subject if resolved else None),
                conditions=conditions)
            if claim is None:
                continue
            if allowed_relations is not None and claim.family == "fact-frame":
                if _normal(claim.relation) not in {
                        _normal(value) for value in allowed_relations}:
                    continue
            if (allowed_predicate_heads is not None
                    and claim.family == "procedure"):
                if _normal(claim.relation) not in {
                        _normal(value) for value in allowed_predicate_heads}:
                    continue
            claims.setdefault(claim.canonical_key, claim)
            if len(claims) >= MAX_CLAIMS_PER_DOCUMENT:
                break
        if rows:
            subjects = {
                str(row.get("subject", "")).strip()
                for row in rows if str(row.get("subject", "")).strip()
            }
            if len(subjects) == 1:
                last_subject = next(iter(subjects))
                last_subject_citation = citation
                last_subject_count = 1
            elif len(subjects) > 1:
                last_subject = None
                last_subject_citation = None
                last_subject_count = len(subjects)
        if len(claims) >= MAX_CLAIMS_PER_DOCUMENT:
            break
    return tuple(sorted(claims.values(), key=lambda claim: claim.canonical_key))


def extract_corpus_claims(
        corpus: Corpus, knowledge: CRMSKnowledgeBase | None = None,
        *, allowed_relations: set[str] | None = None,
        allowed_predicate_heads: set[str] | None = None,
        ) -> tuple[DocumentClaim, ...]:
    rows: list[DocumentClaim] = []
    for document in corpus.documents:
        rows.extend(extract_document_claims(
            document, knowledge, allowed_relations=allowed_relations,
            allowed_predicate_heads=allowed_predicate_heads))
    return tuple(rows)


def propose_claims_to_registry(
        claims: Iterable[DocumentClaim], registry: RuleRegistry
        ) -> list[str]:
    """Insert every eligible claim as a proposed, inert registry rule."""
    ids: list[str] = []
    for claim in claims:
        if not claim.proposal_eligible:
            continue
        rule_id = "phase3-" + claim.candidate_id
        if rule_id in registry:
            ids.append(rule_id)
            continue
        record = registry.propose(
            rule_id=rule_id,
            family=claim.family,
            statement=claim.statement,
            scope=claim.relation,
            payload=claim.as_payload(),
            provenance=({
                "citation": claim.citation,
                "document_id": claim.source_id,
                "publisher": claim.publisher,
                "title": claim.title,
                "licence": "see audited corpus manifest",
                "extractor": f"{FORMAT}/v{EXTRACTOR_VERSION}",
                "review_required": True,
            },),
            trust="source-reviewed",
        )
        # The state is explicit even though propose already defaults to it.
        record.state = "proposed"
        ids.append(rule_id)
    return ids


class ReviewQueue:
    """SQLite review ledger with citation, roles, and time-per-claim."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.row_factory = sqlite3.Row
        with self._connection:
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS candidates ("
                "candidate_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
                "publisher TEXT NOT NULL, family TEXT NOT NULL, "
                "status TEXT NOT NULL, payload TEXT NOT NULL, "
                "decision TEXT, reviewer TEXT, reviewed_at TEXT, "
                "review_seconds REAL, taxonomy TEXT, note TEXT)")

    def close(self) -> None:
        self._connection.close()

    def add(self, claims: Iterable[DocumentClaim]) -> int:
        added = 0
        with self._connection:
            for claim in claims:
                if not claim.proposal_eligible:
                    continue
                cursor = self._connection.execute(
                    "INSERT OR IGNORE INTO candidates("
                    "candidate_id, source_id, publisher, family, status, payload) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (claim.candidate_id, claim.source_id, claim.publisher,
                     claim.family, claim.status,
                     json.dumps(claim.as_payload(), sort_keys=True)))
                added += cursor.rowcount
        return added

    def pending(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM candidates WHERE decision IS NULL "
            "ORDER BY publisher, source_id, candidate_id").fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def review(self, candidate_id: str, *, decision: str, reviewer: str,
               seconds: float, taxonomy: str = "", note: str = ""
               ) -> dict[str, Any]:
        if decision not in REVIEW_DECISIONS:
            raise ValueError(f"unknown review decision: {decision!r}")
        if not reviewer.strip():
            raise ValueError("review requires a reviewer identity")
        if not 0 <= seconds <= 7200:
            raise ValueError("review duration must be between 0 and 7200 seconds")
        row = self._connection.execute(
            "SELECT candidate_id FROM candidates WHERE candidate_id = ?",
            (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        with self._connection:
            self._connection.execute(
                "UPDATE candidates SET decision = ?, reviewer = ?, "
                "reviewed_at = ?, review_seconds = ?, taxonomy = ?, note = ? "
                "WHERE candidate_id = ?",
                (decision, reviewer, _now(), float(seconds), taxonomy, note,
                 candidate_id))
        return self.claim(candidate_id)

    def claim(self, candidate_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT * FROM candidates WHERE candidate_id = ?",
            (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        data = dict(row)
        data["payload"] = json.loads(data["payload"])
        return data

    def reviewed(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM candidates WHERE decision IS NOT NULL "
            "ORDER BY publisher, source_id, candidate_id").fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def accepted(self) -> list[dict[str, Any]]:
        return [row for row in self.reviewed() if row["decision"] == "accept"]

    def metrics(self) -> dict[str, Any]:
        rows = self.reviewed()
        accepted = [row for row in rows if row["decision"] == "accept"]
        rejected = [row for row in rows if row["decision"] == "reject"]
        times = [float(row["review_seconds"]) for row in rows
                 if row["review_seconds"] is not None]
        taxonomies: dict[str, int] = {}
        for row in rejected:
            taxonomy = str(row.get("taxonomy") or "unspecified")
            taxonomies[taxonomy] = taxonomies.get(taxonomy, 0) + 1
        reviewed = len(accepted) + len(rejected)
        return {
            "total": len(rows) + len(self.pending()),
            "reviewed": reviewed,
            "accepted": len(accepted),
            "rejected": len(rejected),
            "abstained": len(rows) - reviewed,
            "precision": (len(accepted) / reviewed) if reviewed else 0.0,
            "median_review_seconds": (
                sorted(times)[len(times) // 2] if times else 0.0),
            "mean_review_seconds": (sum(times) / len(times)) if times else 0.0,
            "review_minutes_per_claim": (
                (sum(times) / len(times)) / 60.0 if times else 0.0),
            "false_positive_taxonomy": dict(sorted(taxonomies.items())),
        }


def review_with_frozen_oracle(
        queue: ReviewQueue, corpus: Corpus,
        *, default_seconds: float | None = None) -> dict[str, Any]:
    """Apply the corpus' frozen adjudication to pending candidates.

    This is a benchmark reviewer, not a human-factors claim. The seconds are
    recorded from the frozen ledger and feed the review-time gate.
    """
    labels = {}
    for label in corpus.labels:
        key = (
            str(label.get("document_id", "")),
            str(label.get("family", "")),
            _normal(str(label.get("subject", ""))),
            _normal(str(label.get("relation", ""))),
            _normal(str(label.get("object", ""))),
        )
        labels[key] = label
    applied = 0
    for row in queue.pending():
        payload = row["payload"]
        key = (
            payload["source_id"], payload["family"],
            _normal(payload["subject"]), _normal(payload["relation"]),
            _normal(payload["object"]),
        )
        label = labels.get(key)
        if label is None:
            decision = "reject"
            taxonomy = "unlabeled"
            seconds = float(default_seconds or corpus.review_seconds)
            note = "frozen reviewer: no matching seed label"
        else:
            decision = str(label.get("decision", "reject"))
            taxonomy = str(label.get("taxonomy", ""))
            seconds = float(label.get("review_seconds",
                                     default_seconds or corpus.review_seconds))
            note = str(label.get("note", "frozen adjudication"))
            expected_conditions = label.get("conditions")
            if expected_conditions is not None:
                observed = tuple(_normal(str(value)) for value in
                                 payload.get("conditions", ()))
                expected = tuple(_normal(str(value)) for value in
                                 expected_conditions)
                if observed != expected:
                    decision = "reject"
                    taxonomy = "condition_scope"
                    note = "frozen reviewer: condition scope changed"
            expected_antecedent = label.get("antecedent")
            if expected_antecedent is not None:
                observed = _normal(str(payload.get("antecedent") or ""))
                if observed != _normal(str(expected_antecedent)):
                    decision = "reject"
                    taxonomy = "antecedent"
                    note = "frozen reviewer: pronoun antecedent changed"
            expected_roles = label.get("roles")
            if isinstance(expected_roles, Mapping):
                observed_roles = payload.get("roles") or {}
                for name, value in expected_roles.items():
                    if str(observed_roles.get(name, "")) != str(value):
                        decision = "reject"
                        taxonomy = "role_preservation"
                        note = "frozen reviewer: role boundary changed"
                        break
        queue.review(
            row["candidate_id"], decision=decision, reviewer=corpus.reviewer,
            seconds=seconds, taxonomy=taxonomy, note=note)
        applied += 1
    return {"reviewed": applied}


def promote_accepted(
        queue: ReviewQueue, registry: RuleRegistry,
        *, authoriser: str | None = None) -> dict[str, Any]:
    """Validate and activate accepted claims; retire rejected proposals."""
    accepted = 0
    rejected = 0
    for row in queue.reviewed():
        rule_id = "phase3-" + row["candidate_id"]
        if row["decision"] == "accept":
            if rule_id not in registry:
                payload = row["payload"]
                claim = DocumentClaim(**{
                    key: payload[key] for key in (
                        "candidate_id", "source_id", "publisher", "genre",
                        "title", "family", "statement", "subject", "relation",
                        "object", "predicate", "polarity", "status",
                        "conditions", "roles", "sentence", "citation",
                        "context_citation", "antecedent", "proposal_eligible",
                        "taxonomy")
                })
                propose_claims_to_registry((claim,), registry)
            record = registry.get(rule_id)
            if record.state == "proposed":
                registry.validate(
                    rule_id, oracle="frozen-phase3-adjudication", passed=True,
                    cases=1, independent_sources=1,
                    detail="citation-backed review accepted this claim")
            if record.state == "validated":
                registry.activate(
                    rule_id, mode="review",
                    authoriser=authoriser or "phase3-reviewer")
            accepted += 1
        elif row["decision"] == "reject" and rule_id in registry:
            record = registry.get(rule_id)
            if record.state != "retired":
                registry.retire(
                    rule_id, reason="review rejected: "
                    + str(row.get("taxonomy") or "unspecified"))
            rejected += 1
    active = [record for record in registry.records(state="active")
              if record.id.startswith("phase3-")]
    return {
        "accepted": accepted,
        "rejected": rejected,
        "active_phase3_rules": len(active),
    }


def _label_keys(corpus: Corpus) -> set[tuple[str, ...]]:
    keys = set()
    for label in corpus.labels:
        keys.add((
            str(label.get("document_id", "")),
            str(label.get("family", "")),
            _normal(str(label.get("subject", ""))),
            _normal(str(label.get("relation", ""))),
            _normal(str(label.get("object", ""))),
        ))
    return keys


def seeded_recall(corpus: Corpus, queue: ReviewQueue) -> dict[str, Any]:
    accepted = {
        (
            row["payload"]["source_id"], row["payload"]["family"],
            _normal(row["payload"]["subject"]),
            _normal(row["payload"]["relation"]),
            _normal(row["payload"]["object"]),
        )
        for row in queue.accepted()
    }
    labels = [label for label in corpus.labels
              if str(label.get("decision", "")) == "accept"]
    found = 0
    for label in labels:
        key = (
            str(label.get("document_id", "")),
            str(label.get("family", "")),
            _normal(str(label.get("subject", ""))),
            _normal(str(label.get("relation", ""))),
            _normal(str(label.get("object", ""))),
        )
        if key in accepted:
            found += 1
    return {
        "seeded": len(labels),
        "found": found,
        "recall": (found / len(labels)) if labels else 0.0,
    }


def control_metrics(corpus: Corpus,
                    claims: Iterable[DocumentClaim]) -> dict[str, Any]:
    rows = list(claims)
    controls = []
    for control in corpus.controls:
        sentence = _normal(str(control.get("sentence", "")))
        source = str(control.get("document_id", ""))
        matches = [
            claim for claim in rows
            if claim.source_id == source
            and sentence and sentence in _normal(claim.sentence)
            and claim.proposal_eligible
        ]
        controls.append({
            "id": control.get("id"),
            "expected": control.get("expected", "no_proposal"),
            "passed": not matches,
            "matches": [claim.candidate_id for claim in matches],
            "taxonomy": control.get("taxonomy", ""),
        })
    return {
        "total": len(controls),
        "passed": sum(1 for row in controls if row["passed"]),
        "controls": controls,
    }


def active_rule_relations(registry: RuleRegistry,
                          *, publisher: str | None = None
                          ) -> tuple[set[str], set[str]]:
    relations: set[str] = set()
    heads: set[str] = set()
    for record in registry.records(state="active"):
        if not record.id.startswith("phase3-"):
            continue
        if publisher is not None and record.payload.get("publisher") != publisher:
            continue
        if record.family == "fact-frame":
            relations.add(_normal(str(record.payload.get("relation", ""))))
        elif record.family == "procedure":
            heads.add(_normal(str(record.payload.get("relation", ""))))
    return relations, heads


def transfer_metrics(
        corpus: Corpus, registry: RuleRegistry,
        knowledge: CRMSKnowledgeBase | None = None,
        *, learning_publisher: str) -> dict[str, Any]:
    relations, heads = active_rule_relations(
        registry, publisher=learning_publisher)
    knowledge = knowledge or CRMSKnowledgeBase()
    claims: list[DocumentClaim] = []
    for document in corpus.documents:
        if document.publisher == learning_publisher:
            continue
        claims.extend(extract_document_claims(
            document, knowledge, allowed_relations=relations,
            allowed_predicate_heads=heads))
    keys = {
        (
            claim.source_id, claim.family, _normal(claim.subject),
            _normal(claim.relation), _normal(claim.object),
        )
        for claim in claims if claim.proposal_eligible
    }
    labels = []
    for label in corpus.labels:
        if str(label.get("decision", "")) != "accept":
            continue
        document_id = str(label.get("document_id", ""))
        if not document_id:
            continue
        if corpus.document(document_id).publisher == learning_publisher:
            continue
        family = str(label.get("family", ""))
        relation = _normal(str(label.get("relation", "")))
        if family == "fact-frame" and relation not in relations:
            continue
        if family == "procedure" and relation not in heads:
            continue
        labels.append(label)
    matched = []
    for label in labels:
        key = (
            str(label["document_id"]), str(label["family"]),
            _normal(str(label["subject"])), _normal(str(label["relation"])),
            _normal(str(label["object"])),
        )
        if key in keys:
            matched.append(key)
    return {
        "learning_publisher": learning_publisher,
        "active_relations": sorted(relations),
        "active_predicate_heads": sorted(heads),
        "heldout_labels": len(labels),
        "matched": len(matched),
        "coverage": (len(matched) / len(labels)) if labels else 0.0,
    }


def retention_after_distractors(
        corpus: Corpus, registry: RuleRegistry,
        index: Any, *, distractors: int = 100) -> dict[str, Any]:
    """Check that active rules and their citations survive corpus growth."""
    before = [record.id for record in registry.records(state="active")
              if record.id.startswith("phase3-")]
    for number in range(distractors):
        document_id = f"distractor-{number:03d}"
        text = (f"Distractor note {number} records ordinary operational "
                "metadata and does not change the reviewed rules.")
        index.add_document(document_id, f"Distractor {number}", text,
                           f"https://example.invalid/distractor/{number}")
    surviving = [record.id for record in registry.records(state="active")
                 if record.id.startswith("phase3-")]
    citations_ok = 0
    for record_id in surviving:
        citation = registry.get(record_id).payload.get("citation")
        try:
            index.resolve_citation(str(citation))
            citations_ok += 1
        except (KeyError, ValueError):
            pass
    return {
        "distractors": distractors,
        "active_before": len(before),
        "active_after": len(surviving),
        "retention": (len(surviving) / len(before)) if before else 0.0,
        "citations_resolved": citations_ok,
        "citation_retention": (citations_ok / len(surviving)) if surviving else 0.0,
    }


def phase3_metrics(
        corpus: Corpus, queue: ReviewQueue, registry: RuleRegistry,
        claims: Iterable[DocumentClaim], *, learning_publisher: str,
        index: Any) -> dict[str, Any]:
    claim_rows = list(claims)
    recall = seeded_recall(corpus, queue)
    queue_metrics = queue.metrics()
    active = [record for record in registry.records(state="active")
              if record.id.startswith("phase3-")]
    accepted = queue_metrics["accepted"]
    transfer = transfer_metrics(
        corpus, registry, learning_publisher=learning_publisher)
    retention = retention_after_distractors(corpus, registry, index)
    publishers = {document.publisher for document in corpus.documents}
    genres = {document.genre for document in corpus.documents}
    return {
        "format": FORMAT,
        "version": VERSION,
        "review_protocol": "frozen-adjudication-ledger",
        "documents": len(corpus.documents),
        "publishers": len(publishers),
        "genres": len(genres),
        "publisher_ids": sorted(publishers),
        "genre_ids": sorted(genres),
        "claims": len(claim_rows),
        "review": queue_metrics,
        "seeded_recall": recall,
        "controls": control_metrics(corpus, claim_rows),
        "useful_yield": (
            accepted / len(claim_rows) if claim_rows else 0.0),
        "useful_yield_per_document": (
            accepted / len(corpus.documents) if corpus.documents else 0.0),
        "proposal_to_active": (
            len(active) / accepted if accepted else 0.0),
        "active_phase3_rules": len(active),
        "transfer": transfer,
        "retention": retention,
        "gate": {},
    }


def apply_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    review = metrics["review"]
    controls = metrics["controls"]
    gate = {
        "precision": review["precision"] >= 0.8,
        "seeded_recall": metrics["seeded_recall"]["recall"] >= 0.5,
        "review_minutes": review["review_minutes_per_claim"] <= 2.0,
        "controls": controls["passed"] == controls["total"],
        "transfer": metrics["transfer"]["coverage"] > 0.0,
        "retention": metrics["retention"]["retention"] >= 1.0,
        "proposal_to_active": metrics["proposal_to_active"] >= 0.8,
    }
    metrics["gate"] = gate
    metrics["gate_passed"] = all(gate.values())
    return metrics
