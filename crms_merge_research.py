"""Merge separately imported SQLite research corpora without losing provenance."""

from __future__ import annotations

import argparse
import json
from itertools import islice
import os
from pathlib import Path
import sqlite3
import tempfile

from crms_research import CRMSSQLiteResearchIndex


def _source_rows(path: Path):
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "source_documents" not in tables:
            raise ValueError(f"not a CRMS SQLite research index: {path}")
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(source_documents)")}
        required = {"document_id", "title", "location", "body", "pages_json"}
        if not required <= columns:
            raise ValueError(f"research index schema is incomplete: {path}")
        cursor = connection.execute(
            "SELECT document_id,title,location,body,pages_json "
            "FROM source_documents ORDER BY document_id")
        while rows := cursor.fetchmany(128):
            yield from rows
    finally:
        connection.close()


def merge_research_indexes(
        sources: list[str | Path], output: str | Path, *, append: bool = False,
        conflict: str = "error", batch_size: int = 256
        ) -> dict[str, int | str]:
    """Merge local indexes into one FTS-backed SQLite index atomically.

    Identical document IDs and contents are deduplicated. Conflicting content
    for one ID errors by default; callers can explicitly keep the first copy
    or replace it with the later source. Distinct IDs retain distinct source
    records, even when their text happens to match.
    """
    if conflict not in {"error", "keep-first", "replace-later"}:
        raise ValueError("conflict must be error, keep-first, or replace-later")
    if type(batch_size) is not int or not 1 <= batch_size <= 10_000:
        raise ValueError("batch_size must be between 1 and 10000")
    destination = Path(output).expanduser().resolve()
    source_paths = [Path(value).expanduser().resolve() for value in sources]
    if not source_paths:
        raise ValueError("at least one source research index is required")
    if len(set(source_paths)) != len(source_paths):
        raise ValueError("source index paths must be unique")
    if destination in source_paths:
        raise ValueError("output cannot also be an input source")
    if destination.exists() and not append:
        raise FileExistsError(f"output already exists: {destination}")
    if append and not destination.is_file():
        raise FileNotFoundError(f"--append requires an existing output: {destination}")
    if any(not path.is_file() for path in source_paths):
        missing = next(path for path in source_paths if not path.is_file())
        raise FileNotFoundError(f"research index does not exist: {missing}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered_sources = ([destination] if append else []) + source_paths
    fd, temporary_name = tempfile.mkstemp(
        prefix=destination.name + ".merge-", suffix=".sqlite",
        dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    temporary.unlink()
    index = CRMSSQLiteResearchIndex(temporary)
    added = duplicates = replaced = conflicts = documents = 0
    try:
        for source_path in ordered_sources:
            rows = iter(_source_rows(source_path))
            while batch := list(islice(rows, batch_size)):
                with index._bulk_write_context():
                    for row in batch:
                        document_id, title, location, body, pages_json = row
                        try:
                            pages = json.loads(pages_json)
                        except (TypeError, json.JSONDecodeError) as error:
                            raise ValueError(
                                f"invalid page data in {source_path}: "
                                f"{document_id}") from error
                        if (not isinstance(pages, list)
                                or any(not isinstance(page, str) for page in pages)
                                or (pages and "\n\f\n".join(pages) != body)):
                            raise ValueError(
                                f"inconsistent page data in {source_path}: "
                                f"{document_id}")
                        documents += 1
                        if index.contains_document(document_id):
                            existing = index.document(document_id)
                            same = (existing.title == title
                                    and existing.location == location
                                    and existing.text == body
                                    and list(existing.pages) == pages)
                            if same:
                                duplicates += 1
                                continue
                            conflicts += 1
                            if conflict == "error":
                                raise ValueError(
                                    f"conflicting document ID {document_id!r} in "
                                    f"{source_path}; choose --conflict keep-first "
                                    "or --conflict replace-later to resolve explicitly")
                            if conflict == "keep-first":
                                continue
                            index.add_document(
                                document_id, title, body, location,
                                replace=True, pages=pages)
                            replaced += 1
                        else:
                            index.add_document(
                                document_id, title, body, location, pages=pages)
                            added += 1
        corpus_documents, corpus_bytes = index.corpus_stats()
        index.close()
        # Re-open through the public index implementation before publishing.
        check = CRMSSQLiteResearchIndex(temporary)
        try:
            if check.corpus_stats() != (corpus_documents, corpus_bytes):
                raise ValueError("merged research index failed its count check")
        finally:
            check.close()
        os.replace(temporary, destination)
        return {
            "output": str(destination), "sources": len(ordered_sources),
            "input_documents": documents, "added": added,
            "identical_duplicates": duplicates, "replaced": replaced,
            "conflicts": conflicts, "documents": corpus_documents,
            "source_bytes": corpus_bytes,
        }
    except Exception:
        try:
            index.close()
        except Exception:
            pass
        temporary.unlink(missing_ok=True)
        Path(str(temporary) + "-wal").unlink(missing_ok=True)
        Path(str(temporary) + "-shm").unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="new or existing combined SQLite research index")
    parser.add_argument("--append", action="store_true",
                        help="include the existing output before merging new sources")
    parser.add_argument("--conflict", choices=("error", "keep-first", "replace-later"),
                        default="error",
                        help="explicit policy for different content with the same ID")
    parser.add_argument("--batch-size", type=int, default=256,
                        help="number of source documents per SQLite transaction")
    parser.add_argument("sources", nargs="+", type=Path,
                        help="SQLite research indexes to merge")
    args = parser.parse_args()
    result = merge_research_indexes(
        args.sources, args.output, append=args.append, conflict=args.conflict,
        batch_size=args.batch_size)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
