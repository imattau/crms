"""Compare exploratory and integrated alignment paths on identical documents.

Both paths are report-only. The script copies only documents eligible for the
exploratory scan into a temporary SQLite index, then runs both candidate
generators against that same document set. The original research index is
opened read-only and is never modified.

Run with:
    python3 experiments/v1_458_matched_structured_alignment.py [INDEX]
"""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import io
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "experiments"))

from crms_knowledge import CRMSKnowledgeBase  # noqa: E402
from crms_research import CRMSSQLiteResearchIndex  # noqa: E402
from v1_337_structured_prose_alignment_probe import (  # noqa: E402
    DEFAULT_INDEX, FIELD_RELATIONS, field_rows, prose_sentence_spans,
    run as run_probe, token_key,
)


def eligible_for_probe(text: str, title: str) -> bool:
    """Match the probe's document, field, and joint-mention scope."""
    if not text.startswith("Infobox"):
        return False
    aliases = {title.casefold()}
    title_tokens = title.split()
    if len(title_tokens) > 1 and len(title_tokens[-1]) >= 4:
        aliases.add(title_tokens[-1].casefold())
    for field, value, _start, _end in field_rows(text):
        if field not in FIELD_RELATIONS or not value or len(value) > 100:
            continue
        if value.casefold() in {"unknown", "none", "n/a", "not known"}:
            continue
        for start, end in prose_sentence_spans(text):
            sentence = text[start:end].strip()
            if not sentence.endswith((".", "!", "?")):
                continue
            lower = sentence.casefold()
            if value.casefold() in lower and any(
                    alias and alias in lower for alias in aliases):
                return True
    return False


def pair_set(rows: list[dict[str, object]]) -> set[
        tuple[tuple[str, ...], tuple[str, ...]]]:
    return {
        (token_key(str(row["subject"])), token_key(str(row["object"])))
        for row in rows
    }


def main(index_path: Path = DEFAULT_INDEX) -> None:
    if not index_path.is_file():
        raise SystemExit(f"SQLite research index not found: {index_path}")
    source = CRMSSQLiteResearchIndex(index_path, read_only=True)
    selected_count = 0
    total = source.document_count()
    try:
        with tempfile.TemporaryDirectory(prefix="crms-v1-458-") as folder:
            subset_path = Path(folder) / "matched.sqlite"
            subset = CRMSSQLiteResearchIndex(subset_path)
            for source_row in source.source_list(limit=total):
                document = source.document(source_row[0])
                if eligible_for_probe(document.text, document.title):
                    subset.add_document(
                        document.document_id, document.title,
                        document.text, document.location)
                    selected_count += 1
            subset_count = subset.document_count()
            subset.close()

            captured = io.StringIO()
            with redirect_stdout(captured):
                exploratory = run_probe(subset_path)
            subset = CRMSSQLiteResearchIndex(subset_path, read_only=True)
            try:
                integrated = CRMSKnowledgeBase()._propose_structured_predicate_alignments(
                    subset, minimum_pairs=2,
                    maximum_documents=max(1, subset_count),
                    maximum_sentences=1_000_000, maximum_proposals=100,
                    document_offset=0)
            finally:
                subset.close()

        exploratory_capital = exploratory.get(
            ("capital of", "capital city of"), {})
        probe_pairs = set(exploratory_capital)
        integrated_capital = next((proposal for proposal in integrated
                                   if proposal["relation"] == "capital of"
                                   and proposal["predicate_phrase"]
                                   == "capital city of"), None)
        integrated_pairs = (pair_set(integrated_capital["support"])
                            if integrated_capital else set())

        probe_groups = [
            (canonical, surface, len(pairs),
             len({document for docs in pairs.values() for document in docs}))
            for (canonical, surface), pairs in exploratory.items()
            if len(pairs) >= 2
        ]
        print(f"Original documents: {total}")
        print(f"Matched eligible documents copied: {selected_count}")
        print(f"Temporary index document count: {subset_count}")
        print(f"Probe candidate groups (minimum two pairs): {len(probe_groups)}")
        for group in sorted(probe_groups):
            print("  probe:", group)
        print("Integrated candidate groups:", len(integrated))
        for proposal in integrated:
            print("  integrated:", proposal["relation"], "=>",
                  proposal["predicate_phrase"],
                  "pairs=", proposal["distinct_pairs"])
        print("Capital wording pairs on matched documents:")
        print("  exploratory:", len(probe_pairs))
        print("  integrated:", len(integrated_pairs))
        print("  overlap:", len(probe_pairs & integrated_pairs))
        print("  exploratory-only:", len(probe_pairs - integrated_pairs))
        print("  integrated-only:", len(integrated_pairs - probe_pairs))
        if probe_pairs != integrated_pairs:
            raise SystemExit(
                "matched capital support differs between the two paths")
        print("PASS: both paths agree on capital alignment support")
    finally:
        source.close()


if __name__ == "__main__":
    argument = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INDEX
    main(argument)
