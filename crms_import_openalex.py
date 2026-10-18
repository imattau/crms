"""Discover scholarly works with OpenAlex and index bibliographic metadata.

This adapter stores OpenAlex metadata only. It never fetches article full text;
each copy's OA URL, version, and reported license are preserved for a later,
separately license-checked importer.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from crms_research import CRMSSQLiteResearchIndex


API = "https://api.openalex.org/works"
USER_AGENT = "CRMS OpenAlex metadata importer/1.0"
MAX_RESPONSE = 8 * 1024 * 1024
SELECT = ",".join(("id", "doi", "display_name", "publication_year", "type",
                   "authorships", "primary_location", "best_oa_location",
                   "open_access", "abstract_inverted_index"))


def _fetch(url: str, *, max_bytes: int = MAX_RESPONSE,
           timeout: float = 30.0) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": "application/json",
                                    "Accept-Encoding": "identity"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"OpenAlex response exceeds {max_bytes} byte limit")
    return payload


def _authors(work: dict) -> list[str]:
    names = []
    for authorship in work.get("authorships", ()):
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = author.get("display_name") if isinstance(author, dict) else None
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def _location_line(label: str, location: object) -> str:
    if not isinstance(location, dict):
        return f"{label}: none reported"
    source = location.get("source")
    source_name = (source.get("display_name")
                   if isinstance(source, dict) else None)
    values = [
        ("version", location.get("version")),
        ("license", location.get("license")),
        ("repository", source_name),
        ("landing page", location.get("landing_page_url")),
        ("PDF URL", location.get("pdf_url")),
    ]
    detail = "; ".join(f"{name}: {value}" for name, value in values
                        if isinstance(value, str) and value.strip())
    return f"{label}: {detail or 'no copy metadata reported'}"


def reconstruct_abstract(inverted_index: object, *, max_positions: int = 100_000
                         ) -> str:
    """Rebuild bounded OpenAlex abstract text from its word-position map."""
    if inverted_index is None:
        return ""
    if (not isinstance(inverted_index, dict)
            or len(inverted_index) > 50_000
            or type(max_positions) is not int or max_positions < 1):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted_index.items():
        if (not isinstance(word, str) or not word.strip()
                or len(word) > 256 or not isinstance(indexes, list)):
            return ""
        for position in indexes:
            if (type(position) is not int or position < 0
                    or position >= max_positions):
                return ""
            existing = positions.get(position)
            if existing is not None and existing != word:
                return ""
            positions[position] = word
    if (not positions or len(positions) > max_positions
            or min(positions) != 0
            or max(positions) + 1 != len(positions)):
        return ""
    words = [positions[index] for index in range(len(positions))]
    text = " ".join(words)
    text = re.sub(r"\s+([,.;:!?%\)\]\}])", r"\1", text)
    text = re.sub(r"([\(\[\{])\s+", r"\1", text)
    text = re.sub(r"\s+((?:n't|'s|'re|'ve|'ll|'d))\b", r"\1", text,
                  flags=re.IGNORECASE)
    return text.strip()


def format_work(work: dict) -> tuple[str, str, str, str] | None:
    """Return (stable id, title, searchable CC0 metadata text, location)."""
    work_id = work.get("id")
    title = work.get("display_name")
    if (not isinstance(work_id, str)
            or not re.fullmatch(r"https://openalex\.org/W\d+", work_id)
            or not isinstance(title, str) or not title.strip()):
        return None
    authors = _authors(work)
    year = work.get("publication_year")
    doi = work.get("doi")
    open_access = work.get("open_access")
    oa_status = (open_access.get("oa_status")
                 if isinstance(open_access, dict) else None)
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    lines = [
        "Source: OpenAlex scholarly works catalog",
        "Metadata license: CC0 (OpenAlex metadata only; not article text)",
        f"Title: {title.strip()}",
        f"Abstract: {abstract or 'not reported'}",
        f"Authors: {', '.join(authors) if authors else 'not reported'}",
        f"Publication year: {year if isinstance(year, int) else 'not reported'}",
        f"Work type: {work.get('type') or 'not reported'}",
        f"DOI: {doi if isinstance(doi, str) else 'not reported'}",
        f"OpenAlex ID: {work_id}",
        f"Open access status: {oa_status or 'not reported'}",
        _location_line("Best open copy", work.get("best_oa_location")),
        _location_line("Primary location", work.get("primary_location")),
        "Full text was not downloaded by this importer.",
    ]
    location = doi if isinstance(doi, str) and doi else work_id
    return f"openalex:{work_id.rsplit('/', 1)[-1]}", title.strip(), "\n".join(lines), location


def search_works(query: str, *, max_results: int = 100,
                 page_size: int = 25, mailto: str | None = None,
                 api_key: str | None = None, fetch=_fetch) -> list[dict]:
    """Fetch a bounded, deduplicated set of OpenAlex work metadata records."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty")
    if type(max_results) is not int or not 1 <= max_results <= 1000:
        raise ValueError("max_results must be between 1 and 1000")
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if mailto is not None and (not isinstance(mailto, str) or "@" not in mailto):
        raise ValueError("mailto must be a valid email address")
    results: list[dict] = []
    seen: set[str] = set()
    cursor = "*"
    while len(results) < max_results:
        params = {"search": query.strip(), "per_page": min(page_size, max_results - len(results)),
                  "cursor": cursor, "select": SELECT}
        if mailto:
            params["mailto"] = mailto
        if api_key:
            params["api_key"] = api_key
        url = API + "?" + urlencode(params)
        payload = json.loads(fetch(url, max_bytes=MAX_RESPONSE).decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ValueError("OpenAlex returned an unexpected works response")
        for work in payload["results"]:
            if not isinstance(work, dict):
                continue
            stable_id = work.get("id")
            if isinstance(stable_id, str) and stable_id not in seen:
                seen.add(stable_id)
                results.append(work)
                if len(results) >= max_results:
                    break
        meta = payload.get("meta")
        next_cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
        if not payload["results"] or not isinstance(next_cursor, str) or not next_cursor:
            break
        if not api_key and len(results) < max_results:
            raise ValueError(
                "OpenAlex requires an API key to continue cursor paging past "
                "the first page; set CRMS_OPENALEX_API_KEY or pass --api-key")
        cursor = next_cursor
    return results


def import_openalex(query: str, output: str | Path, *, max_results: int = 100,
                    append: bool = False, mailto: str | None = None,
                    api_key: str | None = None, fetch=_fetch
                    ) -> tuple[int, int, int]:
    """Index bibliographic metadata, with optional append to an existing DB."""
    path = Path(output).expanduser().resolve()
    if path.exists() and not append:
        raise FileExistsError(f"output already exists: {path}")
    works = search_works(query, max_results=max_results, mailto=mailto,
                         api_key=api_key, fetch=fetch)
    if not works:
        raise ValueError("OpenAlex search returned no works")
    if append and path.exists():
        index = CRMSSQLiteResearchIndex(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        index = CRMSSQLiteResearchIndex(path)
    added = duplicates = invalid = 0
    try:
        with index._bulk_write_context():
            for work in works:
                formatted = format_work(work)
                if formatted is None:
                    invalid += 1
                    continue
                document_id, title, body, location = formatted
                if index.contains_document(document_id):
                    duplicates += 1
                    continue
                index.add_document(document_id, title, body, location)
                added += 1
        if added == 0 and duplicates == 0:
            raise ValueError("OpenAlex response had no indexable work records")
        return added, duplicates, invalid
    finally:
        index.close()


def import_openalex_snapshot(
        files: list[str | Path], output: str | Path, *, append: bool = False,
        max_records: int | None = None, batch_size: int = 500,
        progress=None) -> tuple[int, int, int, int]:
    """Stream local OpenAlex works JSONL parts into the searchable SQLite index.

    Batches commit independently. If a process stops, rerunning with
    ``append=True`` is safe: stable OpenAlex work IDs deduplicate committed
    rows, while the final incomplete batch is rolled back with its transaction.
    """
    if not files:
        raise ValueError("at least one OpenAlex JSONL file is required")
    if max_records is not None and (type(max_records) is not int or max_records < 1):
        raise ValueError("max_records must be a positive integer")
    if type(batch_size) is not int or not 1 <= batch_size <= 10_000:
        raise ValueError("batch_size must be between 1 and 10000")
    path = Path(output).expanduser().resolve()
    if path.exists() and not append:
        raise FileExistsError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    index = CRMSSQLiteResearchIndex(path)
    added = duplicates = invalid = processed = 0
    try:
        with index._bulk_write_context():
            index._db.execute(
                "CREATE TABLE IF NOT EXISTS openalex_snapshot_parts ("
                "source_path TEXT PRIMARY KEY,file_size INTEGER NOT NULL,"
                "mtime_ns INTEGER NOT NULL,records INTEGER NOT NULL,"
                "added INTEGER NOT NULL,duplicates INTEGER NOT NULL,"
                "invalid INTEGER NOT NULL)")
        pending: list[tuple[str, str, str, str]] = []

        def flush() -> None:
            nonlocal added, duplicates
            if not pending:
                return
            with index._bulk_write_context():
                for document_id, title, body, location in pending:
                    if index.contains_document(document_id):
                        existing = index.document(document_id)
                        if (existing.title == title and existing.text == body
                                and existing.location == location):
                            duplicates += 1
                            continue
                        # A changed snapshot may revise a work while retaining
                        # its stable OpenAlex ID. Refresh changed indexed text
                        # instead of treating the old record as a duplicate.
                        index.add_document(document_id, title, body, location,
                                           replace=True)
                        added += 1
                        continue
                    index.add_document(document_id, title, body, location)
                    added += 1
            pending.clear()

        def input_files():
            for value in files:
                source_path = Path(value).expanduser()
                if source_path.is_dir():
                    for candidate in source_path.rglob("*"):
                        if (candidate.is_file()
                                and (candidate.name.startswith("part_")
                                     and candidate.suffix.casefold() == ".gz"
                                     or candidate.name.endswith(".jsonl")
                                     or candidate.name.endswith(".jsonl.gz"))):
                            yield candidate
                elif source_path.is_file():
                    yield source_path
                else:
                    raise FileNotFoundError(source_path)

        for filename in input_files():
            source_path = Path(filename).expanduser()
            stat = source_path.stat()
            checkpoint = index._db.execute(
                "SELECT file_size,mtime_ns,records,added,duplicates,invalid "
                "FROM openalex_snapshot_parts WHERE source_path=?",
                (str(source_path.resolve()),)).fetchone()
            if (max_records is None and checkpoint is not None
                    and checkpoint[0] == stat.st_size
                    and checkpoint[1] == stat.st_mtime_ns):
                processed += checkpoint[2]
                added += checkpoint[3]
                duplicates += checkpoint[4]
                invalid += checkpoint[5]
                if progress is not None:
                    progress(processed, added, duplicates, invalid,
                             str(source_path))
                continue
            if checkpoint is not None:
                with index._bulk_write_context():
                    index._db.execute(
                        "DELETE FROM openalex_snapshot_parts WHERE source_path=?",
                        (str(source_path.resolve()),))
            before_file = (processed, added, duplicates, invalid)
            opener = gzip.open if source_path.suffix.casefold() == ".gz" else open
            file_complete = False
            with opener(source_path, "rt", encoding="utf-8", errors="strict") as source:
                while True:
                    line = source.readline(16 * 1024 * 1024 + 1)
                    if not line:
                        file_complete = True
                        break
                    if not line.strip():
                        continue
                    if max_records is not None and processed >= max_records:
                        break
                    processed += 1
                    if len(line) > 16 * 1024 * 1024:
                        invalid += 1
                        while line and not line.endswith("\n"):
                            line = source.readline(16 * 1024 * 1024 + 1)
                        continue
                    try:
                        work = json.loads(line)
                    except (json.JSONDecodeError, UnicodeError):
                        invalid += 1
                        continue
                    if not isinstance(work, dict):
                        invalid += 1
                        continue
                    try:
                        formatted = format_work(work)
                    except (AttributeError, TypeError, ValueError):
                        formatted = None
                    if formatted is None:
                        invalid += 1
                        continue
                    pending.append(formatted)
                    if len(pending) >= batch_size:
                        flush()
                        if progress is not None:
                            progress(processed, added, duplicates, invalid,
                                     str(source_path))
                flush()
            if file_complete and max_records is None:
                file_counts = (processed - before_file[0], added - before_file[1],
                               duplicates - before_file[2],
                               invalid - before_file[3])
                with index._bulk_write_context():
                    index._db.execute(
                        "INSERT OR REPLACE INTO openalex_snapshot_parts "
                        "(source_path,file_size,mtime_ns,records,added,"
                        "duplicates,invalid) VALUES(?,?,?,?,?,?,?)",
                        (str(source_path.resolve()), stat.st_size,
                         stat.st_mtime_ns, *file_counts))
            if progress is not None:
                progress(processed, added, duplicates, invalid,
                         str(source_path))
            if max_records is not None and processed >= max_records:
                break
        if added == 0 and duplicates == 0 and invalid == 0:
            raise ValueError("OpenAlex snapshot files contained no work records")
        return added, duplicates, invalid, processed
    finally:
        index.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="OpenAlex works search")
    source.add_argument("--snapshot-jsonl", nargs="+", type=Path,
                        help="local works JSONL or gzip JSONL snapshot parts")
    parser.add_argument("--output", type=Path, required=True,
                        help="CRMS SQLite research index")
    parser.add_argument("--max-results", type=int, default=100,
                        help="maximum results to fetch (1-1000; default 100)")
    parser.add_argument("--max-records", type=int,
                        help="optional raw JSONL line limit for a snapshot import")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="snapshot transaction size (1-10000; default 500)")
    parser.add_argument("--append", action="store_true",
                        help="append to an existing CRMS SQLite index")
    parser.add_argument("--mailto", help="email for OpenAlex API identification")
    parser.add_argument("--api-key", default=os.environ.get("CRMS_OPENALEX_API_KEY"),
                        help="optional API key (or CRMS_OPENALEX_API_KEY)")
    args = parser.parse_args()
    try:
        if args.snapshot_jsonl:
            def report(processed, added, duplicates, invalid, filename):
                print(f"{filename}: records={processed}, added={added}, "
                      f"duplicates={duplicates}, invalid={invalid}",
                      file=sys.stderr)
            added, duplicates, invalid, processed = import_openalex_snapshot(
                args.snapshot_jsonl, args.output, append=args.append,
                max_records=args.max_records, batch_size=args.batch_size,
                progress=report)
        else:
            added, duplicates, invalid = import_openalex(
                args.query, args.output, max_results=args.max_results,
                append=args.append, mailto=args.mailto, api_key=args.api_key)
            processed = added + duplicates + invalid
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f"Processed {processed} OpenAlex records; indexed {added}, skipped "
          f"{duplicates} duplicates and {invalid} invalid records. Article full "
          "text was not downloaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
