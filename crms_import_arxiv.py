"""Search arXiv and index licensed metadata or explicitly requested full text."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from crms_research import CRMSSQLiteResearchIndex


API = "https://export.arxiv.org/api/query"
OAI = "https://oaipmh.arxiv.org/oai"
ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
ARXIV_RAW = "http://arxiv.org/OAI/arXivRaw/"
MAX_RESPONSE = 8 * 1024 * 1024
MAX_PDF = 64 * 1024 * 1024
USER_AGENT = "CRMS arXiv metadata importer/1.0"


def _fetch(url: str, *, max_bytes: int = MAX_RESPONSE,
           timeout: float = 45.0) -> bytes:
    accept = ("application/pdf" if urlsplit(url).path.startswith("/pdf/")
              else "application/xml, application/atom+xml, text/xml")
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": accept,
                                    "Accept-Encoding": "identity"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"arXiv API response exceeds {max_bytes} byte limit")
    return payload


def parse_feed(payload: bytes) -> list[dict[str, str]]:
    """Parse Atom entries without retaining abstracts or fetching article text."""
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE:
        raise ValueError("arXiv response is invalid or exceeds the size limit")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError(f"malformed arXiv Atom response: {error}") from error
    if root.tag != f"{{{ATOM}}}feed":
        raise ValueError("arXiv API response is not an Atom feed")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in root.findall(f"{{{ATOM}}}entry"):
        identifier = (entry.findtext(f"{{{ATOM}}}id") or "").strip()
        match = re.fullmatch(r"https?://arxiv\.org/abs/([\w.\-/]+?)(v\d+)?", identifier)
        title = " ".join((entry.findtext(f"{{{ATOM}}}title") or "").split())
        abstract = " ".join((entry.findtext(f"{{{ATOM}}}summary") or "").split())
        if not match or not title:
            continue
        base_id, version = match.group(1), match.group(2) or "v1"
        if ".." in base_id or base_id.startswith("/"):
            continue
        authors = [" ".join((node.findtext(f"{{{ATOM}}}name") or "").split())
                   for node in entry.findall(f"{{{ATOM}}}author")]
        authors = [name for name in authors if name]
        categories = sorted({node.attrib["term"] for node in
                             entry.findall(f"{{{ATOM}}}category")
                             if node.attrib.get("term")})
        primary_node = entry.find(f"{{{ARXIV}}}primary_category")
        doi_node = entry.find(f"{{{ARXIV}}}doi")
        published = (entry.findtext(f"{{{ATOM}}}published") or "").strip()
        updated = (entry.findtext(f"{{{ATOM}}}updated") or "").strip()
        arxiv_id = f"{base_id}{version}"
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        entries.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": abstract,
            "authors": ", ".join(authors),
            "published": published,
            "updated": updated,
            "categories": ", ".join(categories),
            "primary_category": (primary_node.attrib.get("term", "")
                                 if primary_node is not None else ""),
            "doi": (doi_node.text or "").strip() if doi_node is not None else "",
            "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return entries


def search_arxiv(query: str, *, start: int = 0, max_results: int = 100,
                 sort_by: str = "relevance", sort_order: str = "descending",
                 fetch=_fetch
                 ) -> list[dict[str, str]]:
    """Run one bounded arXiv API page; callers may resume with a later offset."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty")
    if type(start) is not int or start < 0:
        raise ValueError("start must be a non-negative integer")
    if type(max_results) is not int or not 1 <= max_results <= 100:
        raise ValueError("max_results must be between 1 and 100")
    if sort_by not in {"relevance", "lastUpdatedDate", "submittedDate"}:
        raise ValueError("sort_by must be relevance, lastUpdatedDate, or submittedDate")
    if sort_order not in {"ascending", "descending"}:
        raise ValueError("sort_order must be ascending or descending")
    params = {"search_query": query.strip(), "start": start,
              "max_results": max_results, "sortBy": sort_by,
              "sortOrder": sort_order}
    payload = fetch(API + "?" + urlencode(params), max_bytes=MAX_RESPONSE)
    return parse_feed(payload)


def _split_arxiv_version(arxiv_id: str) -> tuple[str, str]:
    match = re.fullmatch(r"([\w.\-/]+?)(v\d+)", arxiv_id)
    if not match:
        raise ValueError("arXiv record has no explicit version")
    return match.group(1), match.group(2)


def resolve_arxiv_license(payload: bytes, arxiv_id: str) -> dict[str, str]:
    """Read OAI arXivRaw license and ensure its latest version matches search."""
    base_id, expected_version = _split_arxiv_version(arxiv_id)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError(f"malformed arXiv OAI response: {error}") from error
    if root.tag != f"{{{OAI_NS}}}OAI-PMH":
        raise ValueError("arXiv license response is not an OAI-PMH record")
    errors = root.findall(f"{{{OAI_NS}}}error")
    if errors:
        raise ValueError("arXiv OAI-PMH did not return the requested record")
    record = root.find(f"{{{OAI_NS}}}GetRecord/{{{OAI_NS}}}record")
    if record is None:
        raise ValueError("arXiv OAI response has no record")
    header = record.find(f"{{{OAI_NS}}}header")
    expected_identifier = f"oai:arXiv.org:{base_id}"
    if header is None or header.findtext(f"{{{OAI_NS}}}identifier") != expected_identifier:
        raise ValueError("arXiv OAI record identifier does not match the requested paper")
    datestamp = (header.findtext(f"{{{OAI_NS}}}datestamp") or "").strip()
    metadata = record.find(f"{{{OAI_NS}}}metadata/{{{ARXIV_RAW}}}arXivRaw")
    if metadata is None:
        raise ValueError("arXiv OAI response lacks arXivRaw metadata")
    metadata_id = (metadata.findtext(f"{{{ARXIV_RAW}}}id") or "").strip()
    if metadata_id != base_id:
        raise ValueError("arXiv OAI metadata ID does not match the requested paper")
    versions = [item.attrib.get("version", "") for item in
                metadata.findall(f"{{{ARXIV_RAW}}}version")]
    if not versions or versions[-1] != expected_version:
        raise ValueError("arXiv version changed between search and license lookup")
    license_uri = (metadata.findtext(f"{{{ARXIV_RAW}}}license") or "").strip()
    try:
        parsed = urlsplit(license_uri)
        safe_uri = (parsed.scheme.casefold() in {"http", "https"}
                    and parsed.netloc.casefold() == "creativecommons.org"
                    and not parsed.query and not parsed.fragment)
    except ValueError:
        safe_uri = False
        parsed = urlsplit("")
    host = (parsed.hostname or "").casefold()
    path = parsed.path.rstrip("/").casefold()
    if (safe_uri and host == "creativecommons.org"
            and path == "/publicdomain/zero/1.0"):
        license_name = "CC0"
    elif (safe_uri and host == "creativecommons.org"
          and path in {"/licenses/by/1.0", "/licenses/by/2.0",
                       "/licenses/by/2.5", "/licenses/by/3.0",
                       "/licenses/by/4.0"}):
        license_name = "CC BY"
    else:
        license_name = ""
    return {"license_uri": license_uri, "license_name": license_name,
            "version": expected_version, "datestamp": datestamp,
            "base_id": base_id}


def _fulltext_attribution(record: dict[str, str], license_record: dict[str, str],
                          pdf_digest: str) -> str:
    return "\n".join((
        "Source: arXiv paper full text",
        f"Title: {record['title']}",
        f"Authors: {record['authors'] or 'not reported'}",
        f"arXiv ID and version: {record['arxiv_id']}",
        f"Declared license: {license_record['license_name']} ({license_record['license_uri']})",
        f"arXiv OAI-PMH metadata datestamp: {license_record['datestamp'] or 'not reported'}",
        f"PDF: {record['pdf_url']}",
        f"Downloaded PDF SHA-256: {pdf_digest}",
    ))


def _metadata_text(record: dict[str, str], *,
                   license_record: dict[str, str] | None = None,
                   license_issue: str = "") -> str:
    if license_record is not None:
        article_license = (f"Article license observed via OAI: "
                           f"{license_record['license_uri'] or 'not reported'}")
        license_status = ("Paper text not downloaded: license URI is outside "
                          "the redistribution allowlist."
                          if not license_record["license_name"] else
                          "Paper text not downloaded: full-text import was not completed.")
    elif license_issue:
        article_license = "Article license: not verified for the searched version"
        license_status = f"Paper text not downloaded: {license_issue}"
    else:
        article_license = "Article license: not checked; no full text was downloaded"
        license_status = ""
    return "\n".join((
        "Source: arXiv metadata API",
        "Metadata license: CC0 (bibliographic metadata only; not article text)",
        f"Title: {record['title']}",
        f"Abstract: {record['abstract'] or 'not reported'}",
        f"Authors: {record['authors'] or 'not reported'}",
        f"arXiv ID and version: {record['arxiv_id']}",
        f"Published: {record['published'] or 'not reported'}",
        f"Updated: {record['updated'] or 'not reported'}",
        f"Primary category: {record['primary_category'] or 'not reported'}",
        f"Categories: {record['categories'] or 'not reported'}",
        f"DOI: {record['doi'] or 'not reported'}",
        f"Abstract page: {record['abstract_url']}",
        f"PDF URL: {record['pdf_url']}",
        article_license,
        *([license_status] if license_status else []),
    ))


def import_arxiv(query: str, output: str | Path, *, start: int = 0,
                 max_results: int = 100,
                 sort_by: str = "relevance",
                 sort_order: str = "descending",
                 append: bool = False, full_text: bool = False,
                 records: list[dict[str, str]] | None = None,
                 fetch=_fetch, license_fetch=None, pdf_fetch=None,
                 sleep_fn=time.sleep, request_delay: float = 3.0
                 ) -> tuple[int, int, int]:
    """Index metadata; optionally add only version/license-verified CC0/CC BY PDFs."""
    if type(full_text) is not bool:
        raise ValueError("full_text must be a boolean")
    if not isinstance(request_delay, (int, float)) or request_delay < 0:
        raise ValueError("request_delay must be non-negative")
    path = Path(output).expanduser().resolve()
    if path.exists() and not append:
        raise FileExistsError(f"output already exists: {path}")
    if records is None:
        records = search_arxiv(
            query, start=start, max_results=max_results,
            sort_by=sort_by, sort_order=sort_order, fetch=fetch)
    elif any(not isinstance(record, dict)
             or not isinstance(record.get("arxiv_id"), str)
             or not re.fullmatch(r"[\w.\-/]+v\d+", record["arxiv_id"])
             or not isinstance(record.get("title"), str)
             for record in records):
        raise ValueError("provided arXiv records are malformed")
    if not records:
        raise ValueError("arXiv search returned no valid records")
    index = CRMSSQLiteResearchIndex(path)
    added = duplicates = skipped = 0
    try:
        for position, record in enumerate(records):
            document_id = f"arxiv:{record['arxiv_id']}"
            exists = index.contains_document(document_id)
            existing_text = index.document(document_id).text if exists else ""
            already_full = "Source: arXiv paper full text" in existing_text
            already_license_checked = (
                "Article license observed via OAI:" in existing_text
                and "Paper text not downloaded: full-text import was not completed."
                not in existing_text)
            if exists and (not full_text or already_full
                           or already_license_checked):
                duplicates += 1
                continue
            if full_text:
                if position and request_delay:
                    sleep_fn(request_delay)
                license_params = {
                    "verb": "GetRecord",
                    "identifier": f"oai:arXiv.org:{_split_arxiv_version(record['arxiv_id'])[0]}",
                    "metadataPrefix": "arXivRaw",
                }
                license_payload = (license_fetch or fetch)(
                    OAI + "?" + urlencode(license_params), max_bytes=MAX_RESPONSE)
                try:
                    license_record = resolve_arxiv_license(
                        license_payload, record["arxiv_id"])
                except ValueError as error:
                    print(f"Skipped {record['arxiv_id']}: {error}", file=sys.stderr)
                    skipped += 1
                    with index._bulk_write_context():
                        index.add_document(document_id, record["title"],
                                           _metadata_text(
                                               record, license_issue=str(error)),
                                           record["abstract_url"],
                                           replace=exists)
                    if not exists:
                        added += 1
                    continue
                if not license_record["license_name"]:
                    skipped += 1
                    with index._bulk_write_context():
                        index.add_document(document_id, record["title"],
                                           _metadata_text(
                                               record, license_record=license_record),
                                           record["abstract_url"],
                                           replace=exists)
                    if not exists:
                        added += 1
                    continue
                pdf_url = record["pdf_url"]
                payload = (pdf_fetch or fetch)(pdf_url, max_bytes=MAX_PDF)
                if (not isinstance(payload, bytes) or len(payload) > MAX_PDF
                        or not payload.startswith(b"%PDF-")):
                    raise ValueError(
                        "arXiv PDF response is invalid, not a PDF, or exceeds 64 MiB")
                with tempfile.TemporaryDirectory(prefix="crms-arxiv-pdf-") as folder:
                    pdf_path = Path(folder) / "paper.pdf"
                    pdf_path.write_bytes(payload)
                    with index._bulk_write_context():
                        index.add_pdf(pdf_path, document_id=document_id,
                                      title=record["title"],
                                      location=record["abstract_url"],
                                      replace=exists)
                        stored = index.document(document_id)
                        digest = hashlib.sha256(payload).hexdigest()
                        attribution = _fulltext_attribution(
                            record, license_record, digest)
                        pages = stored.pages
                        if not pages:
                            raise ValueError("PDF extraction did not preserve page boundaries")
                        pages = (attribution + "\n\n" + pages[0], *pages[1:])
                        index.add_document(document_id, record["title"],
                                           "\n\f\n".join(pages),
                                           record["abstract_url"],
                                           replace=True, pages=pages)
                added += 1
            else:
                with index._bulk_write_context():
                    index.add_document(document_id, record["title"],
                                       _metadata_text(record),
                                       record["abstract_url"])
                added += 1
        if added == 0 and duplicates == 0 and skipped == 0:
            raise ValueError("arXiv response had no indexable records")
        return added, duplicates, skipped
    finally:
        index.close()


def _record_from_indexed_document(document) -> dict[str, str]:
    """Recover the exact arXiv record fields needed for license upgrade."""
    if not document.document_id.startswith("arxiv:"):
        raise ValueError("document is not an indexed arXiv record")
    arxiv_id = document.document_id.removeprefix("arxiv:")
    _split_arxiv_version(arxiv_id)
    fields = {}
    for line in document.text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields.setdefault(key.strip(), value.strip())
    return {
        "arxiv_id": arxiv_id,
        "title": document.title,
        "abstract": fields.get("Abstract", ""),
        "authors": fields.get("Authors", ""),
        "published": fields.get("Published", ""),
        "updated": fields.get("Updated", ""),
        "categories": fields.get("Categories", ""),
        "primary_category": fields.get("Primary category", ""),
        "doi": fields.get("DOI", ""),
        "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


def upgrade_existing_arxiv_full_text(
        output: str | Path, *, max_records: int = 100,
        retry_failed: bool = False,
        request_delay: float = 3.0,
        license_fetch=None, pdf_fetch=None, sleep_fn=time.sleep
        ) -> tuple[int, int, int]:
    """Upgrade unchecked local arXiv metadata in bounded resumable batches.

    License outcomes are written back into each metadata record. Re-running
    skips full text and already checked licenses, so each invocation advances
    through the remaining unchecked records without a separate checkpoint.
    """
    if type(max_records) is not int or not 1 <= max_records <= 1000:
        raise ValueError("max_records must be between 1 and 1000")
    if type(retry_failed) is not bool:
        raise ValueError("retry_failed must be a boolean")
    if not isinstance(request_delay, (int, float)) or request_delay < 0:
        raise ValueError("request_delay must be non-negative")
    path = Path(output).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"arXiv index does not exist: {path}")
    index = CRMSSQLiteResearchIndex(path)
    try:
        records = []
        for document in sorted(index.documents(),
                               key=lambda item: item.document_id):
            if not document.document_id.startswith("arxiv:"):
                continue
            if "Source: arXiv paper full text" in document.text:
                continue
            unchecked = ("Article license: not checked; no full text was downloaded"
                         in document.text)
            eligible_but_not_downloaded = (
                "Paper text not downloaded: full-text import was not completed."
                in document.text)
            retryable_failure = (retry_failed and
                                 "Article license: not verified for the searched version"
                                 in document.text)
            if not (unchecked or eligible_but_not_downloaded
                    or retryable_failure):
                continue
            records.append(_record_from_indexed_document(document))
            if len(records) >= max_records:
                break
    finally:
        index.close()
    if not records:
        return 0, 0, 0
    return import_arxiv(
        "", path, append=True, full_text=True, records=records,
        license_fetch=license_fetch, pdf_fetch=pdf_fetch,
        sleep_fn=sleep_fn, request_delay=request_delay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query",
                        help='arXiv API query, e.g. "all:formal verification"')
    mode.add_argument("--upgrade-existing-full-text", action="store_true",
                      help="license-check unchecked arXiv records already in the index")
    parser.add_argument("--output", type=Path, required=True,
                        help="CRMS SQLite research index")
    parser.add_argument("--max-results", type=int, default=100,
                        help="maximum results in this API request (1-100)")
    parser.add_argument("--start", type=int, default=0,
                        help="zero-based result offset; advance it between --append runs")
    parser.add_argument("--sort-by", choices=("relevance", "lastUpdatedDate",
                                               "submittedDate"),
                        default="relevance",
                        help="arXiv ordering (use submittedDate for recent research)")
    parser.add_argument("--sort-order", choices=("ascending", "descending"),
                        default="descending", help="arXiv result order")
    parser.add_argument("--append", action="store_true",
                        help="append to an existing CRMS SQLite index")
    parser.add_argument("--full-text", action="store_true",
                        help="fetch only CC0/CC BY PDFs after exact-version OAI license verification")
    parser.add_argument("--max-records", type=int, default=100,
                        help="maximum unchecked existing records per upgrade run (1-1000)")
    parser.add_argument("--request-delay", type=float, default=3.0,
                        help="seconds between OAI/PDF record requests (default: 3)")
    parser.add_argument("--retry-failed-license-checks", action="store_true",
                        help="include prior exact-version OAI failures in upgrade runs")
    args = parser.parse_args()
    try:
        if args.upgrade_existing_full_text:
            if args.full_text or not args.append:
                parser.error("--upgrade-existing-full-text requires --append and cannot be combined with --full-text")
            added, duplicates, skipped = upgrade_existing_arxiv_full_text(
                args.output, max_records=args.max_records,
                retry_failed=args.retry_failed_license_checks,
                request_delay=args.request_delay)
        else:
            added, duplicates, skipped = import_arxiv(
                args.query, args.output, start=args.start,
                max_results=args.max_results,
                sort_by=args.sort_by, sort_order=args.sort_order,
                append=args.append, full_text=args.full_text,
                request_delay=args.request_delay)
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(f"Indexed {added} arXiv records; skipped {duplicates} duplicates and {skipped} license/version exclusions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
