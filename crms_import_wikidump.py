"""Stream a MediaWiki XML dump into a searchable CRMS SQLite source index."""

from __future__ import annotations

import argparse
import bz2
import gzip
from html import unescape
from pathlib import Path
import re
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from urllib.parse import urlencode, urlsplit, urlunsplit

from crms_research import CRMSSQLiteResearchIndex


MAX_PAGE_TEXT_BYTES = 64 * 1024 * 1024
WRITE_BATCH = 128


def render_wikitext(source: str) -> str:
    """Convert common wikitext structure into stable, searchable plain text."""
    source = re.sub(r"(?s)<!--.*?-->", " ", source)
    source = re.sub(r"(?is)<ref\b[^>]*/\s*>", " ", source)
    source = re.sub(r"(?is)<ref\b[^>]*>.*?</ref\s*>", " ", source)
    source = re.sub(r"(?is)</?(?:br|p|div|li|tr|h[1-6])\b[^>]*>", "\n", source)
    source = re.sub(r"(?is)<[^>]+>", " ", source)

    def internal_link(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        parts = target.split("|")
        destination = parts[0].strip()
        label = parts[-1].strip() if len(parts) > 1 else destination
        if destination.casefold().startswith(("file:", "image:", "category:")):
            return label if len(parts) > 1 else " "
        return label

    source = re.sub(r"\[\[([^\]]+)\]\]", internal_link, source)
    source = re.sub(r"\[(?:https?|ftp)://[^\s\]]+\s+([^\]]*)\]", r"\1", source)
    source = re.sub(r"\[(?:https?|ftp)://[^\]]+\]", " ", source)
    source = source.replace("'''", "").replace("''", "")
    source = re.sub(r"(?m)^\s*(?:={2,6})\s*(.*?)\s*(?:={2,6})\s*$",
                    r"\n\1\n", source)
    source = re.sub(r"(?m)^\s*[|!{}-]+\s*$", "\n", source)
    source = re.sub(r"(?m)^\s*[|!]+\s*", "", source)
    source = re.sub(r"(?m)^\s*[*#;:]+\s*", "", source)
    source = source.replace("||", " | ").replace("!!", " | ")
    source = source.replace("{{", "\n").replace("}}", "\n")
    source = source.replace("|", " ; ")
    source = unescape(source)
    lines = [re.sub(r"\s+", " ", line).strip()
             for line in source.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(
        line for line in lines if line)).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    child = next((item for item in element if _local_name(item.tag) == name), None)
    return child.text if child is not None else None


def _open_dump(path: Path):
    suffix = path.name.casefold()
    if suffix.endswith(".bz2"):
        return bz2.open(path, "rb")
    if suffix.endswith(".gz"):
        return gzip.open(path, "rb")
    return path.open("rb")


def _revision_url(base: str | None, title: str, revision_id: str) -> str | None:
    if not base:
        return None
    try:
        parsed = urlsplit(base)
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, "/w/index.php",
                       urlencode({"title": title, "oldid": revision_id}), ""))


def import_dump(source: str | Path, output: str | Path, *,
                license_name: str, license_url: str
                ) -> tuple[str, int, int]:
    """Import main-namespace, non-redirect pages without loading the dump whole.

    The output must not already exist. Each page is a separate citable source;
    common wikitext markup is rendered to readable text before indexing.
    The import is built beside the destination and renamed into place only
    after the entire dump parses successfully.
    """
    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if (not isinstance(license_name, str) or not license_name.strip()
            or not isinstance(license_url, str) or not license_url.strip()):
        raise ValueError(
            "an explicit license name and URL are required for dump import")
    try:
        license_parts = urlsplit(license_url)
        if (license_parts.scheme.casefold() not in {"http", "https"}
                or not license_parts.netloc):
            raise ValueError
    except ValueError as error:
        raise ValueError("license_url must be an absolute HTTP(S) URL") from error
    if not source_path.is_file():
        raise FileNotFoundError(f"MediaWiki dump does not exist: {source_path}")
    if output_path.exists():
        raise FileExistsError(f"output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
            prefix=output_path.name + ".", dir=output_path.parent) as temporary:
        temporary_index_path = Path(temporary) / "research.sqlite"
        index = CRMSSQLiteResearchIndex(temporary_index_path)
        page_count = 0
        revision_bytes = 0
        pending = []
        dbname = "mediawiki"
        base_url = None
        try:
            with _open_dump(source_path) as stream:
                stack: list[ElementTree.Element] = []
                try:
                    for event, element in ElementTree.iterparse(
                            stream, events=("start", "end")):
                        if event == "start":
                            stack.append(element)
                            continue
                        name = _local_name(element.tag)
                        if name == "siteinfo":
                            candidate = next((child.text for child in element
                                              if _local_name(child.tag) == "dbname"
                                              and child.text), None)
                            if candidate:
                                dbname = candidate.strip()
                            base_candidate = next((child.text for child in element
                                                   if _local_name(child.tag) == "base"
                                                   and child.text), None)
                            if base_candidate:
                                base_url = base_candidate.strip()
                        elif name == "page":
                            title = _child_text(element, "title") or ""
                            namespace = _child_text(element, "ns") or ""
                            page_id = _child_text(element, "id") or ""
                            redirected = any(
                                _local_name(child.tag) == "redirect"
                                for child in element)
                            revisions = [child for child in element
                                         if _local_name(child.tag) == "revision"]
                            revision = revisions[-1] if revisions else None
                            revision_id = (_child_text(revision, "id")
                                           if revision is not None else None)
                            text_element = (next((child for child in revision
                                                  if _local_name(child.tag) == "text"), None)
                                            if revision is not None else None)
                            raw_text = (text_element.text
                                        if text_element is not None else None)
                            if (namespace.strip() == "0" and not redirected
                                    and raw_text and title and page_id):
                                size = len(raw_text.encode("utf-8"))
                                if size > MAX_PAGE_TEXT_BYTES:
                                    raise ValueError(
                                        f"page {page_id} exceeds the 64 MiB text limit")
                                text = render_wikitext(raw_text)
                                if not text:
                                    if len(stack) >= 2:
                                        stack[-2].remove(element)
                                    element.clear()
                                    stack.pop()
                                    continue
                                document_id = f"wiki:{dbname}:{page_id}"
                                page_url = (_revision_url(
                                    base_url, title, revision_id)
                                    if revision_id else None)
                                source_reference = (page_url or
                                                    f"{source_path.name}#page={page_id}")
                                location = (
                                    f"{source_reference} [dump: {source_path.name}; "
                                    f"revision: {revision_id or 'not recorded'}; "
                                    f"license supplied by importer: {license_name.strip()} "
                                    f"({license_url.strip()}); readable text normalized "
                                    "from wikitext]")
                                pending.append((document_id, title, text, location))
                                revision_bytes += size
                                page_count += 1
                                if len(pending) >= WRITE_BATCH:
                                    with index._bulk_write_context():
                                        for row in pending:
                                            index.add_document(
                                                row[0], row[1], row[2], row[3])
                                    pending.clear()
                                if page_count % 10_000 == 0:
                                    print(f"Imported {page_count:,} pages...",
                                          file=sys.stderr, flush=True)
                            if len(stack) >= 2:
                                stack[-2].remove(element)
                            element.clear()
                        stack.pop()
                except ElementTree.ParseError as error:
                    raise ValueError(f"MediaWiki XML is malformed: {error}") from error
            if page_count == 0:
                raise ValueError("MediaWiki dump contained no readable main-namespace pages")
            if pending:
                with index._bulk_write_context():
                    for row in pending:
                        index.add_document(row[0], row[1], row[2], row[3])
                pending.clear()
            index.close()
            temporary_index_path.replace(output_path)
        except Exception:
            index.close()
            raise
    return dbname, page_count, revision_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path,
                        help="plain, .bz2, or .gz MediaWiki XML export")
    parser.add_argument("--output", type=Path, required=True,
                        help="new SQLite research index to create")
    parser.add_argument("--license-name", required=True,
                        help="license stated for this dump's page text")
    parser.add_argument("--license-url", required=True,
                        help="HTTP(S) URL for the stated license")
    args = parser.parse_args()
    try:
        dbname, pages, size = import_dump(
            args.dump, args.output, license_name=args.license_name,
            license_url=args.license_url)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        parser.error(str(error))
    print(f"Imported {pages:,} pages from {dbname} into {args.output} "
          f"({size:,} UTF-8 source-text bytes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
