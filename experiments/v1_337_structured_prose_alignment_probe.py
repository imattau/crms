"""Measure whether infobox fields can supervise corpus predicate learning.

Objective: test a higher-recall, source-grounded alignment signal than repeated
exact entity-pair overlap between prose predicates.

Setup: scan the full local SQLite corpus in deterministic 100,000-document
windows. Pair selected explicit infobox fields with complete prose
sentences that mention both the page entity (or its final title token) and the
field value. Parse the sentence with CRMS's current surface-relation parser.

Metrics: field rows, joint field/sentence mentions, role-compatible parses,
canonical-relation matches, and multi-document candidate groups.

Failure modes: title-token collisions, metadata/prose copied from one origin,
field values that name multiple entities, parser role errors, and canonical
field mappings that do not represent the same relation.

Definition of success: report candidate recall separately from evidence
quality. This diagnostic must never accept or store a fact or rule. Any useful
candidate path requires exact cited spans, multiple distinct entity pairs,
and explicit review before it can license language.

Run with: python3 experiments/v1_337_structured_prose_alignment_probe.py [INDEX]
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
import sys
from collections import defaultdict

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import (  # noqa: E402
    CRMSSQLiteResearchIndex, _sentence_spans,
)


DEFAULT_INDEX = PROJECT / "data" / "crms_simplewiki_research.sqlite"
DOCUMENTS_PER_WINDOW = 100_000
FIELD_RELATIONS = {
    # field: (canonical relation, role occupied by the page title)
    "birth_place": ("born in", "subject"),
    "capital": ("capital of", "object"),
    "designer": ("designed", "object"),
    "creator": ("created", "object"),
    "author": ("wrote", "object"),
}


def field_rows(text: str) -> list[tuple[str, str, int, int]]:
    """Return exact key/value spans from the first normalized infobox."""
    rows = []
    offset = 0
    in_infobox = False
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if not in_infobox:
            in_infobox = bool(re.match(r"^[ \t]*Infobox\b", content, re.I))
            offset += len(line)
            continue
        if not content.strip():
            offset += len(line)
            continue
        match = re.match(r"^[ \t]*([\w -]{1,48})[ \t]*=[ \t]*(.*)$", content)
        if match:
            key = " ".join(match.group(1).casefold().split())
            value = match.group(2).strip()
            if key in FIELD_RELATIONS and value:
                left = len(content) - len(content.lstrip())
                value_start = offset + left + match.start(2)
                value_end = offset + len(content)
                rows.append((key, value, value_start, value_end))
        offset += len(line)
    return rows


def token_key(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[\w’'-]+", text.casefold()))


def run(index_path: Path) -> None:
    if not index_path.is_file():
        raise SystemExit(f"SQLite research index not found: {index_path}")
    index = CRMSSQLiteResearchIndex(index_path, read_only=True)
    learner = CRMSKnowledgeBase()
    morphology = learner._licensed_predicate_spelling_rules()
    try:
        print(f"Index: {index_path}")
        print(f"Documents: {index.document_count()}")
        print("Mode: read-only; proposals are diagnostics only")
        all_pairs: dict[tuple[str, str], dict[tuple[str, ...], set[str]]] = {}
        for offset in range(0, index.document_count(), DOCUMENTS_PER_WINDOW):
            counts = defaultdict(int)
            pairs: dict[tuple[str, str], dict[tuple[str, ...], set[str]]] = {}
            examples = []
            for source_row in index.source_list(
                    limit=DOCUMENTS_PER_WINDOW, offset=offset):
                document = index.document(source_row[0])
                counts["documents"] += 1
                if not document.text.startswith("Infobox"):
                    continue
                title = document.title.strip()
                aliases = {title.casefold()}
                title_tokens = title.split()
                if len(title_tokens) > 1 and len(title_tokens[-1]) >= 4:
                    aliases.add(title_tokens[-1].casefold())
                digest = hashlib.sha256(
                    document.text.encode("utf-8")).hexdigest()
                for field, value, field_start, field_end in field_rows(document.text):
                    if len(value) > 100 or value.casefold() in {
                            "unknown", "none", "n/a", "not known"}:
                        continue
                    counts["field_rows"] += 1
                    canonical, title_role = FIELD_RELATIONS[field]
                    subject = title if title_role == "subject" else value
                    obj = title if title_role == "object" else value
                    wanted_subject = token_key(subject)
                    wanted_object = token_key(obj)
                    for start, end in _sentence_spans(document.text):
                        sentence = document.text[start:end].strip()
                        if not sentence.endswith((".", "!", "?")):
                            continue
                        lower = sentence.casefold()
                        if value.casefold() not in lower:
                            continue
                        if not any(alias and alias in lower for alias in aliases):
                            continue
                        counts["joint_mentions"] += 1
                        citation = (f"{document.document_id}#sha256={digest}"
                                    f"&chars={start}:{end}")
                        candidates = learner._discover_surface_relation_candidates(
                            sentence, source=citation, research_index=index,
                            morphology_rules=morphology)
                        role_matches = [candidate for candidate in candidates
                                        if (token_key(candidate.object) == wanted_object
                                            and (token_key(candidate.subject)
                                                 == wanted_subject
                                                 or candidate.subject.casefold()
                                                 in aliases))]
                        if len(role_matches) != 1:
                            continue
                        candidate = role_matches[0]
                        counts["role_parses"] += 1
                        same_relation = token_key(candidate.relation) == token_key(canonical)
                        if same_relation:
                            counts["canonical_matches"] += 1
                        group = (canonical, candidate.relation)
                        pairs.setdefault(group, {}).setdefault(
                            (wanted_subject, wanted_object), set()).add(
                                document.document_id)
                        all_pairs.setdefault(group, {}).setdefault(
                            (wanted_subject, wanted_object), set()).add(
                                document.document_id)
                        if len(examples) < 5:
                            examples.append((field, title, value, canonical,
                                             candidate.relation, sentence,
                                             same_relation))

            candidate_groups = []
            novel_candidate_groups = []
            for (canonical, surface), support in sorted(pairs.items()):
                distinct_pairs = len(support)
                distinct_documents = len({doc for docs in support.values()
                                          for doc in docs})
                if distinct_pairs >= 2 and distinct_documents >= 2:
                    item = (canonical, surface, distinct_pairs,
                            distinct_documents)
                    candidate_groups.append(item)
                    if token_key(canonical) != token_key(surface):
                        novel_candidate_groups.append(item)
            print(f"offset={offset}: documents={counts['documents']}, "
                  f"field_rows={counts['field_rows']}, "
                  f"joint_mentions={counts['joint_mentions']}, "
                  f"role_parses={counts['role_parses']}, "
                  f"canonical_matches={counts['canonical_matches']}, "
                  f"candidate_groups={len(candidate_groups)}, "
                  f"novel_candidate_groups={len(novel_candidate_groups)}")
            for item in candidate_groups[:5]:
                print("  candidate:", item)
            for example in examples[:3]:
                print("  example:", example)
        all_candidate_groups = []
        all_novel_candidate_groups = []
        for (canonical, surface), support in sorted(all_pairs.items()):
            distinct_pairs = len(support)
            distinct_documents = len({doc for docs in support.values()
                                      for doc in docs})
            if distinct_pairs >= 2 and distinct_documents >= 2:
                item = (canonical, surface, distinct_pairs, distinct_documents)
                all_candidate_groups.append(item)
                if token_key(canonical) != token_key(surface):
                    all_novel_candidate_groups.append(item)
        print("Full-corpus candidates:", len(all_candidate_groups),
              "novel predicate groups:", len(all_novel_candidate_groups))
        for item in all_candidate_groups[:10]:
            print("  corpus candidate:", item)
        for item in all_novel_candidate_groups[:10]:
            print("  novel predicate:", item)
    finally:
        index.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", type=Path, default=DEFAULT_INDEX)
    run(parser.parse_args().index)


if __name__ == "__main__":
    main()
