"""Measure whether simple source-grounded argument types aid predicate discovery.

This is a read-only diagnostic, not a rule learner. It extracts coarse noun
heads from exact-title lead sentences and infobox fields, collects corpus
relation frames from bounded document windows, and reports same-domain/range
predicate candidates. No candidate is accepted or stored.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import re
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from crms_knowledge import CRMSKnowledgeBase, _tokens  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402


_TYPE_ADJUNCTS = frozenset({
    "in", "of", "with", "from", "for", "on", "at", "by", "through",
    "within", "without", "that", "who", "which", "where", "when",
    "because", "as", "such",
})


def _coarse_head(noun_phrase: str) -> str | None:
    words = list(_tokens(noun_phrase))
    if words[:3] == ["one", "of", "the"]:
        words = words[3:]
    cut = next((position for position, word in enumerate(words)
                if word in _TYPE_ADJUNCTS), len(words))
    words = words[:cut]
    if not words:
        return None
    head = words[-1]
    if len(head) > 4 and head.endswith("ies"):
        head = head[:-3] + "y"
    elif len(head) > 4 and head.endswith("s") and not head.endswith("ss"):
        head = head[:-1]
    return head


def _title_types(index: CRMSSQLiteResearchIndex,
                 maximum_documents: int) -> dict[tuple[str, ...], str]:
    candidates: dict[tuple[str, ...], set[str]] = defaultdict(set)
    infobox_line = re.compile(r"^[ \t]*Infobox\b", re.IGNORECASE)
    assignment = re.compile(r"^[ \t]*([\w -]{1,48})[ \t]*=[ \t]*(.*)$")
    for scanned, (document_id, title, _location) in enumerate(
            index.source_list(limit=maximum_documents), start=1):
        if scanned % 50_000 == 0:
            print(f"  class scan: {scanned}/{maximum_documents} pages",
                  flush=True)
        if not title:
            continue
        document = index.document(document_id)
        base_title = title.split("(", 1)[0].strip()
        pattern = re.compile(
            r"(?:^|(?<=[.!?])\s+|[\r\n]+)(?:the\s+)?"
            + re.escape(base_title)
            + r"(?:\s*\([^)]{1,200}\))?\s+"
            + r"(?:is|are|was|were)\s+"
            + r"(?P<phrase>[^.!?;]{2,160})",
            re.IGNORECASE)
        match = pattern.search(document.text[:8000])
        if match is not None:
            head = _coarse_head(match.group("phrase"))
            if head:
                candidates[tuple(_tokens(base_title))].add(head)

        # Normalized Wikipedia pages often put the lead after an infobox, and
        # their explicit `type` field may be the only concise class statement.
        # Read only exact assignments in the leading infobox; keep the value
        # as a source-derived candidate and discard conflicting page classes.
        in_infobox = False
        for line in document.text[:8000].splitlines():
            if not in_infobox:
                in_infobox = infobox_line.match(line) is not None
                continue
            field = assignment.match(line)
            if field is None:
                continue
            name = " ".join(field.group(1).casefold().split())
            if name not in {"type", "class", "kind", "entity type"}:
                continue
            head = _coarse_head(field.group(2))
            if head:
                candidates[tuple(_tokens(base_title))].add(head)
    return {entity: next(iter(heads)) for entity, heads in candidates.items()
            if len(heads) == 1}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "index", nargs="?", type=Path,
        default=PROJECT / "data" / "crms_simplewiki_research.sqlite")
    parser.add_argument("--type-documents", type=int, default=300_000)
    parser.add_argument("--window-documents", type=int, default=10_000)
    parser.add_argument("--window-count", type=int, default=5)
    parser.add_argument("--sentences-per-window", type=int, default=200_000)
    args = parser.parse_args()
    if not args.index.is_file():
        raise SystemExit(f"SQLite research index not found: {args.index}")
    if not 1 <= args.type_documents <= 300_000:
        raise SystemExit("--type-documents must be in 1..300000")
    if not 1 <= args.window_documents <= 10_000:
        raise SystemExit("--window-documents must be in 1..10000")
    if not 1 <= args.window_count <= 20:
        raise SystemExit("--window-count must be in 1..20")
    if not 1 <= args.sentences_per_window <= 1_000_000:
        raise SystemExit("--sentences-per-window must be in 1..1000000")

    index = CRMSSQLiteResearchIndex(args.index, read_only=True)
    try:
        document_count = index.document_count()
        type_limit = min(args.type_documents, document_count)
        types = _title_types(index, type_limit)
        print(f"Index documents: {document_count}")
        print(f"Read-only exact-title type candidates: {len(types)} / {type_limit}")
        print(f"Mode: report only; windows={args.window_count}; "
              "no proposals accepted or stored")

        aggregate: dict[str, dict[tuple[str, str], dict[
            tuple[tuple[str, ...], tuple[str, ...]], set[str]]]] = defaultdict(
                lambda: defaultdict(lambda: defaultdict(set)))
        total_frames = non_is_a_support = 0
        typed_subject = typed_object = typed_both = 0
        offsets = [round(index * max(document_count - args.window_documents, 0)
                         / max(args.window_count - 1, 1))
                   for index in range(args.window_count)]
        for offset in offsets:
            frames = CRMSKnowledgeBase().propose_corpus_relation_frames(
                index, maximum_documents=args.window_documents,
                maximum_sentences=args.sentences_per_window,
                maximum_proposals=1000, document_offset=offset)
            total_frames += len(frames)
            for frame in frames:
                if frame["relation"] == "is-a" or frame["polarity"] is not True:
                    continue
                relation = frame["relation"].casefold()
                for row in frame["support"]:
                    non_is_a_support += 1
                    subject_type = types.get(tuple(_tokens(row["subject"])))
                    object_type = types.get(tuple(_tokens(row["object"])))
                    typed_subject += subject_type is not None
                    typed_object += object_type is not None
                    if subject_type is None or object_type is None:
                        continue
                    typed_both += 1
                    pair = (tuple(_tokens(row["subject"])),
                            tuple(_tokens(row["object"])))
                    aggregate[relation][(subject_type, object_type)][pair].add(
                        row["document_id"])
            print(f"offset={offset}: relation_frames={len(frames)}")

        relation_names = sorted(aggregate)
        weak_hypotheses = []
        strong_hypotheses = []
        for left_index, left in enumerate(relation_names):
            for right in relation_names[left_index + 1:]:
                shared_types = set(aggregate[left]) & set(aggregate[right])
                for signature in shared_types:
                    left_pairs = aggregate[left][signature]
                    right_pairs = aggregate[right][signature]
                    # A type-only hypothesis is informative only when the
                    # observed entity pairs differ and their evidence comes
                    # from separate documents. It remains report-only.
                    independent = [
                        (left_pair, right_pair, left_docs, right_docs)
                        for left_pair, left_docs in left_pairs.items()
                        for right_pair, right_docs in right_pairs.items()
                        if (left_pair != right_pair
                            and left_docs.isdisjoint(right_docs))]
                    independent.sort(key=lambda row: (row[0], row[1]))
                    distinct_examples = []
                    used_left: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
                    used_right: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
                    for example in independent:
                        if example[0] in used_left or example[1] in used_right:
                            continue
                        distinct_examples.append(example)
                        used_left.add(example[0])
                        used_right.add(example[1])
                    if distinct_examples:
                        weak_hypotheses.append((
                            len(distinct_examples), left, right, signature,
                            distinct_examples))
                    if (len(left_pairs) >= 2 and len(right_pairs) >= 2
                            and len(distinct_examples) >= 2):
                        strong_hypotheses.append((
                            len(distinct_examples), left, right, signature,
                            distinct_examples))
        print(f"relation frames total: {total_frames}")
        print("typed endpoints across positive non-is-a supports "
              f"(subject/object/both): {typed_subject}/{typed_object}/{typed_both} "
              f"of {non_is_a_support}")
        print("distinct-pair, cross-document role-type hypotheses "
              f"(one typed pair per wording): {len(weak_hypotheses)}")
        print("same hypotheses with >=2 typed pairs per wording: "
              f"{len(strong_hypotheses)}")
        for support, left, right, signature, examples in sorted(
                weak_hypotheses, reverse=True)[:20]:
            left_pair, right_pair, left_docs, right_docs = examples[0]
            print(f"  {left} ~ {right}: role={signature[0]}→{signature[1]}; "
                  f"typed_support={support}; "
                  f"examples={' '.join(left_pair[0])}/{ ' '.join(left_pair[1]) }"
                  f" ~ {' '.join(right_pair[0])}/{ ' '.join(right_pair[1]) }")
    finally:
        index.close()


if __name__ == "__main__":
    main()
