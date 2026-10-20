"""Discover predicate variants from structured/prose co-occurrence without a field map.

The probe groups exact page-title/field-value relations by the observed
infobox field name and the role occupied by the page title. It learns the
most frequent predicate wording on training pages, proposes less frequent
wordings only as report-only candidates, and measures whether each wording
also appears on a document-held-out split. Field names are grouping cues, not
semantic labels. No proposal is accepted or written to CRMS memory.

Run:
    python3 experiments/v1_464_unmapped_structured_predicate_discovery.py \
        [INDEX] [--limit N] [--json-out PATH]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase, _tokens  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex, _sentence_spans  # noqa: E402

DEFAULT_INDEX = PROJECT / "data" / "crms_simplewiki_research.sqlite"
MINIMUM_PAIRS = 2


def _key(text: str) -> tuple[str, ...]:
    words = tuple(_tokens(text))
    if words[:1] in {("the",), ("a",), ("an",)}:
        return words[1:]
    return words


def _contains_phrase(sentence_tokens: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    return bool(phrase) and any(
        sentence_tokens[index:index + len(phrase)] == phrase
        for index in range(len(sentence_tokens) - len(phrase) + 1))


def _field_rows(text: str) -> list[tuple[str, str, int, int]]:
    """Extract every exact key/value line from the first infobox."""
    rows = []
    offset = 0
    in_infobox = False
    assignment = re.compile(r"^[ \t]*([\w -]{1,48})[ \t]*=[ \t]*(.*)$")
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not in_infobox:
            in_infobox = bool(re.match(r"^[ \t]*Infobox\b", content, re.I))
            offset += len(line)
            continue
        match = assignment.match(content)
        if match:
            field = " ".join(match.group(1).casefold().split())
            value = match.group(2).strip()
            if value:
                leading = len(content) - len(content.lstrip())
                rows.append((field, value, offset + leading, offset + len(content)))
        offset += len(line)
    return rows


def _prose_spans(text: str) -> list[tuple[int, int]]:
    assignment = re.compile(r"^[ \t]*[\w -]{1,48}[ \t]*=")
    structured_lines = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if assignment.match(content):
            structured_lines.append((offset, offset + len(content)))
        offset += len(line)
    return [
        (start, end) for start, end in _sentence_spans(text)
        if not any(start < line_end and end > line_start
                   for line_start, line_end in structured_lines)
    ]


def _holdout(document_id: str) -> bool:
    return int(hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:8], 16) % 5 == 0


def _citation(document_id: str, digest: str, start: int, end: int) -> str:
    return f"{document_id}#sha256={digest}&chars={start}:{end}"


def run(index_path: Path, *, maximum_documents: int | None = None) -> dict[str, Any]:
    if not index_path.is_file():
        raise FileNotFoundError(index_path)
    index = CRMSSQLiteResearchIndex(index_path, read_only=True)
    learner = CRMSKnowledgeBase()
    morphology = learner._licensed_predicate_spelling_rules()
    # (field, title role, predicate) -> split -> pair -> support rows
    groups: dict[tuple[str, str, str], dict[str, dict[tuple, dict[str, Any]]]] = defaultdict(
        lambda: {"train": {}, "holdout": {}})
    counters = defaultdict(int)
    total = index.document_count()
    limit = total if maximum_documents is None else min(total, maximum_documents)
    try:
        for source_row in index.source_list(limit=limit):
            counters["documents_scanned"] += 1
            if counters["documents_scanned"] % 25_000 == 0:
                print(f"scanned {counters['documents_scanned']}/{limit} documents",
                      flush=True)
            document = index.document(source_row[0])
            if not document.text.startswith("Infobox") or not document.title.strip():
                continue
            title_key = _key(document.title)
            if not title_key:
                continue
            split = "holdout" if _holdout(document.document_id) else "train"
            fields = [row for row in _field_rows(document.text)
                      if row[1] and len(row[1]) <= 100
                      and row[1].casefold() not in {"unknown", "none", "n/a", "not known"}]
            if not fields:
                continue
            spans = _prose_spans(document.text)
            if not spans:
                continue
            digest = hashlib.sha256(document.text.encode("utf-8")).hexdigest()
            parsed_sentences = {}
            for field, value, field_start, field_end in fields:
                value_key = _key(value)
                if not value_key:
                    continue
                for start, end in spans:
                    sentence = document.text[start:end].strip()
                    if not sentence.endswith((".", "!", "?")):
                        continue
                    sentence_tokens = tuple(_tokens(sentence))
                    if (not _contains_phrase(sentence_tokens, title_key)
                            or not _contains_phrase(sentence_tokens, value_key)):
                        continue
                    counters["joint_field_sentence_mentions"] += 1
                    sentence_citation = _citation(
                        document.document_id, digest, start, end)
                    field_citation = _citation(
                        document.document_id, digest, field_start, field_end)
                    if (start, end) not in parsed_sentences:
                        parsed_sentences[(start, end)] = (
                            sentence_citation,
                            learner._discover_surface_relation_candidates(
                                sentence, source=sentence_citation,
                                research_index=index,
                                morphology_rules=morphology))
                    candidates = parsed_sentences[(start, end)][1]
                    matches = []
                    for candidate in candidates:
                        if candidate.polarity is not True:
                            continue
                        subject_key, object_key = _key(candidate.subject), _key(candidate.object)
                        if subject_key == title_key and object_key == value_key:
                            matches.append(("title-subject", candidate))
                        elif object_key == title_key and subject_key == value_key:
                            matches.append(("title-object", candidate))
                    if len(matches) != 1:
                        counters["ambiguous_or_role_mismatch"] += 1
                        continue
                    role, candidate = matches[0]
                    predicate = " ".join(str(item.get("predicate_phrase", ""))
                                          for item in candidate.language_evidence
                                          if item.get("kind") == "surface_relation_discovery").strip()
                    if not predicate:
                        predicate = candidate.relation
                    predicate = " ".join(predicate.casefold().split())
                    if not predicate:
                        continue
                    counters["role_compatible_mentions"] += 1
                    pair = (tuple(_tokens(candidate.subject)),
                            tuple(_tokens(candidate.object)))
                    row = {
                        "field": field,
                        "title": document.title,
                        "field_value": value,
                        "title_role": role,
                        "subject": candidate.subject,
                        "predicate": predicate,
                        "object": candidate.object,
                        "field_line": document.text[field_start:field_end],
                        "sentence": sentence,
                        "field_citation": field_citation,
                        "sentence_citation": sentence_citation,
                        "document_id": document.document_id,
                    }
                    # One sentence/field contributes at most once per pair and page.
                    groups[(field, role, predicate)][split].setdefault(pair, row)

        proposals = []
        field_role_groups = defaultdict(list)
        for (field, role, predicate), splits in groups.items():
            training = splits["train"]
            if len(training) >= MINIMUM_PAIRS:
                field_role_groups[(field, role)].append((predicate, splits))
        for (field, role), items in sorted(field_role_groups.items()):
            ranked = sorted(items, key=lambda item: (-len(item[1]["train"]), item[0]))
            canonical, canonical_splits = ranked[0]
            canonical_train = canonical_splits["train"]
            for phrase, splits in ranked[1:]:
                candidate_train = splits["train"]
                if len(candidate_train) < MINIMUM_PAIRS:
                    continue
                if len(candidate_train) >= len(canonical_train):
                    continue
                proposals.append({
                    "field": field,
                    "title_role": role,
                    "dominant_training_phrase": canonical,
                    "candidate_phrase": phrase,
                    "training_support_pairs": len(candidate_train),
                    "training_dominant_pairs": len(canonical_train),
                    "holdout_candidate_pairs": len(splits["holdout"]),
                    "holdout_dominant_pairs": len(canonical_splits["holdout"]),
                    "support": list(candidate_train.values())[:4],
                    "heldout_support": list(splits["holdout"].values())[:4],
                    "dominant_examples": list(canonical_train.values())[:2],
                    "status": "report-only; field name is weak grouping evidence",
                    "accepted": False,
                })
        proposals.sort(key=lambda row: (
            -row["training_support_pairs"], -row["holdout_candidate_pairs"],
            row["field"], row["title_role"], row["candidate_phrase"]))
        return {
            "experiment": "v1_464_unmapped_structured_predicate_discovery",
            "index": str(index_path),
            "index_document_count": total,
            "documents_scanned": counters["documents_scanned"],
            "split": "document_id sha256 bucket mod 5 == 0 is holdout; all others train",
            "field_to_relation_map": None,
            "counters": dict(counters),
            "field_role_groups_with_repeated_training_pairs": len(field_role_groups),
            "candidate_count": len(proposals),
            "candidates": proposals[:100],
            "limitations": [
                "This experiment uses SimpleWiki only; document holdout does not test publisher transfer.",
                "The same page supplies the structured field and prose sentence, so source independence is absent.",
                "The dominant predicate phrase is a statistical anchor, not a verified canonical relation.",
                "The parser and morphology rules are existing CRMS mechanisms; their errors remain in scope.",
                "Candidates are report-only and have not been manually labeled in this run.",
            ],
        }
    finally:
        index.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = run(args.index, maximum_documents=args.limit)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(json.dumps({
        key: report[key] for key in (
            "experiment", "index_document_count", "documents_scanned",
            "split", "field_to_relation_map", "counters",
            "field_role_groups_with_repeated_training_pairs", "candidate_count")
    }, ensure_ascii=False, indent=2))
    for candidate in report["candidates"][:20]:
        print("CANDIDATE", json.dumps({key: candidate[key] for key in (
            "field", "title_role", "dominant_training_phrase", "candidate_phrase",
            "training_support_pairs", "training_dominant_pairs",
            "holdout_candidate_pairs", "holdout_dominant_pairs")}, ensure_ascii=False))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
